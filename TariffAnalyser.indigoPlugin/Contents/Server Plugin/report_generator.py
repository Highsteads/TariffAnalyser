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

    Returns (path, error_string). error_string is None on success.
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

    tracker_row = next((r for r in results if r["tariff_key"] == "tracker"), None)
    baseline    = tracker_row["total_cost_p"] if tracker_row else 0.0

    # UK date format throughout
    from_uk = date_from.strftime("%d/%m/%Y")
    to_uk   = date_to.strftime("%d/%m/%Y")
    slots_per_day = slots / days if days else 0
    coverage_note = f"{slots_per_day:.1f} slots/day  (48 = full coverage)"

    def gbp(pence):
        return f"£{pence / 100.0:.2f}"

    try:
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)

            # Title block — each row is label + single value cell
            w.writerow(["Tariff Analyser - Comparison Report"])
            w.writerow(["Generated:", datetime.now().strftime("%d/%m/%Y %H:%M")])
            w.writerow(["Date range:", f"{from_uk} to {to_uk}"])
            w.writerow(["Days:", days])
            w.writerow(["Slots recorded:", f"{slots}  ({coverage_note})"])
            w.writerow(["Export tariff:", export_tariff_name])
            w.writerow([])

            # Summary table — marker in its own column
            w.writerow(["TARIFF COMPARISON SUMMARY"])
            w.writerow([
                "Tariff", "",
                "Import Cost", "Export Revenue", "Net Energy Cost",
                "Standing Charges", "Total Cost", "vs Tracker", "Coverage",
            ])
            w.writerow([
                "", "",
                "(GBP)", "(GBP)", "(GBP)", "(GBP)", "(GBP)", "(GBP)", "(%)",
            ])

            for r in results:
                vs_tracker = (r["total_cost_p"] - baseline) / 100.0
                if r["tariff_key"] == "tracker":
                    marker = "actual"
                elif vs_tracker < 0:
                    marker = f"CHEAPER by £{abs(vs_tracker):.2f}"
                elif vs_tracker > 0:
                    marker = f"more expensive by £{vs_tracker:.2f}"
                else:
                    marker = "same"
                w.writerow([
                    r["tariff_name"],
                    marker,
                    gbp(r["import_cost_p"]),
                    gbp(r["export_revenue_p"]),
                    gbp(r["net_cost_p"]),
                    gbp(r["standing_charge_p"]),
                    gbp(r["total_cost_p"]),
                    f"£{vs_tracker:+.2f}",
                    f"{r['coverage_pct']:.0f}%",
                ])
            w.writerow([])

            # Raw energy totals
            w.writerow(["ENERGY TOTALS FOR PERIOD"])
            w.writerow(["Grid Import:", f"{totals.get('grid_import_kwh', 0):.1f} kWh"])
            w.writerow(["Grid Export:", f"{totals.get('grid_export_kwh', 0):.1f} kWh"])
            w.writerow(["Solar PV:",   f"{totals.get('pv_kwh', 0):.1f} kWh"])
            w.writerow(["Home Load:",  f"{totals.get('home_kwh', 0):.1f} kWh"])
            home_kwh = totals.get("home_kwh", 0)
            if home_kwh > 0:
                self_suff = (1.0 - totals.get("grid_import_kwh", 0) / home_kwh) * 100.0
                w.writerow(["Self-sufficiency:", f"{self_suff:.1f}%"])
            w.writerow([])

            # Monthly net energy cost breakdown (no standing charges)
            if monthly:
                tariff_keys  = [r["tariff_key"]  for r in results]
                tariff_names = [r["tariff_name"] for r in results]

                w.writerow(["MONTHLY NET ENERGY COST BREAKDOWN",
                            "(GBP energy cost only — standing charges not included)"])
                w.writerow(["Month"] + tariff_names + ["Cheapest tariff"])

                for month in sorted(monthly.keys()):
                    # Display month as UK MMM YYYY
                    try:
                        m_label = datetime.strptime(month, "%Y-%m").strftime("%b %Y")
                    except ValueError:
                        m_label = month
                    m_data   = monthly[month]
                    row_vals = [m_label]
                    min_cost = None
                    min_name = ""
                    for key, name in zip(tariff_keys, tariff_names):
                        val = m_data.get(key, 0.0) / 100.0
                        row_vals.append(f"£{val:.2f}")
                        if min_cost is None or val < min_cost:
                            min_cost = val
                            min_name = name
                    row_vals.append(min_name)
                    w.writerow(row_vals)
                w.writerow([])

            # Notes — each point as a single cell so commas inside don't split
            w.writerow(["NOTES"])
            w.writerow(["1. Comparison assumes identical energy consumption patterns across all tariffs. "
                        "Actual savings on time-of-use tariffs (Go and Agile) may be higher "
                        "because battery dispatch would be optimised for cheap-window charging."])
            w.writerow(["2. Agile coverage below 100% means price data was not available for all slots; "
                        "those slots are excluded from the Agile cost calculation."])
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


