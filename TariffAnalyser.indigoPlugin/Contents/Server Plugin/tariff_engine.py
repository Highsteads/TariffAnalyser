#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    tariff_engine.py
# Description: Tariff comparison engine - applies UK energy tariff pricing
#              to half-hourly energy flow data from energy_timeseries.db
# Author:      CliveS & Claude Sonnet 4.6
# Date:        02-05-2026
# Version:     1.0

import sqlite3
from datetime import datetime, date, timedelta

# ---------------------------------------------------------------------------
# Tariff definitions
# Each tariff has a 'type' that controls how rates are calculated:
#   fixed        - single unit rate all hours
#   tou          - time-of-use: cheap window + peak rate
#   tou_multi    - multiple cheap windows (Cosy)
#   variable_db  - rate stored per-slot in the timeseries DB (Tracker actual)
#   agile        - half-hourly rate from agile_prices DB
# ---------------------------------------------------------------------------

IMPORT_TARIFFS = {
    "tracker": {
        "name":              "Octopus Tracker (actual)",
        "type":              "variable_db",
        "standing_p_day":    61.64,
    },
    "go": {
        "name":              "Octopus Go",
        "type":              "tou",
        "cheap_start":       "00:30",
        "cheap_end":         "05:30",
        "cheap_p":           7.5,
        "peak_p":            24.0,
        "standing_p_day":    53.35,
    },
    "go_faster": {
        "name":              "Octopus Go Faster",
        "type":              "tou",
        "cheap_start":       "23:30",
        "cheap_end":         "05:30",
        "cheap_p":           7.5,
        "peak_p":            24.0,
        "standing_p_day":    53.35,
    },
    "agile": {
        "name":              "Octopus Agile",
        "type":              "agile",
        "standing_p_day":    53.35,
        "cap_p":             100.0,   # Agile price cap per Octopus terms
    },
    "cosy": {
        "name":              "Octopus Cosy",
        "type":              "tou_multi",
        "slots": [
            {"start": "04:00", "end": "07:00", "rate_p": 12.0},
            {"start": "13:00", "end": "16:00", "rate_p": 12.0},
        ],
        "peak_start":        "16:00",
        "peak_end":          "19:00",
        "peak_p":            38.0,
        "shoulder_p":        26.0,
        "standing_p_day":    53.35,
    },
    "economy7": {
        "name":              "Economy 7 (typical)",
        "type":              "tou",
        "cheap_start":       "00:30",
        "cheap_end":         "07:30",
        "cheap_p":           15.0,
        "peak_p":            30.0,
        "standing_p_day":    61.64,
    },
    "ofgem_cap": {
        "name":              "Ofgem Price Cap (SVT)",
        "type":              "fixed",
        "rate_p":            24.50,
        "standing_p_day":    61.64,
    },
    "eon_fixed": {
        "name":              "E.ON Next Fixed (typical)",
        "type":              "fixed",
        "rate_p":            24.0,
        "standing_p_day":    60.0,
    },
    "edf_fixed": {
        "name":              "EDF Fixed (typical)",
        "type":              "fixed",
        "rate_p":            24.0,
        "standing_p_day":    60.0,
    },
    "scottishpower_fixed": {
        "name":              "Scottish Power Fixed (typical)",
        "type":              "fixed",
        "rate_p":            24.0,
        "standing_p_day":    60.0,
    },
}

EXPORT_TARIFFS = {
    "outgoing_12p": {
        "name":  "Octopus Outgoing 12p (actual)",
        "type":  "fixed",
        "rate_p": 12.0,
    },
    "agile_outgoing": {
        "name":  "Octopus Agile Outgoing",
        "type":  "agile",
    },
    "seg_min": {
        "name":  "SEG Minimum (Ofgem floor)",
        "type":  "fixed",
        "rate_p": 1.63,
    },
    "seg_typical": {
        "name":  "SEG Typical (e.g. EDF/E.ON)",
        "type":  "fixed",
        "rate_p": 7.5,
    },
}


