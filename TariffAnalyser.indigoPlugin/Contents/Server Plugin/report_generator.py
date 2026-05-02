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

    # Extra daily stats
    peak_pv_r    = max(rows, key=lambda r: r[4] or 0.0)
    peak_pv_kwh  = peak_pv_r[4] or 0.0
    peak_pv_time = peak_pv_r[0][11:16] if peak_pv_kwh >= 0.01 else None
    avg_imp_rate = import_cost_p / total_imp if total_imp >= 0.01 else None
    carbon_kg    = total_pv * 0.225   # UK grid average 225 g CO2/kWh

    from collections import Counter
    action_counts = Counter(r[10] for r in rows if r[10])
    action_summary = "  ".join(
        f"{v}&times; {k}" for k, v in sorted(action_counts.items(), key=lambda x: -x[1])
    ) if action_counts else "Self-consuming"

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

    avg_rate_str = f"{avg_imp_rate:.1f}p/kWh" if avg_imp_rate is not None else "—"
    peak_str     = (f"{peak_pv_time} ({peak_pv_kwh:.2f} kWh)"
                    if peak_pv_time else "—")

    cost_html = (
        cost_row("Grid import cost",   import_cost_p, "imp" if import_cost_p > 0 else "")
        + cost_row("Export revenue",  -export_rev_p,  "exp" if export_rev_p  > 0 else "")
        + f'<div class="crow divider"></div>'
        + cost_row("Net energy cost",  net_cost_p,    "imp" if net_cost_p > 0 else "exp")
        + f'<div class="crow"><span>Standing charge</span><span>61.64p/day</span></div>'
        + f'<div class="crow"><span>Avg import rate</span><span>{avg_rate_str}</span></div>'
        + f'<div class="crow"><span>Self-sufficiency</span><strong>{self_suff:.0f}%</strong></div>'
        + f'<div class="crow"><span>Carbon offset</span>'
          f'<span class="exp">{carbon_kg:.1f} kg CO&#8322;</span></div>'
        + f'<div class="crow"><span>Peak solar slot</span><span>{peak_str}</span></div>'
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
        <div class="bat-label">{soc_e:.0f}% charged</div>
        <div class="crow" style="margin-top:12px"><span>Manager actions</span></div>
        <div style="font-size:0.82em;color:#555;margin-top:4px;line-height:1.6">{action_summary}</div>"""

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


def generate_period_report(db_path, date_from, date_to, period_label,
                           output_dir, export_rate_p=12.0,
                           standing_p_per_day=61.64, log_fn=None):
    """Generate an HTML energy summary for any multi-day period.

    period_label: short string used in the page title (e.g. 'Weekly', 'Monthly')
    Breakdown table shows daily rows for <=62 days, monthly rows for longer periods.

    Returns (path, error_string).
    """
    import sqlite3
    from datetime import timedelta as _td

    def _log(msg, level="INFO"):
        if log_fn:
            log_fn(msg, level=level)

    days_in_range = (date_to - date_from).days + 1
    use_monthly   = days_in_range > 62

    # ---- query daily aggregates ----------------------------------------
    try:
        con = sqlite3.connect(db_path)
        raw = con.execute(
            """SELECT DATE(slot_start)                        AS day,
                      SUM(pv_kwh)                            AS pv,
                      SUM(home_kwh)                          AS home,
                      SUM(grid_import_kwh)                   AS imp,
                      SUM(grid_export_kwh)                   AS exp,
                      SUM(grid_import_kwh * tracker_price_p) AS imp_cost_p,
                      COUNT(*)                               AS slots
               FROM halfhourly
               WHERE slot_start >= ? AND slot_start < ?
               GROUP BY day
               ORDER BY day""",
            (f"{date_from.isoformat()}T00:00:00",
             f"{(date_to + _td(days=1)).isoformat()}T00:00:00"),
        ).fetchall()
        con.close()
    except Exception as exc:
        return None, str(exc)

    if not raw:
        return None, (f"No data between {date_from.strftime('%d/%m/%Y')} "
                      f"and {date_to.strftime('%d/%m/%Y')}")

    # ---- period totals --------------------------------------------------
    total_pv   = sum(r[1] or 0.0 for r in raw)
    total_home = sum(r[2] or 0.0 for r in raw)
    total_imp  = sum(r[3] or 0.0 for r in raw)
    total_exp  = sum(r[4] or 0.0 for r in raw)
    total_imp_cost_p = sum(r[5] or 0.0 for r in raw)
    total_exp_rev_p  = total_exp * export_rate_p
    net_cost_p       = total_imp_cost_p - total_exp_rev_p
    standing_p       = standing_p_per_day * days_in_range
    total_cost_p     = net_cost_p + standing_p

    days_with_data   = len(raw)
    self_suff        = max(0.0, (1.0 - total_imp / total_home) * 100.0) if total_home > 0 else 100.0
    avg_imp_rate     = total_imp_cost_p / total_imp if total_imp >= 0.01 else None
    carbon_kg        = total_pv * 0.225

    best_solar_r     = max(raw, key=lambda r: r[1] or 0.0)
    best_solar_day   = best_solar_r[0]
    best_solar_kwh   = best_solar_r[1] or 0.0

    from_uk      = date_from.strftime("%d/%m/%Y")
    to_uk        = date_to.strftime("%d/%m/%Y")
    generated_at = datetime.now().strftime("%d/%m/%Y %H:%M")
    title        = f"{period_label} Energy Report: {from_uk} – {to_uk}"

    # ---- breakdown rows -------------------------------------------------
    def kwh(v):
        return f"{v:.2f}" if (v or 0) >= 0.005 else "—"

    def net_str(cost_p):
        v = cost_p / 100.0
        if abs(v) < 0.005:
            return "—"
        return (f'<span class="exp">−£{abs(v):.2f}</span>'
                if v < 0 else f'<span class="imp">£{v:.2f}</span>')

    if use_monthly:
        # Aggregate by YYYY-MM
        from collections import defaultdict
        months = defaultdict(lambda: [0.0, 0.0, 0.0, 0.0, 0.0, 0])
        for r in raw:
            m = r[0][:7]
            months[m][0] += r[1] or 0.0
            months[m][1] += r[2] or 0.0
            months[m][2] += r[3] or 0.0
            months[m][3] += r[4] or 0.0
            months[m][4] += r[5] or 0.0
            months[m][5] += r[6] or 0

        breakdown_rows = []
        for m in sorted(months.keys()):
            pv, home, imp, exp, ic, slots = months[m]
            ss   = max(0.0, (1.0 - imp / home) * 100.0) if home > 0 else 100.0
            net  = ic - exp * export_rate_p
            try:
                mlabel = datetime.strptime(m, "%Y-%m").strftime("%B %Y")
            except ValueError:
                mlabel = m
            breakdown_rows.append(
                f"<tr><td>{mlabel}</td>"
                f'<td class="pv">{kwh(pv)}</td><td>{kwh(home)}</td>'
                f'<td class="imp">{kwh(imp)}</td><td class="exp">{kwh(exp)}</td>'
                f"<td>{ss:.0f}%</td><td>{net_str(net)}</td></tr>"
            )
        row_label = "Month"
    else:
        breakdown_rows = []
        for r in raw:
            pv, home, imp, exp, ic = r[1] or 0.0, r[2] or 0.0, r[3] or 0.0, r[4] or 0.0, r[5] or 0.0
            ss  = max(0.0, (1.0 - imp / home) * 100.0) if home > 0 else 100.0
            net = ic - exp * export_rate_p
            try:
                dlabel = date.fromisoformat(r[0]).strftime("%-d %b")
            except Exception:
                dlabel = r[0]
            breakdown_rows.append(
                f"<tr><td>{dlabel}</td>"
                f'<td class="pv">{kwh(pv)}</td><td>{kwh(home)}</td>'
                f'<td class="imp">{kwh(imp)}</td><td class="exp">{kwh(exp)}</td>'
                f"<td>{ss:.0f}%</td><td>{net_str(net)}</td></tr>"
            )
        row_label = "Date"

    breakdown_html = "\n".join(breakdown_rows)

    # totals footer row
    net_tot = net_cost_p
    footer_net = net_str(net_tot)
    breakdown_footer = (
        f"<tr><td><strong>Total</strong></td>"
        f'<td class="pv"><strong>{total_pv:.2f}</strong></td>'
        f"<td><strong>{total_home:.2f}</strong></td>"
        f'<td class="imp"><strong>{total_imp:.2f}</strong></td>'
        f'<td class="exp"><strong>{total_exp:.2f}</strong></td>'
        f"<td><strong>{self_suff:.0f}%</strong></td>"
        f"<td><strong>{footer_net}</strong></td></tr>"
    )

    # ---- coverage note --------------------------------------------------
    total_expected = days_in_range * 48
    total_slots    = sum(r[6] or 0 for r in raw)
    coverage_pct   = total_slots / total_expected * 100.0 if total_expected else 0
    coverage_note  = (
        f'<p class="warn">⚠ Data coverage: {total_slots} of {total_expected} expected slots '
        f'({coverage_pct:.0f}%, {days_with_data} of {days_in_range} days) — '
        f'totals may be incomplete.</p>'
        if coverage_pct < 95 else ""
    )

    # ---- cost & stats panels --------------------------------------------
    avg_rate_str  = f"{avg_imp_rate:.1f}p/kWh" if avg_imp_rate is not None else "—"
    best_day_str  = (f"{date.fromisoformat(best_solar_day).strftime('%-d %b')} "
                     f"({best_solar_kwh:.1f} kWh)" if best_solar_kwh >= 0.01 else "—")

    def crow(label, val, cls=""):
        s = f'<span class="{cls}">{val}</span>' if cls else f"<span>{val}</span>"
        return f'<div class="crow"><span>{label}</span>{s}</div>'

    cost_panel = (
        crow("Import cost (Tracker)", f"£{total_imp_cost_p/100:.2f}", "imp" if total_imp_cost_p > 0 else "")
        + crow("Export revenue (12p)", f"−£{total_exp_rev_p/100:.2f}", "exp" if total_exp_rev_p > 0 else "")
        + '<div class="crow divider"></div>'
        + crow("Net energy cost", f"{'−' if net_cost_p < 0 else ''}£{abs(net_cost_p)/100:.2f}",
               "exp" if net_cost_p < 0 else "imp")
        + crow("Standing charges", f"£{standing_p/100:.2f}")
        + '<div class="crow divider"></div>'
        + crow("Total inc. standing", f"£{total_cost_p/100:.2f}", "imp" if total_cost_p > 0 else "exp")
        + crow("Avg import rate", avg_rate_str)
    )

    stats_panel = (
        crow("Self-sufficiency",   f"{self_suff:.0f}%",     "exp" if self_suff >= 80 else "")
        + crow("Carbon offset",   f"{carbon_kg:.1f} kg CO&#8322;", "exp")
        + crow("Best solar day",  best_day_str)
        + crow("Days with data",  f"{days_with_data} of {days_in_range}")
        + crow("Avg solar/day",   f"{total_pv/days_in_range:.1f} kWh")
        + crow("Avg import/day",  f"{total_imp/days_in_range:.1f} kWh")
        + crow("Avg export/day",  f"{total_exp/days_in_range:.1f} kWh")
    )

    # ---- HTML -----------------------------------------------------------
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{title}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
         background: #f0f4f0; color: #333; padding: 24px; font-size: 15px; }}
  .container {{ max-width: 960px; margin: 0 auto; }}
  .header {{ background: #1b5e20; color: #fff; padding: 22px 28px; border-radius: 10px 10px 0 0; }}
  .header h1 {{ font-size: 1.35em; font-weight: 700; }}
  .header p  {{ opacity: 0.75; font-size: 0.85em; margin-top: 4px; }}
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
  .panels {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin: 10px 0; }}
  .panel {{ background: #fff; border-radius: 8px; padding: 18px 20px;
            box-shadow: 0 1px 4px rgba(0,0,0,.08); }}
  .panel h2 {{ font-size: 0.78em; font-weight: 600; color: #777; text-transform: uppercase;
               letter-spacing: 0.6px; border-bottom: 1px solid #eee;
               padding-bottom: 10px; margin-bottom: 12px; }}
  .crow {{ display: flex; justify-content: space-between; padding: 6px 0;
           border-bottom: 1px solid #f5f5f5; font-size: 0.92em; }}
  .crow:last-child {{ border-bottom: none; }}
  .crow.divider {{ border-bottom: 2px solid #e0e0e0; margin: 4px 0; padding: 0; }}
  .section {{ background: #fff; border-radius: 8px; padding: 18px 20px; margin: 10px 0;
              box-shadow: 0 1px 4px rgba(0,0,0,.08); overflow-x: auto; }}
  .section h2 {{ font-size: 0.78em; font-weight: 600; color: #777; text-transform: uppercase;
                 letter-spacing: 0.6px; border-bottom: 1px solid #eee;
                 padding-bottom: 10px; margin-bottom: 14px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.88em; }}
  thead th {{ background: #1b5e20; color: #fff; padding: 9px 10px;
              text-align: right; font-weight: 500; }}
  thead th:first-child {{ text-align: left; }}
  tbody tr:hover {{ background: #f7fff7; }}
  tbody tr:nth-child(even) {{ background: #fafafa; }}
  tbody td {{ padding: 7px 10px; text-align: right; border-bottom: 1px solid #f0f0f0; }}
  tbody td:first-child {{ text-align: left; }}
  tfoot td {{ padding: 9px 10px; text-align: right; font-weight: 600;
              border-top: 2px solid #1b5e20; background: #f0f7f0; }}
  tfoot td:first-child {{ text-align: left; }}
  .imp {{ color: #b71c1c; }} .exp {{ color: #1b5e20; }} .pv {{ color: #e65100; }}
  .warn {{ background: #fff8e1; border-left: 4px solid #f9a825; padding: 10px 14px;
           margin: 10px 0; border-radius: 4px; font-size: 0.88em; color: #555; }}
  .footer {{ text-align: center; color: #aaa; font-size: 0.78em; margin-top: 16px; }}
</style>
</head>
<body>
<div class="container">

  <div class="header">
    <h1>{title}</h1>
    <p>Generated {generated_at} &nbsp;&bull;&nbsp;
       {days_with_data} days of data &nbsp;&bull;&nbsp;
       Export tariff: Octopus Outgoing {export_rate_p:.0f}p</p>
  </div>

  {coverage_note}

  <div class="cards">
    <div class="card pv">
      <div class="card-value">{total_pv:.1f}</div>
      <div class="card-unit">kWh</div>
      <div class="card-label">Solar Generated</div>
    </div>
    <div class="card home">
      <div class="card-value">{total_home:.1f}</div>
      <div class="card-unit">kWh</div>
      <div class="card-label">Home Consumption</div>
    </div>
    <div class="card imp">
      <div class="card-value">{total_imp:.1f}</div>
      <div class="card-unit">kWh</div>
      <div class="card-label">Grid Import</div>
    </div>
    <div class="card exp">
      <div class="card-value">{total_exp:.1f}</div>
      <div class="card-unit">kWh</div>
      <div class="card-label">Grid Export</div>
    </div>
  </div>

  <div class="panels">
    <div class="panel">
      <h2>Costs &amp; Revenue</h2>
      {cost_panel}
    </div>
    <div class="panel">
      <h2>Period Stats</h2>
      {stats_panel}
    </div>
  </div>

  <div class="section">
    <h2>{'Monthly' if use_monthly else 'Daily'} Breakdown</h2>
    <table>
      <thead>
        <tr>
          <th>{row_label}</th>
          <th>Solar kWh</th><th>Home kWh</th>
          <th>Import kWh</th><th>Export kWh</th>
          <th>Self-Suff</th><th>Net Cost</th>
        </tr>
      </thead>
      <tbody>{breakdown_html}</tbody>
      <tfoot><tr>{breakdown_footer}</tr></tfoot>
    </table>
  </div>

  <div class="footer">Tariff Analyser &bull; Sigenergy Home Energy System &bull; {generated_at}</div>
</div>
</body>
</html>"""

    os.makedirs(output_dir, exist_ok=True)
    filename = f"period_energy_{date_from.isoformat()}_{date_to.isoformat()}.html"
    path     = os.path.join(output_dir, filename)
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(html)
    except Exception as exc:
        return None, str(exc)

    _log(f"[Period] Report written: {path}")
    return path, None


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
