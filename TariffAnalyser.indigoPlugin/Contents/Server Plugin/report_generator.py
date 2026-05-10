#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    report_generator.py
# Description: Generates HTML tariff comparison + savings reports and opens
#              them in the default browser.  CSV output was removed in v1.2.
# Author:      CliveS & Claude Sonnet 4.6
# Date:        10-05-2026
# Version:     1.2

import os
import subprocess
from datetime import date, datetime, timedelta
import tariff_engine


def generate_report(comparison, date_from, date_to, output_dir, export_tariff_name):
    """Write the tariff comparison as an HTML page (replaces v1.0 CSV output).

    The page ranks every UK tariff by total cost over the chosen period,
    highlights Tracker (the user's current default), and breaks down each
    tariff's import cost / export revenue / standing charge / coverage.

    Returns (path, error_string).  error_string is None on success.
    """
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename  = f"tariff_comparison_{date_from}_{date_to}_{timestamp}.html"
    path      = os.path.join(output_dir, filename)

    results   = comparison.get("results", [])
    monthly   = comparison.get("monthly", {})
    totals    = comparison.get("raw_totals", {})
    slots     = comparison.get("slots", 0)
    days      = comparison.get("days", 0)

    tracker_row = next((r for r in results if r["tariff_key"] == "tracker"), None)
    baseline    = tracker_row["total_cost_p"] if tracker_row else 0.0

    # Sort cheapest -> most expensive
    ranked = sorted(results, key=lambda r: r["total_cost_p"])

    def gbp(pence):
        return f"£{pence / 100.0:.2f}"

    from_uk      = date_from.strftime("%d %b %Y")
    to_uk        = date_to.strftime("%d %b %Y")
    generated_at = datetime.now().strftime("%d/%m/%Y %H:%M")
    slots_per_day = slots / days if days else 0

    # --- summary rows ---------------------------------------------------
    summary_rows = []
    for i, r in enumerate(ranked, 1):
        vs_tracker_p = r["total_cost_p"] - baseline
        if r["tariff_key"] == "tracker":
            vs = '<span class="vs current">current</span>'
        elif vs_tracker_p < 0:
            vs = f'<span class="vs cheaper">cheaper by {gbp(-vs_tracker_p)}</span>'
        elif vs_tracker_p > 0:
            vs = f'<span class="vs dearer">more by {gbp(vs_tracker_p)}</span>'
        else:
            vs = '<span class="vs">same</span>'
        rank_class = " rank-best" if i == 1 else (" rank-worst" if i == len(ranked) else "")
        marker = " ★" if i == 1 else (" ✘" if i == len(ranked) else "")
        summary_rows.append(f"""
        <tr class="rank-row{rank_class}">
          <td class="rank">{i}{marker}</td>
          <td class="name">{r['tariff_name']}</td>
          <td class="cost total">{gbp(r['total_cost_p'])}</td>
          <td class="cost">{gbp(r['import_cost_p'])}</td>
          <td class="cost">{gbp(r['export_revenue_p'])}</td>
          <td class="cost">{gbp(r['standing_charge_p'])}</td>
          <td class="vs-cell">{vs}</td>
          <td class="coverage">{r['coverage_pct']:.0f}%</td>
        </tr>""")

    # --- monthly breakdown ----------------------------------------------
    monthly_html = ""
    if monthly:
        tariff_keys  = [r["tariff_key"]  for r in results]
        tariff_names = [r["tariff_name"] for r in results]
        header_cells = "".join(f"<th>{n}</th>" for n in tariff_names)
        rows = []
        for month in sorted(monthly.keys()):
            try:
                m_label = datetime.strptime(month, "%Y-%m").strftime("%b %Y")
            except ValueError:
                m_label = month
            m_data = monthly[month]
            min_key = min(tariff_keys, key=lambda k: m_data.get(k, 0.0))
            cells = []
            for k in tariff_keys:
                v = m_data.get(k, 0.0) / 100.0
                cls = "best" if k == min_key else ""
                cells.append(f'<td class="{cls}">£{v:.2f}</td>')
            cheapest_name = tariff_names[tariff_keys.index(min_key)]
            rows.append(f'<tr><td class="month">{m_label}</td>' + "".join(cells) +
                        f'<td class="cheapest">{cheapest_name}</td></tr>')
        monthly_html = f"""
        <h2>Monthly net energy cost breakdown</h2>
        <p class="note">Energy cost only — standing charges excluded.  Cheapest tariff each month is highlighted.</p>
        <div class="table-scroll">
          <table class="monthly">
            <thead><tr><th>Month</th>{header_cells}<th>Cheapest</th></tr></thead>
            <tbody>{''.join(rows)}</tbody>
          </table>
        </div>"""

    # --- energy totals ---------------------------------------------------
    home_kwh = totals.get("home_kwh", 0) or 0
    self_suff_str = ""
    if home_kwh > 0:
        self_suff = (1.0 - totals.get("grid_import_kwh", 0) / home_kwh) * 100.0
        self_suff_str = f'<div class="totalrow"><span>Self-sufficiency</span><span>{self_suff:.1f}%</span></div>'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Tariff Comparison · {from_uk} - {to_uk}</title>
