#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    report_generator.py
# Description: Generates CSV tariff comparison reports and opens them in
#              LibreOffice (or Numbers as fallback).
# Author:      CliveS & Claude Sonnet 4.6
# Date:        02-05-2026
# Version:     1.0

import csv
import os
import subprocess
from datetime import date, datetime


def generate_report(comparison, date_from, date_to, output_dir, export_tariff_name):
    """Write the comparison result as a CSV file.

    Args:
        comparison:        dict returned by tariff_engine.run_comparison()
        date_from:         date object
        date_to:           date object
        output_dir:        directory to write into
        export_tariff_name: display name of the export tariff used

    Returns the path to the written CSV file, or None on error.
    """
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename  = f"tariff_comparison_{date_from}_{date_to}_{timestamp}.csv"
    path      = os.path.join(output_dir, filename)

    results   = comparison.get("results", [])
    monthly   = comparison.get("monthly", {})
    totals    = comparison.get("raw_totals", {})
    slots     = comparison.get("slots", 0)
    days      = comparison.get("days", 0)
    baseline  = results[0]["total_cost_p"] if results else 0.0

    # Find actual Tracker row for baseline label
    tracker_row = next((r for r in results if r["tariff_key"] == "tracker"), None)
    if tracker_row:
        baseline = tracker_row["total_cost_p"]

    try:
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)

            # Title block
            w.writerow(["Tariff Analyser - Comparison Report"])
            w.writerow(["Generated:", datetime.now().strftime("%d/%m/%Y %H:%M")])
            w.writerow(["Date range:", f"{date_from}", "to", f"{date_to}"])
            w.writerow(["Days:", days, "    Slots:", slots,
                        "    (48 slots/day = full coverage)"])
            w.writerow(["Export tariff used:", export_tariff_name])
            w.writerow([])

            # Summary table
            w.writerow(["TARIFF COMPARISON SUMMARY"])
            w.writerow([
                "Tariff", "Import Cost", "Export Revenue", "Net Energy",
                "Standing Charges", "Total Cost", "vs Tracker", "Coverage"
            ])
            w.writerow([
                "", "(GBP)", "(GBP)", "(GBP)", "(GBP)", "(GBP)", "(GBP)", "(%)"
            ])

            for r in results:
                total_gbp    = r["total_cost_p"]    / 100.0
                import_gbp   = r["import_cost_p"]   / 100.0
                export_gbp   = r["export_revenue_p"] / 100.0
                net_gbp      = r["net_cost_p"]       / 100.0
                standing_gbp = r["standing_charge_p"] / 100.0
                vs_tracker   = (r["total_cost_p"] - baseline) / 100.0
                marker = ""
                if r["tariff_key"] == "tracker":
                    marker = " (ACTUAL)"
                elif vs_tracker < 0:
                    marker = " CHEAPER"
                elif vs_tracker > 0:
                    marker = " MORE EXPENSIVE"
                w.writerow([
                    r["tariff_name"] + marker,
                    f"{import_gbp:.2f}",
                    f"{export_gbp:.2f}",
                    f"{net_gbp:.2f}",
                    f"{standing_gbp:.2f}",
                    f"{total_gbp:.2f}",
                    f"{vs_tracker:+.2f}",
                    f"{r['coverage_pct']:.0f}%"
                ])
            w.writerow([])

            # Raw energy totals
            w.writerow(["ENERGY TOTALS FOR PERIOD"])
            w.writerow(["Grid Import (kWh):", f"{totals.get('grid_import_kwh', 0):.1f}"])
            w.writerow(["Grid Export (kWh):", f"{totals.get('grid_export_kwh', 0):.1f}"])
            w.writerow(["Solar PV (kWh):",    f"{totals.get('pv_kwh', 0):.1f}"])
            w.writerow(["Home Load (kWh):",   f"{totals.get('home_kwh', 0):.1f}"])
            if totals.get("home_kwh", 0) > 0:
                self_suff = (1.0 - totals.get("grid_import_kwh", 0) /
                             totals["home_kwh"]) * 100.0
                w.writerow(["Self-sufficiency:", f"{self_suff:.1f}%"])
            w.writerow([])

            # Monthly breakdown
            if monthly:
                tariff_keys  = [r["tariff_key"]  for r in results]
                tariff_names = [r["tariff_name"] for r in results]

                w.writerow(["MONTHLY NET COST BREAKDOWN (GBP, energy cost only, no standing charge)"])
                header = ["Month"] + tariff_names + ["Cheapest"]
                w.writerow(header)

                for month in sorted(monthly.keys()):
                    m_data = monthly[month]
                    row_vals = [month]
                    min_cost = None
                    min_name = ""
                    for key, name in zip(tariff_keys, tariff_names):
                        val = m_data.get(key, 0.0) / 100.0
                        row_vals.append(f"{val:.2f}")
                        if min_cost is None or val < min_cost:
                            min_cost = val
                            min_name = name
                    row_vals.append(min_name)
                    w.writerow(row_vals)
                w.writerow([])

            # Notes
            w.writerow(["NOTES"])
            w.writerow(["1. Comparison assumes identical energy consumption patterns across all tariffs."])
            w.writerow(["   Actual savings on time-of-use tariffs (Go, Agile) may be higher"])
            w.writerow(["   because battery dispatch would be optimised for cheap-window charging."])
            w.writerow(["2. Agile coverage below 100% means price data was not available for all slots;"])
            w.writerow(["   those slots are excluded from the Agile cost calculation."])
            w.writerow(["3. Standing charges use published rates and may differ from your actual contract."])
            w.writerow(["4. All costs include VAT at 5%."])

    except Exception as exc:
        return None, str(exc)

    return path, None