def _slot_in_window(slot_start_str, window_start_hhmm, window_end_hhmm):
    """Return True if slot_start falls inside [window_start, window_end).

    Handles overnight windows (e.g. 23:30-05:30) correctly.
    slot_start_str format: 'YYYY-MM-DDTHH:MM:SS'
    """
    t = datetime.strptime(slot_start_str, "%Y-%m-%dT%H:%M:%S").strftime("%H:%M")
    if window_start_hhmm <= window_end_hhmm:
        return window_start_hhmm <= t < window_end_hhmm
    # overnight: wraps midnight
    return t >= window_start_hhmm or t < window_end_hhmm


def _import_rate_for_slot(slot_start, tariff, agile_import_rates):
    """Return the import rate in p/kWh for this 30-min slot under the given tariff."""
    ttype = tariff["type"]

    if ttype == "fixed":
        return tariff["rate_p"]

    if ttype == "variable_db":
        return None  # caller uses per-slot tracker_price_p from the DB row

    if ttype == "tou":
        if _slot_in_window(slot_start, tariff["cheap_start"], tariff["cheap_end"]):
            return tariff["cheap_p"]
        return tariff["peak_p"]

    if ttype == "tou_multi":
        for slot in tariff["slots"]:
            if _slot_in_window(slot_start, slot["start"], slot["end"]):
                return slot["rate_p"]
        if _slot_in_window(slot_start, tariff["peak_start"], tariff["peak_end"]):
            return tariff["peak_p"]
        return tariff["shoulder_p"]

    if ttype == "agile":
        cap = tariff.get("cap_p", 9999.0)
        rate = agile_import_rates.get(slot_start)
        if rate is not None:
            return min(rate, cap)
        return None  # no data for this slot

    return None


def _export_rate_for_slot(slot_start, tariff, agile_export_rates):
    """Return the export rate in p/kWh for this slot."""
    if tariff["type"] == "fixed":
        return tariff["rate_p"]
    if tariff["type"] == "agile":
        return agile_export_rates.get(slot_start)
    return None