def generate_daily_report(db_path, report_date, output_dir, export_rate_p=12.0, log_fn=None):
    """Generate an HTML daily energy summary for a single day.

    Args:
        db_path:       path to energy_timeseries.db
        report_date:   date object
        output_dir:    directory to write HTML into
        export_rate_p: export rate in p/kWh
        log_fn:        optional logging callable

    Returns (path, error_string). error_string is None on success.
    """
    import sqlite3

    def _log(msg, level="INFO"):
        if log_fn:
            log_fn(msg, level=level)

    next_day = report_date + timedelta(days=1)
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
            (f"{report_date.isoformat()}T00:00:00",
             f"{next_day.isoformat()}T00:00:00"),
        ).fetchall()
        con.close()
    except Exception as exc:
        return None, str(exc)

    if not rows:
        return None, f"No data for {report_date.strftime('%d/%m/%Y')}"

    # Totals
    total_imp  = sum(r[2] or 0.0 for r in rows)
    total_exp  = sum(r[3] or 0.0 for r in rows)
    total_pv   = sum(r[4] or 0.0 for r in rows)
    total_home = sum(r[5] or 0.0 for r in rows)

    soc_start     = rows[0][6]
    soc_end       = rows[-1][7]
    import_cost_p = sum((r[2] or 0.0) * (r[9] or 0.0) for r in rows)
    export_rev_p  = total_exp * export_rate_p
    net_cost_p    = import_cost_p - export_rev_p
    self_suff     = max(0.0, (1.0 - total_imp / total_home) * 100.0) if total_home > 0 else 100.0

    slot_count   = len(rows)
    expected_48  = 48
    completeness = slot_count / expected_48 * 100.0

    day_label    = report_date.strftime("%A, %-d %B %Y")
    generated_at = datetime.now().strftime("%d/%m/%Y %H:%M")

    # ------------------------------------------------------------------ helpers
    def kwh(v):
        return f"{v:.2f}" if v >= 0.005 else "—"

    def cost_cell(p):
        if abs(p) < 0.5:
            return '<td class="dim">—</td>'
        if p > 0:
            return f'<td class="imp">£{p/100:.3f}</td>'
        return f'<td class="exp">−£{abs(p)/100:.3f}</td>'

    def soc_cell(s, e):
        if s is None or e is None:
            return '<td class="dim">—</td>'
        arrow = "↑" if e > s else ("↓" if e < s else "→")
        cls   = "exp" if e >= s else "imp"
        return f'<td><span class="{cls}">{s:.0f}%{arrow}{e:.0f}%</span></td>'

    # ------------------------------------------------------------------ slot rows
    slot_rows = []
    for r in rows:
        t       = r[0][11:16]
        imp     = r[2] or 0.0
        exp     = r[3] or 0.0
        pv      = r[4] or 0.0
        home    = r[5] or 0.0
        rate    = r[9] or 0.0
        action  = r[10] or ""

        imp_cls = ' class="imp"' if imp >= 0.01 else ' class="dim"'
        exp_cls = ' class="exp"' if exp >= 0.01 else ' class="dim"'
        pv_cls  = ' class="pv"'  if pv  >= 0.01 else ' class="dim"'

        badge = (f'<span class="badge">{action}</span>' if action else "")

        slot_rows.append(f"""
        <tr>
          <td class="time">{t}{badge}</td>
          <td{pv_cls}>{kwh(pv)}</td>
          <td>{kwh(home)}</td>
          <td{imp_cls}>{kwh(imp)}</td>
          <td{exp_cls}>{kwh(exp)}</td>
          {soc_cell(r[6], r[7])}
          <td>{rate:.1f}p</td>
          {cost_cell(imp * rate - exp * export_rate_p)}
        </tr>""")

    slot_rows_html = "\n".join(slot_rows)

    # ------------------------------------------------------------------ summary cards
    def card(cls, label, value, unit="kWh"):
        return f"""
        <div class="card {cls}">
          <div class="card-value">{value}</div>
          <div class="card-unit">{unit}</div>
          <div class="card-label">{label}</div>
        </div>"""

    cards_html = (
        card("pv",     "Solar Generated",  f"{total_pv:.2f}")
        + card("home", "Home Consumption", f"{total_home:.2f}")
        + card("imp",  "Grid Import",      f"{total_imp:.2f}")
        + card("exp",  "Grid Export",      f"{total_exp:.2f}")
    )

    # ------------------------------------------------------------------ cost block
    def cost_row(label, value_p, cls=""):
        val = value_p / 100.0
        sign = "−" if val < 0 else ""
        styled = f'<span class="{cls}">£{abs(val):.2f}</span>' if cls else f'£{abs(val):.2f}'
        return f'<div class="crow"><span>{label}</span>{sign}{styled}</div>'

    cost_html = (
        cost_row("Grid import cost",     import_cost_p,  "imp" if import_cost_p > 0 else "")
        + cost_row("Export revenue",    -export_rev_p,   "exp" if export_rev_p  > 0 else "")
        + f'<div class="crow divider"></div>'
        + cost_row("Net energy cost",   net_cost_p,      "imp" if net_cost_p > 0 else "exp")
        + f'<div class="crow"><span>Standing charge</span><span>61.64p/day</span></div>'
        + f'<div class="crow"><span>Self-sufficiency</span>'
          f'<strong>{self_suff:.0f}%</strong></div>'
    )

    # ------------------------------------------------------------------ battery block
    soc_s = soc_start or 0
    soc_e = soc_end   or 0
    bar_colour = "#2e7d32" if soc_e >= 50 else "#f57c00" if soc_e >= 20 else "#c62828"
    bat_change = soc_e - soc_s
    bat_dir    = f"+{bat_change:.0f}%" if bat_change > 0 else f"{bat_change:.0f}%"

    battery_html = f"""
        <div class="crow"><span>Start of day</span><strong>{soc_s:.0f}%</strong></div>
        <div class="crow"><span>End of day</span><strong>{soc_e:.0f}%</strong></div>
        <div class="crow"><span>Change</span><strong>{bat_dir}</strong></div>
        <div class="bat-bar">
          <div class="bat-fill" style="width:{min(soc_e,100):.0f}%;background:{bar_colour}"></div>
        </div>
        <div class="bat-label">{soc_e:.0f}% charged</div>"""

    # ------------------------------------------------------------------ coverage note
    if completeness < 95:
        coverage_note = (f'<p class="warn">⚠ Data coverage: {slot_count} of 48 expected slots '
                         f'({completeness:.0f}%) — totals may be incomplete.</p>')
    else:
        coverage_note = ""

    # ------------------------------------------------------------------ HTML
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Daily Energy Report — {day_label}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
         background: #f0f4f0; color: #333; padding: 24px; font-size: 15px; }}
  .container {{ max-width: 960px; margin: 0 auto; }}

  /* Header */
  .header {{ background: #1b5e20; color: #fff; padding: 22px 28px;
             border-radius: 10px 10px 0 0; }}
  .header h1 {{ font-size: 1.45em; font-weight: 700; letter-spacing: -0.3px; }}
  .header p  {{ opacity: 0.75; font-size: 0.85em; margin-top: 4px; }}

  /* Cards */
  .cards {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin: 10px 0; }}
  .card {{ background: #fff; border-radius: 8px; padding: 18px 12px; text-align: center;
           box-shadow: 0 1px 4px rgba(0,0,0,.08); }}
  .card-value {{ font-size: 2em; font-weight: 700; line-height: 1; }}
  .card-unit  {{ font-size: 0.78em; color: #888; margin-top: 2px; }}
  .card-label {{ font-size: 0.78em; color: #666; margin-top: 6px;
                 text-transform: uppercase; letter-spacing: 0.5px; }}
  .card.pv   .card-value {{ color: #e65100; }}
  .card.home .card-value {{ color: #1565c0; }}
  .card.imp  .card-value {{ color: #b71c1c; }}
  .card.exp  .card-value {{ color: #1b5e20; }}

  /* Two-column panel */
  .panels {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 10px 0; }}
  .panel {{ background: #fff; border-radius: 8px; padding: 18px 20px;
            box-shadow: 0 1px 4px rgba(0,0,0,.08); }}
  .panel h2 {{ font-size: 0.78em; font-weight: 600; color: #777;
               text-transform: uppercase; letter-spacing: 0.6px;
               border-bottom: 1px solid #eee; padding-bottom: 10px; margin-bottom: 12px; }}
  .crow {{ display: flex; justify-content: space-between; padding: 6px 0;
           border-bottom: 1px solid #f5f5f5; font-size: 0.92em; }}
  .crow:last-child {{ border-bottom: none; }}
  .crow.divider {{ border-bottom: 2px solid #e0e0e0; margin: 4px 0; padding: 0; }}

  /* Battery bar */
  .bat-bar   {{ height: 14px; background: #e0e0e0; border-radius: 7px; margin: 14px 0 4px; }}
  .bat-fill  {{ height: 100%; border-radius: 7px; transition: width 0.3s; }}
  .bat-label {{ text-align: center; font-size: 0.82em; color: #666; }}

  /* Table */
  .section {{ background: #fff; border-radius: 8px; padding: 18px 20px; margin: 10px 0;
              box-shadow: 0 1px 4px rgba(0,0,0,.08); overflow-x: auto; }}
  .section h2 {{ font-size: 0.78em; font-weight: 600; color: #777;
                 text-transform: uppercase; letter-spacing: 0.6px;
                 border-bottom: 1px solid #eee; padding-bottom: 10px; margin-bottom: 14px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.88em; }}
  thead th {{ background: #1b5e20; color: #fff; padding: 9px 10px;
              text-align: right; font-weight: 500; white-space: nowrap; }}
  thead th:first-child {{ text-align: left; }}
  tbody tr:hover {{ background: #f7fff7; }}
  tbody tr:nth-child(even) {{ background: #fafafa; }}
  tbody td {{ padding: 7px 10px; text-align: right; border-bottom: 1px solid #f0f0f0; }}
  tbody td:first-child {{ text-align: left; }}
  thead th:last-child, tbody td:last-child {{ border-right: none; }}
  tfoot td {{ padding: 9px 10px; text-align: right; font-weight: 600;
              border-top: 2px solid #1b5e20; background: #f0f7f0; }}
  tfoot td:first-child {{ text-align: left; }}

  /* Colours */
  .imp  {{ color: #b71c1c; }}
  .exp  {{ color: #1b5e20; }}
  .pv   {{ color: #e65100; }}
  .dim  {{ color: #bbb; }}
  .time {{ font-family: 'SF Mono', 'Menlo', monospace; font-size: 0.9em; }}
  .badge {{ display: inline-block; margin-left: 6px; padding: 1px 6px;
            border-radius: 3px; font-size: 0.72em; background: #e8f5e9;
            color: #2e7d32; vertical-align: middle; }}
  .warn {{ background: #fff8e1; border-left: 4px solid #f9a825; padding: 10px 14px;
           margin: 10px 0; border-radius: 4px; font-size: 0.88em; color: #555; }}
  .footer {{ text-align: center; color: #aaa; font-size: 0.78em; margin-top: 16px; }}
</style>
</head>
<body>
<div class="container">

  <div class="header">
    <h1>Daily Energy Report &mdash; {day_label}</h1>
    <p>Generated {generated_at} &nbsp;&bull;&nbsp;
       {slot_count} of 48 slots &nbsp;&bull;&nbsp;
       Export tariff: Octopus Outgoing {export_rate_p:.0f}p</p>
  </div>

  {coverage_note}

  <div class="cards">
    {cards_html}
  </div>

  <div class="panels">
    <div class="panel">
      <h2>Costs &amp; Revenue</h2>
      {cost_html}
    </div>
    <div class="panel">
      <h2>Battery</h2>
      {battery_html}
    </div>
  </div>

  <div class="section">
    <h2>Half-Hourly Breakdown</h2>
    <table>
      <thead>
        <tr>
          <th>Time</th>
          <th>Solar&nbsp;kWh</th>
          <th>Home&nbsp;kWh</th>
          <th>Import&nbsp;kWh</th>
          <th>Export&nbsp;kWh</th>
          <th>Battery&nbsp;SOC</th>
          <th>Rate</th>
          <th>Slot&nbsp;Cost</th>
        </tr>
      </thead>
      <tbody>
        {slot_rows_html}
      </tbody>
      <tfoot>
        <tr>
          <td>Total</td>
          <td class="pv">{total_pv:.2f}</td>
          <td>{total_home:.2f}</td>
          <td class="imp">{total_imp:.2f}</td>
          <td class="exp">{total_exp:.2f}</td>
          <td></td>
          <td></td>
          <td>{'−£' if net_cost_p < 0 else '£'}{abs(net_cost_p)/100:.2f}</td>
        </tr>
      </tfoot>
    </table>
  </div>

  <div class="footer">Tariff Analyser &bull; Sigenergy Home Energy System &bull; {generated_at}</div>

</div>
</body>
</html>"""

    os.makedirs(output_dir, exist_ok=True)
    filename = f"daily_energy_{report_date.isoformat()}.html"
    path     = os.path.join(output_dir, filename)
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(html)
    except Exception as exc:
        return None, str(exc)

    _log(f"[Daily] Report written: {path}")
    return path, None


def open_in_browser(filepath, log_fn=None):
    """Open an HTML file in the system default browser."""
    def _log(msg, level="INFO"):
        if log_fn:
            log_fn(msg, level=level)
    try:
        subprocess.Popen(["open", filepath])
        _log(f"[Daily] Opened in browser: {filepath}")
        return True
    except Exception as exc:
        _log(f"[Daily] Could not open browser: {exc}", level="WARNING")
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