def open_in_libreoffice(filepath, log_fn=None):
    """Open the CSV in LibreOffice Calc, or Numbers as fallback."""
    def _log(msg, level="INFO"):
        if log_fn:
            log_fn(msg, level=level)

    libreoffice_paths = [
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        "/Applications/LibreOffice.app",
    ]

    for lo_path in libreoffice_paths:
        if os.path.exists(lo_path):
            try:
                subprocess.Popen(["open", "-a", "LibreOffice", filepath])
                _log(f"Opened in LibreOffice: {filepath}")
                return True
            except Exception as exc:
                _log(f"LibreOffice open failed: {exc}", level="WARNING")

    # Fallback: Numbers
    try:
        subprocess.Popen(["open", "-a", "Numbers", filepath])
        _log(f"LibreOffice not found - opened in Numbers: {filepath}")
        return True
    except Exception:
        pass

    # Last resort: default app
    try:
        subprocess.Popen(["open", filepath])
        _log(f"Opened with default app: {filepath}")
        return True
    except Exception as exc:
        _log(f"Could not open file: {exc}", level="WARNING")
        return False


def export_raw_csv(timeseries_db_path, output_dir, log_fn=None):
    """Dump the full halfhourly table as a raw CSV."""
    import sqlite3
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(output_dir, f"raw_energy_data_{timestamp}.csv")

    def _log(msg, level="INFO"):
        if log_fn:
            log_fn(msg, level=level)

    try:
        con  = sqlite3.connect(timeseries_db_path)
        rows = con.execute(
            "SELECT * FROM halfhourly ORDER BY slot_start"
        ).fetchall()
        cols = [d[0] for d in con.execute(
            "SELECT * FROM halfhourly LIMIT 0"
        ).description or []]
        # Fallback column names
        if not cols:
            cols = ["id", "slot_start", "slot_end",
                    "grid_import_kwh", "grid_export_kwh", "pv_kwh", "home_kwh",
                    "battery_soc_start_pct", "battery_soc_end_pct", "battery_net_kwh",
                    "tracker_price_p", "manager_action"]
        con.close()

        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(cols)
            w.writerows(rows)

        _log(f"Raw data exported: {len(rows)} rows to {path}")
        return path, None

    except Exception as exc:
        return None, str(exc)