def run_comparison(
    timeseries_db_path,
    agile_db_path,
    region,
    date_from,
    date_to,
    import_tariff_keys=None,
    export_tariff_key="outgoing_12p",
):
    """Run tariff comparison over the given date range.

    Args:
        timeseries_db_path: path to SigenEnergyManager energy_timeseries.db
        agile_db_path:       path to TariffAnalyser agile_prices.db
        region:              Octopus region code (e.g. 'F')
        date_from:           date object (inclusive)
        date_to:             date object (inclusive)
        import_tariff_keys:  list of keys from IMPORT_TARIFFS to compare;
                             None = all
        export_tariff_key:   key from EXPORT_TARIFFS to use for all import tariffs

    Returns a dict:
        {
          "slots":   int  - number of slots with data,
          "days":    int  - number of calendar days,
          "results": [
              {
                "tariff_key": str,
                "tariff_name": str,
                "import_cost_p": float,
                "export_revenue_p": float,
                "net_cost_p": float,
                "standing_charge_p": float,
                "total_cost_p": float,
                "coverage_pct": float,   - slots with a valid rate / total slots
              },
              ...
          ],
          "monthly": {  "YYYY-MM": { tariff_key: net_cost_p, ... }, ...  },
          "raw_totals": {
              "grid_import_kwh": float,
              "grid_export_kwh": float,
              "pv_kwh": float,
              "home_kwh": float,
          }
        }
    """
    if import_tariff_keys is None:
        import_tariff_keys = list(IMPORT_TARIFFS.keys())

    export_tariff = EXPORT_TARIFFS[export_tariff_key]

    # Load agile prices for the period
    agile_import = _load_agile_prices(agile_db_path, region, date_from, date_to, "import")
    agile_export = _load_agile_prices(agile_db_path, region, date_from, date_to, "export")

    # Load timeseries rows
    rows = _load_timeseries(timeseries_db_path, date_from, date_to)

    if not rows:
        return {"slots": 0, "days": 0, "results": [], "monthly": {}, "raw_totals": {}}

    # Compute calendar days in range
    days = (date_to - date_from).days + 1

    # Accumulators: {tariff_key: {import_p, export_p, valid_slots}}
    acc   = {k: {"import_p": 0.0, "export_p": 0.0, "valid_slots": 0}
             for k in import_tariff_keys}
    monthly = {}   # {month_str: {tariff_key: net_cost_p}}
    totals  = {"grid_import_kwh": 0.0, "grid_export_kwh": 0.0,
               "pv_kwh": 0.0, "home_kwh": 0.0}

    for row in rows:
        (slot_start, slot_end,
         imp_kwh, exp_kwh, pv_kwh, home_kwh,
         soc_start, soc_end, bat_net,
         tracker_p, action) = row

        totals["grid_import_kwh"] += imp_kwh or 0.0
        totals["grid_export_kwh"] += exp_kwh or 0.0
        totals["pv_kwh"]          += pv_kwh  or 0.0
        totals["home_kwh"]        += home_kwh or 0.0

        month_str = slot_start[:7]  # 'YYYY-MM'
        if month_str not in monthly:
            monthly[month_str] = {k: 0.0 for k in import_tariff_keys}

        # Export revenue is the same regardless of import tariff
        exp_rate = _export_rate_for_slot(slot_start, export_tariff, agile_export)
        exp_rev  = (exp_kwh or 0.0) * (exp_rate or 0.0)

        for key in import_tariff_keys:
            tariff = IMPORT_TARIFFS[key]
            if tariff["type"] == "variable_db":
                imp_rate = tracker_p
            else:
                imp_rate = _import_rate_for_slot(slot_start, tariff, agile_import)

            if imp_rate is None:
                continue  # no data for this slot — skip

            cost = (imp_kwh or 0.0) * imp_rate
            acc[key]["import_p"]   += cost
            acc[key]["export_p"]   += exp_rev
            acc[key]["valid_slots"] += 1
            monthly[month_str][key] += cost - exp_rev

    results = []
    total_slots = len(rows)
    for key in import_tariff_keys:
        tariff = IMPORT_TARIFFS[key]
        a = acc[key]
        standing = tariff.get("standing_p_day", 0.0) * days
        net      = a["import_p"] - a["export_p"]
        total    = net + standing
        coverage = (a["valid_slots"] / total_slots * 100.0) if total_slots else 0.0
        results.append({
            "tariff_key":       key,
            "tariff_name":      tariff["name"],
            "import_cost_p":    round(a["import_p"],   2),
            "export_revenue_p": round(a["export_p"],   2),
            "net_cost_p":       round(net,              2),
            "standing_charge_p": round(standing,        2),
            "total_cost_p":     round(total,            2),
            "coverage_pct":     round(coverage,         1),
        })

    # Sort by total_cost_p ascending (cheapest first)
    results.sort(key=lambda r: r["total_cost_p"])

    return {
        "slots":       total_slots,
        "days":        days,
        "results":     results,
        "monthly":     monthly,
        "raw_totals":  {k: round(v, 3) for k, v in totals.items()},
    }