<style>
  body {{ font: 14px/1.4 -apple-system, BlinkMacSystemFont, "Helvetica Neue", sans-serif;
          margin: 0; padding: 20px 30px; color: #222; background: #f6f7f9; }}
  h1   {{ margin: 0 0 4px; font-size: 22px; }}
  h2   {{ margin: 28px 0 8px; font-size: 17px; color: #444; }}
  .meta {{ color: #666; font-size: 12px; margin-bottom: 18px; }}
  .totals {{ background: #fff; border-radius: 10px; padding: 16px 20px;
             box-shadow: 0 1px 3px rgba(0,0,0,.08); margin-bottom: 20px; }}
  .totalrow {{ display: flex; justify-content: space-between; padding: 4px 0;
               border-bottom: 1px solid #eee; }}
  .totalrow:last-child {{ border-bottom: 0; }}
  .totalrow span:last-child {{ font-weight: 600; font-variant-numeric: tabular-nums; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff;
           border-radius: 10px; overflow: hidden;
           box-shadow: 0 1px 3px rgba(0,0,0,.08); font-variant-numeric: tabular-nums; }}
  thead th {{ background: #eef1f5; font-weight: 600; color: #333;
              padding: 10px 8px; text-align: right; border-bottom: 2px solid #d8dde3; }}
  thead th:first-child, thead th:nth-child(2) {{ text-align: left; }}
  td {{ padding: 9px 8px; border-bottom: 1px solid #f0f1f4; text-align: right; }}
  td.rank, td.name, td.month {{ text-align: left; }}
  td.rank {{ font-weight: 700; color: #888; width: 50px; }}
  td.name {{ font-weight: 500; }}
  td.cost.total {{ font-weight: 700; }}
  td.coverage {{ color: #888; }}
  tr.rank-best td {{ background: #e8f5e9; }}
  tr.rank-best td.rank {{ color: #2e7d32; }}
  tr.rank-worst td {{ background: #fbe9e7; }}
  tr.rank-worst td.rank {{ color: #c0392b; }}
  .vs {{ font-size: 12px; padding: 2px 8px; border-radius: 12px; background: #eef0f3; }}
  .vs.cheaper {{ background: #c8e6c9; color: #1b5e20; }}
  .vs.dearer  {{ background: #ffccbc; color: #b71c1c; }}
  .vs.current {{ background: #1976d2; color: #fff; font-weight: 600; }}
  .table-scroll {{ overflow-x: auto; }}
  table.monthly th, table.monthly td {{ font-size: 12.5px; padding: 6px 8px; }}
  table.monthly td.best {{ background: #c8e6c9; font-weight: 600; }}
  table.monthly td.cheapest {{ font-style: italic; color: #555; }}
  .note {{ color: #666; font-size: 12px; margin: 4px 0 12px; }}
  ul.notes {{ font-size: 12px; color: #555; line-height: 1.6; padding-left: 20px; }}
</style>
</head>
<body>
  <h1>Tariff Comparison</h1>
  <div class="meta">
    {from_uk} - {to_uk} · {days} day{'s' if days != 1 else ''} · {slots} slots ({slots_per_day:.1f}/day)
    · Export tariff: {export_tariff_name} · Generated {generated_at}
  </div>

  <div class="totals">
    <div class="totalrow"><span>Grid import</span><span>{totals.get('grid_import_kwh', 0):.1f} kWh</span></div>
    <div class="totalrow"><span>Grid export</span><span>{totals.get('grid_export_kwh', 0):.1f} kWh</span></div>
    <div class="totalrow"><span>Solar generated</span><span>{totals.get('pv_kwh', 0):.1f} kWh</span></div>
    <div class="totalrow"><span>Home load</span><span>{home_kwh:.1f} kWh</span></div>
    {self_suff_str}
  </div>

  <h2>Tariff ranking</h2>
  <p class="note">★ cheapest, ✘ most expensive.  Cost = import - export + standing charges.  Compared against Tracker (your current).</p>
  <table>
    <thead>
      <tr>
        <th>#</th>
        <th>Tariff</th>
        <th>Total cost</th>
        <th>Import</th>
        <th>Export</th>
        <th>Standing</th>
        <th>vs Tracker</th>
        <th>Coverage</th>
      </tr>
    </thead>
    <tbody>{''.join(summary_rows)}</tbody>
  </table>

  {monthly_html}

  <h2>Notes</h2>
  <ul class="notes">
    <li>Comparison assumes identical energy consumption patterns across all tariffs.  Real savings on time-of-use tariffs (Go, Intelligent Go, Agile) may be higher because battery dispatch would be optimised for cheap windows.</li>
    <li>Agile coverage below 100% means price data was missing for some slots; those slots are excluded from the Agile cost.</li>
    <li>Standing charges use published rates and may differ from your actual contract.</li>
    <li>All costs include VAT at 5%.</li>
  </ul>
</body>
</html>"""

    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(html)
    except Exception as exc:
        return None, str(exc)
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


def generate_savings_summary(db_path, output_dir, export_rate_p=12.0, log_fn=None):
    """Generate a standalone HTML page showing solar savings for today, this
    week, this month, this year, and all time.

    Returns (path, error_string).
    """
    import calendar as _cal

    def _log(msg, level="INFO"):
        if log_fn:
            log_fn(msg, level=level)

    today       = date.today()
    yesterday   = today - timedelta(days=1)
    # Period boundaries — calendar-aligned, not rolling
    # Week: Monday of the current week through today
    week_start  = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    year_start  = today.replace(month=1, day=1)

    periods = [
        ("Today",       today,       today),
        ("Yesterday",   yesterday,   yesterday),
        ("This week",   week_start,  today),
        ("This month",  month_start, today),
        ("This year",   year_start,  today),
    ]

    sections = []
    for label, d_from, d_to in periods:
        s = tariff_engine.calculate_savings(db_path, export_rate_p, d_from, d_to)
        if s["slots"] == 0:
            sections.append((label, d_from, d_to, None))
        else:
            sections.append((label, d_from, d_to, s))

    generated_at = datetime.now().strftime("%d/%m/%Y %H:%M")

    def fmt_gbp(p):
        return f"£{p/100:.2f}"

    def savings_block(label, d_from, d_to, s):
        if s is None:
            return f"""
        <div class="period-card">
          <div class="period-header">{label}</div>
          <div class="period-dates">{d_from.strftime('%-d %b')} – {d_to.strftime('%-d %b %Y')}</div>
          <div class="no-data">No data available</div>
        </div>"""

        self_cons   = (s["pv_to_home_kwh"] / s["pv_kwh"] * 100) if s["pv_kwh"] >= 0.01 else 0.0
        days_span   = (d_to - d_from).days + 1
        actual_days = max(1.0, s["slots"] / 48.0)   # real days with data, not calendar span
        daily_avg   = s["total_savings_p"] / actual_days
        annual_proj = daily_avg * 365
        data_note   = (f"based on {actual_days:.0f} day{'s' if actual_days != 1 else ''} of data"
                       if actual_days < days_span else "")

        return f"""
        <div class="period-card">
          <div class="period-header">{label}</div>
          <div class="period-dates">{d_from.strftime('%-d %b')} – {d_to.strftime('%-d %b %Y')}</div>
          <div class="saving-total">{fmt_gbp(s['total_savings_p'])}</div>
          <div class="saving-label">total saved</div>
          <div class="breakdown">
            <div class="brow">
              <span>Solar generated</span>
              <span class="pv">{s['pv_kwh']:.1f} kWh</span>
            </div>
            <div class="brow">
              <span>Used at home</span>
              <span class="pv">{s['pv_to_home_kwh']:.1f} kWh ({self_cons:.0f}%)</span>
            </div>
            <div class="brow">
              <span>Exported</span>
              <span class="exp">{s['export_kwh']:.1f} kWh</span>
            </div>
            <div class="brow divider"></div>
            <div class="brow">
              <span>Avoided import</span>
              <span class="exp">{fmt_gbp(s['avoided_import_p'])}</span>
            </div>
            <div class="brow">
              <span>Export revenue</span>
              <span class="exp">{fmt_gbp(s['export_revenue_p'])}</span>
            </div>
            <div class="brow divider"></div>
            <div class="brow">
              <span>Would have paid</span>
              <span class="imp">{fmt_gbp(s['cost_without_solar_p'])}</span>
            </div>
            <div class="brow">
              <span>Actually paid</span>
              <span>{fmt_gbp(max(0, s['cost_with_solar_p']))}</span>
            </div>
            <div class="brow divider"></div>
            <div class="brow">
              <span>Daily average saving</span>
              <span class="exp">{fmt_gbp(daily_avg)}/day</span>
            </div>
            <div class="brow">
              <span>Projected annual{f' <span class="note">({data_note})</span>' if data_note else ''}</span>
              <span class="exp"><strong>{fmt_gbp(annual_proj)}/year</strong></span>
            </div>
          </div>
        </div>"""

    cards_html = "\n".join(savings_block(l, f, t, s) for l, f, t, s in sections)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Solar Savings Summary</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
         background: #f0f4f0; color: #333; padding: 24px; font-size: 15px; }}
  .container {{ max-width: 960px; margin: 0 auto; }}

  .header {{ background: #1b5e20; color: #fff; padding: 22px 28px;
             border-radius: 10px 10px 0 0; }}
  .header h1 {{ font-size: 1.45em; font-weight: 700; letter-spacing: -0.3px; }}
  .header p  {{ opacity: 0.75; font-size: 0.85em; margin-top: 4px; }}

  .subtitle {{ background: #fff; padding: 14px 20px; border-radius: 0;
               font-size: 0.88em; color: #666; border-bottom: 1px solid #e0e0e0; }}

  .grid {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px; margin-top: 14px; }}

  .period-card {{ background: #fff; border-radius: 10px;
                  box-shadow: 0 2px 6px rgba(0,0,0,.08); padding: 22px 24px; }}
  .period-header {{ font-size: 1.05em; font-weight: 700; color: #1b5e20;
                    text-transform: uppercase; letter-spacing: 0.5px; }}
  .period-dates  {{ font-size: 0.82em; color: #999; margin-top: 2px; margin-bottom: 14px; }}
  .saving-total  {{ font-size: 3em; font-weight: 800; color: #1b5e20; line-height: 1; }}
  .saving-label  {{ font-size: 0.8em; color: #888; text-transform: uppercase;
                    letter-spacing: 0.5px; margin-bottom: 16px; }}
  .no-data       {{ color: #bbb; font-style: italic; padding: 20px 0; }}

  .breakdown {{ margin-top: 14px; border-top: 1px solid #eee; padding-top: 12px; }}
  .brow      {{ display: flex; justify-content: space-between;
                padding: 5px 0; font-size: 0.9em; border-bottom: 1px solid #f5f5f5; }}
  .brow:last-child {{ border-bottom: none; }}
  .brow.divider {{ border-bottom: 2px solid #e0e0e0; margin: 4px 0; padding: 0; }}

  .imp  {{ color: #b71c1c; }}
  .exp  {{ color: #1b5e20; }}
  .pv   {{ color: #e65100; }}
  .note {{ color: #999; font-size: 0.82em; font-weight: 400; }}

  .footer {{ text-align: center; color: #aaa; font-size: 0.78em; margin-top: 20px; }}
</style>
</head>
<body>
<div class="container">

  <div class="header">
    <h1>Solar Savings Summary</h1>
    <p>Generated {generated_at} &nbsp;&bull;&nbsp; Export tariff: Octopus Outgoing {export_rate_p:.0f}p
       &nbsp;&bull;&nbsp; Savings calculated against actual Octopus Tracker rates</p>
  </div>

  <div class="subtitle">
    <strong>How this is calculated:</strong> &ldquo;Without solar&rdquo; assumes all home
    consumption would have been purchased from the grid at your actual Tracker rate.
    Savings = avoided import cost + export revenue.
  </div>

  <div class="grid">
    {cards_html}
  </div>

  <div class="footer">Tariff Analyser &bull; Sigenergy Home Energy System &bull; {generated_at}</div>

</div>
</body>
</html>"""

    os.makedirs(output_dir, exist_ok=True)
    filename = f"savings_summary_{today.isoformat()}.html"
    path     = os.path.join(output_dir, filename)
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(html)
    except Exception as exc:
        return None, str(exc)

    _log(f"[Savings] Summary written: {path}")
    return path, None