def calculate_savings(db_path, export_rate_p, date_from, date_to):
    """Calculate solar savings for a date range against the actual Tracker tariff.

    Savings = what you would have paid without solar − what you actually paid.
    - Avoided import: solar/battery energy used at home × Tracker rate per slot
    - Export revenue: grid export × flat export rate
    Falls back to Ofgem cap (24.5p) for slots with no Tracker price.

    Returns a dict:
        pv_kwh             total solar generated (kWh)
        pv_to_home_kwh     solar used at home, not exported (kWh)
        export_kwh         total exported (kWh)
        home_kwh           total home consumption (kWh)
        grid_import_kwh    total grid import (kWh)
        avoided_import_p   pence saved by using own solar instead of buying
        export_revenue_p   pence earned from exporting
        total_savings_p    total savings in pence
        cost_with_solar_p  actual energy cost (import cost − export revenue)
        cost_without_solar_p  what the bill would have been with no solar
        slots              number of slots processed
    """
    _OFGEM_FALLBACK_P = 24.5  # pence/kWh when Tracker price missing

    rows = _load_timeseries(db_path, date_from, date_to)
    if not rows:
        return {
            "pv_kwh": 0.0, "pv_to_home_kwh": 0.0, "export_kwh": 0.0,
            "home_kwh": 0.0, "grid_import_kwh": 0.0,
            "avoided_import_p": 0.0, "export_revenue_p": 0.0,
            "total_savings_p": 0.0, "cost_with_solar_p": 0.0,
            "cost_without_solar_p": 0.0, "slots": 0,
        }

    avoided_p      = 0.0
    export_rev_p   = 0.0
    cost_actual_p  = 0.0
    cost_no_solar_p = 0.0
    total_pv       = 0.0
    total_exp      = 0.0
    total_home     = 0.0
    total_imp      = 0.0

    for row in rows:
        imp_kwh  = row[2] or 0.0
        exp_kwh  = row[3] or 0.0
        pv_kwh   = row[4] or 0.0
        home_kwh = row[5] or 0.0
        rate_p   = row[9] or _OFGEM_FALLBACK_P

        # Energy met by solar/battery rather than the grid
        solar_at_home = max(0.0, home_kwh - imp_kwh)
        slot_exp_rev  = exp_kwh * export_rate_p

        avoided_p      += solar_at_home * rate_p
        export_rev_p   += slot_exp_rev
        cost_actual_p  += imp_kwh * rate_p - slot_exp_rev
        cost_no_solar_p += home_kwh * rate_p

        total_pv  += pv_kwh
        total_exp += exp_kwh
        total_home += home_kwh
        total_imp  += imp_kwh

    return {
        "pv_kwh":              round(total_pv,          3),
        "pv_to_home_kwh":      round(total_pv - total_exp, 3),
        "export_kwh":          round(total_exp,         3),
        "home_kwh":            round(total_home,        3),
        "grid_import_kwh":     round(total_imp,         3),
        "avoided_import_p":    round(avoided_p,         2),
        "export_revenue_p":    round(export_rev_p,      2),
        "total_savings_p":     round(avoided_p + export_rev_p, 2),
        "cost_with_solar_p":   round(cost_actual_p,     2),
        "cost_without_solar_p": round(cost_no_solar_p,  2),
        "slots":               len(rows),
    }


def get_coverage(timeseries_db_path):
    """Return (earliest_date, latest_date, total_slots) from the DB."""
    try:
        con = sqlite3.connect(timeseries_db_path)
        row = con.execute(
            "SELECT MIN(slot_start), MAX(slot_start), COUNT(*) FROM halfhourly"
        ).fetchone()
        con.close()
        if row and row[0]:
            earliest = row[0][:10]
            latest   = row[1][:10]
            count    = row[2]
            return earliest, latest, count
    except Exception:
        pass
    return None, None, 0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_timeseries(db_path, date_from, date_to):
    """Return list of rows from halfhourly table for the date range."""
    if not db_path or not __import__('os').path.exists(db_path):
        return []
    try:
        con  = sqlite3.connect(db_path)
        rows = con.execute(
            """SELECT slot_start, slot_end,
                      grid_import_kwh, grid_export_kwh, pv_kwh, home_kwh,
                      battery_soc_start_pct, battery_soc_end_pct, battery_net_kwh,
                      tracker_price_p, manager_action
               FROM halfhourly
               WHERE slot_start >= ? AND slot_start < ?
               ORDER BY slot_start""",
            (date_from.strftime("%Y-%m-%dT00:00:00"),
             (date_to + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00"))
        ).fetchall()
        con.close()
        return rows
    except Exception:
        return []


def _load_agile_prices(db_path, region, date_from, date_to, direction):
    """Return dict {slot_start_str: price_p} from agile_prices DB."""
    table = "agile_import" if direction == "import" else "agile_export"
    if not db_path or not __import__('os').path.exists(db_path):
        return {}
    try:
        con  = sqlite3.connect(db_path)
        rows = con.execute(
            f"SELECT slot_start, price_p FROM {table} "
            f"WHERE region=? AND slot_start >= ? AND slot_start < ?",
            (region,
             date_from.strftime("%Y-%m-%dT00:00:00"),
             (date_to + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00"))
        ).fetchall()
        con.close()
        return {r[0]: r[1] for r in rows}
    except Exception:
        return {}
