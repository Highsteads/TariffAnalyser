#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    energy_dashboard.py
# Description: Interactive HTML energy dashboard with Chart.js.
#              Four tabs: Daily, Weekly, Monthly, Yearly.
#              Reads from daily_summary table; opens in browser.
# Author:      CliveS & Claude Sonnet 4.6
# Date:        06-05-2026
# Version:     1.0

import json
import os
import sqlite3
import subprocess
from datetime import datetime, date, timedelta
import calendar


# ---------------------------------------------------------------------------
# Public
# ---------------------------------------------------------------------------

def generate_dashboard(db_path, output_dir, log_fn=None):
    """Generate the full energy dashboard HTML file.

    Returns (path, error_string). error_string is None on success.
    """
    def _log(msg, level="INFO"):
        if log_fn:
            log_fn(f"[Dashboard] {msg}", level=level)

    if not os.path.exists(db_path):
        return None, "DB not found — run backfill first"

    try:
        data = _load_all_data(db_path)
    except Exception as exc:
        return None, f"DB read failed: {exc}"

    if not data:
        html = _build_empty_page()
    else:
        html = _build_html(data)

    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "energy_dashboard.html")
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(html)
    except Exception as exc:
        return None, str(exc)

    _log(f"Dashboard written: {path} ({len(data)} days of data)")
    return path, None


def open_in_browser(filepath, log_fn=None):
    """Open an HTML file in the default browser."""
    try:
        subprocess.Popen(["open", filepath])
        if log_fn:
            log_fn(f"[Dashboard] Opened in browser: {filepath}")
        return True
    except Exception as exc:
        if log_fn:
            log_fn(f"[Dashboard] Could not open browser: {exc}", level="WARNING")
        return False


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_all_data(db_path):
    """Return list of row dicts from daily_summary, ordered by date."""
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT * FROM daily_summary ORDER BY date"
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def _f(row, key, default=0.0):
    """Safe float from row dict."""
    v = row.get(key)
    return float(v) if v is not None else default


# ---------------------------------------------------------------------------
# Data aggregation helpers
# ---------------------------------------------------------------------------

def _weekly_rows(data):
    """Aggregate data into Mon-Sun weeks. Returns list of week dicts."""
    from collections import defaultdict
    weeks = defaultdict(list)
    for row in data:
        d = date.fromisoformat(row["date"])
        # Monday of this week
        monday = d - timedelta(days=d.weekday())
        weeks[monday.isoformat()].append(row)
    result = []
    for monday_str in sorted(weeks.keys()):
        result.append(_sum_rows(weeks[monday_str], monday_str))
    return result


def _monthly_rows(data):
    """Aggregate data into calendar months. Returns list of month dicts."""
    from collections import defaultdict
    months = defaultdict(list)
    for row in data:
        m = row["date"][:7]   # YYYY-MM
        months[m].append(row)
    result = []
    for m in sorted(months.keys()):
        result.append(_sum_rows(months[m], m))
    return result


def _yearly_rows(data):
    """Aggregate data into calendar years. Returns list of year dicts."""
    from collections import defaultdict
    years = defaultdict(list)
    for row in data:
        y = row["date"][:4]
        years[y].append(row)
    result = []
    for y in sorted(years.keys()):
        result.append(_sum_rows(years[y], y))
    return result


def _sum_rows(rows, label):
    """Sum a list of daily rows into a single aggregated dict."""
    def _s(key):
        vals = [_f(r, key) for r in rows if r.get(key) is not None]
        return round(sum(vals), 3) if vals else None

    def _avg(key):
        vals = [_f(r, key) for r in rows if r.get(key) is not None]
        return round(sum(vals) / len(vals), 4) if vals else None

    n = len(rows)
    return {
        "label":                    label,
        "days":                     n,
        "pv_kwh":                   _s("pv_kwh"),
        "home_kwh":                 _s("home_kwh"),
        "grid_import_kwh":          _s("grid_import_kwh"),
        "grid_export_kwh":          _s("grid_export_kwh"),
        # Prefer Octopus-metered export for displayed figures (accurate for billing)
        "best_export_kwh": round(sum(
            _f(r, "octopus_export_kwh") if r.get("octopus_export_kwh") is not None
            else _f(r, "grid_export_kwh")
            for r in rows
        ), 3),
        "battery_charge_kwh":       _s("battery_charge_kwh"),
        "battery_discharge_kwh":    _s("battery_discharge_kwh"),
        "octopus_import_kwh":       _s("octopus_import_kwh"),
        "octopus_export_kwh":       _s("octopus_export_kwh"),
        "elec_import_cost_gbp":     _s("elec_import_cost_gbp"),
        "elec_export_revenue_gbp":  _s("elec_export_revenue_gbp"),
        "elec_net_cost_gbp":        _s("elec_net_cost_gbp"),
        "elec_standing_charge_gbp": round(n * 0.6152, 4),
        "elec_total_gbp":           _s("elec_total_gbp"),
        "cost_without_solar_gbp":   _s("cost_without_solar_gbp"),
        "savings_vs_no_solar_gbp":  _s("savings_vs_no_solar_gbp"),
        "go_import_cost_gbp":       _s("go_import_cost_gbp"),
        "go_net_cost_gbp":          _s("go_net_cost_gbp"),
        "go_saving_vs_tracker_gbp": _s("go_saving_vs_tracker_gbp"),
        "flux_import_cost_gbp":     _s("flux_import_cost_gbp"),
        "flux_net_cost_gbp":        _s("flux_net_cost_gbp"),
        "flux_saving_vs_tracker_gbp": _s("flux_saving_vs_tracker_gbp"),
        "gas_kwh":                  _s("gas_kwh"),
        "gas_cost_gbp":             _s("gas_cost_gbp"),
        "gas_standing_charge_gbp":  round(n * 0.2906, 4),
        "gas_total_gbp":            _s("gas_total_gbp"),
        "tracker_avg_rate_p":       _avg("tracker_avg_rate_p"),
    }


# ---------------------------------------------------------------------------
# HTML builder
# ---------------------------------------------------------------------------

def _build_empty_page():
    """Return a simple HTML page shown when daily_summary has no rows yet."""
    from datetime import datetime as _dt
    generated = _dt.now().strftime("%d %b %Y %H:%M")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Energy Dashboard — No Data Yet</title>
<style>
  body {{font-family:Arial,sans-serif;background:#1a1a2e;color:#e0e0e0;
        display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}}
  .box {{background:#16213e;border-radius:12px;padding:48px 56px;max-width:560px;text-align:center;
         box-shadow:0 4px 24px rgba(0,0,0,.4)}}
  h1 {{color:#f0a500;margin-bottom:12px}}
  p  {{line-height:1.7;color:#b0b8cc}}
  code {{background:#0f3460;padding:2px 8px;border-radius:4px;font-size:.9em;color:#64b5f6}}
  .footer {{margin-top:32px;font-size:.8em;color:#555}}
</style>
</head>
<body>
<div class="box">
  <h1>Energy Dashboard</h1>
  <p>The <code>daily_summary</code> table exists but contains no data yet.</p>
  <p><strong>To populate it, run one of these:</strong></p>
  <p>
    &bull; <strong>Backfill script</strong> — run <code>backfill_energy_history.py</code>
    from an Indigo action to import historical data from 1 Jan 2026.<br><br>
    &bull; <strong>On-demand update</strong> — use
    <em>Plugins &rsaquo; Tariff Analyser &rsaquo; Update Daily Summary Now</em>
    to fetch the last 7 days from Octopus.<br><br>
    &bull; <strong>Auto-update</strong> — the plugin refreshes automatically every night at 02:00.
  </p>
  <div class="footer">Generated {generated}</div>
</div>
</body>
</html>"""


def _build_html(data):
    today       = date.today()
    generated   = datetime.now().strftime("%d/%m/%Y %H:%M")
    first_date  = data[0]["date"]
    last_date   = data[-1]["date"]

    weekly  = _weekly_rows(data)
    monthly = _monthly_rows(data)
    yearly  = _yearly_rows(data)

    # JSON for Chart.js (daily — last 90 days for readability)
    daily_recent = data[-90:] if len(data) > 90 else data

    def _labels(rows, key):
        return json.dumps([r[key] for r in rows])

    def _series(rows, key):
        return json.dumps([round(_f(r, key), 2) for r in rows])

    def _series_n(rows, key):
        return json.dumps([round(_f(r, key), 2) if r.get(key) is not None else None for r in rows])

    # Weekly labels: "Mon DD MMM"
    def _week_labels(weeks):
        labels = []
        for w in weeks:
            try:
                d = date.fromisoformat(w["label"])
                labels.append(d.strftime("%-d %b"))
            except Exception:
                labels.append(w["label"])
        return json.dumps(labels)

    def _month_labels(months):
        labels = []
        for m in months:
            try:
                d = datetime.strptime(m["label"], "%Y-%m")
                labels.append(d.strftime("%b %Y"))
            except Exception:
                labels.append(m["label"])
        return json.dumps(labels)

    # Totals card helper
    all_time = _sum_rows(data, "all_time")

    def _card(cls, label, value, unit="kWh"):
        return f"""<div class="card {cls}">
          <div class="cv">{value}</div>
          <div class="cu">{unit}</div>
          <div class="cl">{label}</div>
        </div>"""

    def _gbp(v, default="—"):
        if v is None:
            return default
        return f"£{v:.2f}"

    def _kwh(v, default="—"):
        if v is None:
            return default
        return f"{v:.1f}"

    def _p(v, default="—"):
        if v is None:
            return default
        return f"{v:.1f}%"

    def _self_suff(row):
        imp  = _f(row, "octopus_import_kwh") or _f(row, "grid_import_kwh")
        home = _f(row, "home_kwh")
        if home <= 0:
            return "—"
        return f"{max(0.0, (1.0 - imp / home) * 100):.0f}%"

    # Build period summary rows for the tables
    def _period_table_rows(rows, label_fmt):
        html_rows = []
        for r in rows:
            label = r["label"]
            if label_fmt == "week":
                try:
                    d = date.fromisoformat(label)
                    label = f"{d.strftime('%-d %b')} – {(d + timedelta(days=6)).strftime('%-d %b %Y')}"
                except Exception:
                    pass
            elif label_fmt == "month":
                try:
                    label = datetime.strptime(label, "%Y-%m").strftime("%B %Y")
                except Exception:
                    pass

            sav   = _f(r, "savings_vs_no_solar_gbp")
            go_s  = _f(r, "go_saving_vs_tracker_gbp")
            flux_s = _f(r, "flux_saving_vs_tracker_gbp")

            def _saving_cell(v):
                if v is None:
                    return '<td class="dim">—</td>'
                cls = "exp" if v > 0.005 else ("imp" if v < -0.005 else "dim")
                sign = "+" if v > 0 else ""
                return f'<td class="{cls}">{sign}£{v:.2f}</td>'

            html_rows.append(f"""<tr>
              <td>{label}</td>
              <td class="pv">{_kwh(r.get('pv_kwh'))}</td>
              <td>{_kwh(r.get('home_kwh'))}</td>
              <td class="imp">{_kwh(r.get('octopus_import_kwh') or r.get('grid_import_kwh'))}</td>
              <td class="exp">{_kwh(r.get('grid_export_kwh'))}</td>
              <td>{_self_suff(r)}</td>
              <td>{_gbp(r.get('elec_total_gbp'))}</td>
              <td>{_gbp(r.get('gas_total_gbp'))}</td>
              {_saving_cell(sav)}
              {_saving_cell(go_s)}
              {_saving_cell(flux_s)}
            </tr>""")
        return "\n".join(html_rows)

    weekly_rows_html  = _period_table_rows(weekly,  "week")
    monthly_rows_html = _period_table_rows(monthly, "month")
    yearly_rows_html  = _period_table_rows(yearly,  "year")

    # All-time summary stat cards
    total_pv      = _f(all_time, "pv_kwh")
    total_exp     = _f(all_time, "best_export_kwh")
    total_exp_rev = _f(all_time, "elec_export_revenue_gbp")
    total_saving  = _f(all_time, "savings_vs_no_solar_gbp")
    total_gas     = _f(all_time, "gas_kwh")

    # Savings breakdown components
    self_consumed_kwh      = round(total_pv - total_exp, 1)
    avoided_import_gbp     = round(total_saving - total_exp_rev, 2)
    cost_without_solar_gbp = _f(all_time, "cost_without_solar_gbp")
    elec_import_cost_gbp   = _f(all_time, "elec_import_cost_gbp")
    elec_standing_gbp      = _f(all_time, "elec_standing_charge_gbp")
    gas_unit_cost_gbp      = _f(all_time, "gas_cost_gbp")
    gas_standing_gbp       = _f(all_time, "gas_standing_charge_gbp")

    all_time_cards = (
        _card("pv",   "Solar Generated",     f"{total_pv:.1f}")
        + _card("exp", "Exported",            f"{total_exp:.1f}")
        + _card("rev", "Export Revenue",      f"£{total_exp_rev:.2f}", "")
        + _card("sav", "Saved vs No Solar",   f"£{total_saving:.2f}", "")
    )

    # Tariff comparison table for all-time
    tracker_cost = _f(all_time, "elec_net_cost_gbp")
    go_cost      = _f(all_time, "go_net_cost_gbp")
    flux_cost    = _f(all_time, "flux_net_cost_gbp")

    def _tariff_row(name, cost, saving, actual=False):
        badge = ' <span class="actual-badge">actual</span>' if actual else ""
        if saving is None or actual:
            diff = ""
        elif saving > 0.01:
            diff = f'<span class="exp">saves £{saving:.2f}</span>'
        elif saving < -0.01:
            diff = f'<span class="imp">costs £{abs(saving):.2f} more</span>'
        else:
            diff = '<span class="dim">same</span>'
        return f"<tr><td>{name}{badge}</td><td>£{cost:.2f}</td><td>{diff}</td></tr>"

    tariff_rows = (
        _tariff_row("Octopus Tracker", tracker_cost, None, actual=True)
        + _tariff_row("Octopus Go",    go_cost,  tracker_cost - go_cost    if go_cost   else None)
        + _tariff_row("Octopus Flux",  flux_cost, tracker_cost - flux_cost if flux_cost else None)
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Energy Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
       background: #f0f4f0; color: #333; font-size: 14px; }}
.header {{ background: #1b5e20; color: #fff; padding: 18px 24px;
           display: flex; justify-content: space-between; align-items: center; }}
.header h1 {{ font-size: 1.3em; font-weight: 700; }}
.header p  {{ font-size: 0.8em; opacity: 0.75; }}
.tabs  {{ background: #2e7d32; display: flex; }}
.tab   {{ padding: 12px 22px; color: rgba(255,255,255,0.7); cursor: pointer;
          font-size: 0.88em; font-weight: 600; letter-spacing: 0.3px;
          border-bottom: 3px solid transparent; transition: all 0.15s; }}
.tab:hover {{ color: #fff; }}
.tab.active {{ color: #fff; border-bottom-color: #a5d6a7; }}
.tab-content {{ display: none; padding: 16px 20px; max-width: 1200px; margin: 0 auto; }}
.tab-content.active {{ display: block; }}

.cards {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 14px; }}
.card  {{ background: #fff; border-radius: 8px; padding: 16px 12px; text-align: center;
          box-shadow: 0 1px 4px rgba(0,0,0,.08); }}
.cv    {{ font-size: 1.9em; font-weight: 800; line-height: 1; }}
.cu    {{ font-size: 0.75em; color: #888; margin-top: 2px; }}
.cl    {{ font-size: 0.74em; color: #666; margin-top: 5px; text-transform: uppercase; letter-spacing: 0.4px; }}
.card.pv   .cv {{ color: #e65100; }}
.card.exp  .cv {{ color: #1b5e20; }}
.card.rev  .cv {{ color: #2e7d32; }}
.card.sav  .cv {{ color: #1565c0; }}
.card.imp  .cv {{ color: #b71c1c; }}
.card.gas  .cv {{ color: #6a1b9a; }}

.row2 {{ display: grid; grid-template-columns: 2fr 1fr; gap: 12px; margin-bottom: 14px; }}
.panel {{ background: #fff; border-radius: 8px; padding: 18px 20px;
          box-shadow: 0 1px 4px rgba(0,0,0,.08); }}
.panel h2 {{ font-size: 0.74em; font-weight: 700; color: #777; text-transform: uppercase;
             letter-spacing: 0.6px; border-bottom: 1px solid #eee;
             padding-bottom: 8px; margin-bottom: 12px; }}
.crow {{ display: flex; justify-content: space-between; padding: 5px 0;
         border-bottom: 1px solid #f5f5f5; font-size: 0.88em; }}
.crow:last-child {{ border-bottom: none; }}
.crow.div {{ border-bottom: 2px solid #e0e0e0; margin: 4px 0; padding: 0; height: 0; }}

.section {{ background: #fff; border-radius: 8px; padding: 18px 20px; margin-bottom: 14px;
            box-shadow: 0 1px 4px rgba(0,0,0,.08); overflow-x: auto; }}
.section h2 {{ font-size: 0.74em; font-weight: 700; color: #777; text-transform: uppercase;
               letter-spacing: 0.6px; border-bottom: 1px solid #eee;
               padding-bottom: 8px; margin-bottom: 14px; }}

table {{ width: 100%; border-collapse: collapse; font-size: 0.85em; }}
thead th {{ background: #1b5e20; color: #fff; padding: 8px 10px; text-align: right;
            font-weight: 500; white-space: nowrap; }}
thead th:first-child {{ text-align: left; }}
tbody tr:hover {{ background: #f7fff7; }}
tbody tr:nth-child(even) {{ background: #fafafa; }}
tbody td {{ padding: 6px 10px; text-align: right; border-bottom: 1px solid #f0f0f0; }}
tbody td:first-child {{ text-align: left; }}
tfoot td {{ padding: 8px 10px; text-align: right; font-weight: 700;
            border-top: 2px solid #1b5e20; background: #f0f7f0; }}
tfoot td:first-child {{ text-align: left; }}

.chart-wrap {{ position: relative; height: 260px; }}

.pv   {{ color: #e65100; }}
.imp  {{ color: #b71c1c; }}
.exp  {{ color: #1b5e20; }}
.rev  {{ color: #2e7d32; }}
.sav  {{ color: #1565c0; }}
.gas  {{ color: #6a1b9a; }}
.dim  {{ color: #bbb; }}

.actual-badge {{ display: inline-block; margin-left: 6px; padding: 1px 5px;
                 border-radius: 3px; font-size: 0.72em; background: #e8f5e9;
                 color: #2e7d32; vertical-align: middle; }}
.note {{ background: #fff8e1; border-left: 4px solid #f9a825; padding: 10px 14px;
         margin-bottom: 12px; border-radius: 4px; font-size: 0.83em; color: #555; }}
.footer {{ text-align: center; color: #aaa; font-size: 0.75em; padding: 16px; }}
</style>
</head>
<body>

<div class="header">
  <div>
    <h1>Energy Dashboard &mdash; Highsteads</h1>
    <p>Sigenergy 14.25 kWp solar &bull; 35 kWh battery &bull; Octopus Tracker + Outgoing 12p</p>
  </div>
  <div style="text-align:right">
    <p style="font-size:0.85em">{first_date} to {last_date}</p>
    <p>Generated {generated}</p>
  </div>
</div>

<div class="tabs">
  <div class="tab active" onclick="showTab('overview')">Overview</div>
  <div class="tab" onclick="showTab('daily')">Daily</div>
  <div class="tab" onclick="showTab('weekly')">Weekly</div>
  <div class="tab" onclick="showTab('monthly')">Monthly</div>
  <div class="tab" onclick="showTab('yearly')">Yearly</div>
</div>

<!-- ====================================================================== OVERVIEW -->
<div id="tab-overview" class="tab-content active">
  <div style="height:12px"></div>

  <div class="cards">
    {all_time_cards}
  </div>

  <div class="row2" style="grid-template-columns: 3fr 2fr">
    <div class="panel">
      <h2>Tariff Comparison &mdash; All Time (energy cost net of export, excl. standing charges)</h2>
      <table>
        <thead><tr><th>Tariff</th><th>Net Import Cost</th><th>Saving vs Tracker</th></tr></thead>
        <tbody>{tariff_rows}</tbody>
      </table>
      <p style="font-size:0.75em;color:#999;margin-top:10px">
        Go and Flux costs calculated from actual half-hourly Octopus metered consumption.
        Same 12p export rate applied throughout.
      </p>
    </div>
    <div class="panel">
      <h2>All Time Totals</h2>
      <div class="crow"><span>Days with data</span><span>{len(data)}</span></div>

      <div class="crow" style="font-size:0.72em;color:#999;text-transform:uppercase;letter-spacing:0.5px;margin-top:6px;border-bottom:none"><span>Solar</span></div>
      <div class="crow"><span>Generated</span><span class="pv">{_kwh(all_time.get('pv_kwh'))} kWh</span></div>
      <div class="crow"><span style="padding-left:10px">Self-consumed</span><span class="exp">{_kwh(self_consumed_kwh)} kWh</span></div>
      <div class="crow"><span style="padding-left:10px">Exported to grid</span><span class="exp">{_kwh(all_time.get('best_export_kwh'))} kWh</span></div>
      <div class="crow"><span style="padding-left:10px">Export revenue</span><span class="exp">{_gbp(all_time.get('elec_export_revenue_gbp'))}</span></div>

      <div class="crow div"></div>
      <div class="crow" style="font-size:0.72em;color:#999;text-transform:uppercase;letter-spacing:0.5px;border-bottom:none"><span>Electricity</span></div>
      <div class="crow"><span>Grid import</span><span class="imp">{_kwh(all_time.get('octopus_import_kwh') or all_time.get('grid_import_kwh'))} kWh</span></div>
      <div class="crow"><span style="padding-left:10px">Unit cost</span><span class="imp">{_gbp(elec_import_cost_gbp)}</span></div>
      <div class="crow"><span style="padding-left:10px">Standing charges</span><span class="dim">{_gbp(elec_standing_gbp)}</span></div>
      <div class="crow"><span><strong>Electricity total</strong></span><strong class="imp">{_gbp(all_time.get('elec_total_gbp'))}</strong></div>

      <div class="crow div"></div>
      <div class="crow" style="font-size:0.72em;color:#999;text-transform:uppercase;letter-spacing:0.5px;border-bottom:none"><span>Gas</span></div>
      <div class="crow"><span>Consumed</span><span class="gas">{_kwh(all_time.get('gas_kwh'))} kWh</span></div>
      <div class="crow"><span style="padding-left:10px">Unit cost</span><span class="gas">{_gbp(gas_unit_cost_gbp)}</span></div>
      <div class="crow"><span style="padding-left:10px">Standing charges</span><span class="dim">{_gbp(gas_standing_gbp)}</span></div>
      <div class="crow"><span><strong>Gas total</strong></span><strong class="gas">{_gbp(all_time.get('gas_total_gbp'))}</strong></div>

      <div class="crow div"></div>
      <div class="crow" style="font-size:0.72em;color:#999;text-transform:uppercase;letter-spacing:0.5px;border-bottom:none"><span>Savings vs No Solar (electricity only)</span></div>
      <div class="crow"><span style="padding-left:10px">Without solar, import cost</span><span class="dim">{_gbp(cost_without_solar_gbp)}</span></div>
      <div class="crow"><span style="padding-left:10px">Actual import cost</span><span class="dim">{_gbp(elec_import_cost_gbp)}</span></div>
      <div class="crow"><span style="padding-left:10px">Avoided import</span><span class="sav">{_gbp(avoided_import_gbp)}</span></div>
      <div class="crow"><span style="padding-left:10px">+ Export revenue</span><span class="sav">{_gbp(all_time.get('elec_export_revenue_gbp'))}</span></div>
      <div class="crow" style="border-top:1px solid #e0e0e0;margin-top:2px;padding-top:4px">
        <span><strong>= Total saved</strong></span>
        <strong class="sav">{_gbp(all_time.get('savings_vs_no_solar_gbp'))}</strong></div>
    </div>
  </div>

  <div class="section">
    <h2>Solar Generation &amp; Export &mdash; Monthly (kWh)</h2>
    <div class="chart-wrap">
      <canvas id="overviewChart"></canvas>
    </div>
  </div>
</div>

<!-- ====================================================================== DAILY -->
<div id="tab-daily" class="tab-content">
  <div style="height:12px"></div>
  <div class="note">Showing last 90 days. Solar, home load, import, export in kWh per day.</div>

  <div class="section">
    <h2>Daily Solar &amp; Grid (last 90 days)</h2>
    <div class="chart-wrap"><canvas id="dailySolarChart"></canvas></div>
  </div>

  <div class="section">
    <h2>Daily Costs &amp; Savings (last 90 days)</h2>
    <div class="chart-wrap"><canvas id="dailyCostChart"></canvas></div>
  </div>

  <div class="section">
    <h2>Daily Gas &amp; Electricity (last 90 days, kWh)</h2>
    <div class="chart-wrap"><canvas id="dailyGasChart"></canvas></div>
  </div>
</div>

<!-- ====================================================================== WEEKLY -->
<div id="tab-weekly" class="tab-content">
  <div style="height:12px"></div>
  <div class="section">
    <h2>Weekly Energy (Mon-Sun weeks)</h2>
    <div class="chart-wrap"><canvas id="weeklyChart"></canvas></div>
  </div>
  <div class="section">
    <h2>Weekly Summary Table</h2>
    <table>
      <thead>
        <tr>
          <th>Week</th><th>Solar kWh</th><th>Home kWh</th><th>Import kWh</th>
          <th>Export kWh</th><th>Self-Suff</th><th>Elec Total</th><th>Gas Total</th>
          <th>Saved vs<br>No Solar</th><th>Go vs<br>Tracker</th><th>Flux vs<br>Tracker</th>
        </tr>
      </thead>
      <tbody>{weekly_rows_html}</tbody>
    </table>
  </div>
</div>

<!-- ====================================================================== MONTHLY -->
<div id="tab-monthly" class="tab-content">
  <div style="height:12px"></div>
  <div class="section">
    <h2>Monthly Energy</h2>
    <div class="chart-wrap"><canvas id="monthlyChart"></canvas></div>
  </div>
  <div class="section">
    <h2>Monthly Costs &amp; Savings</h2>
    <div class="chart-wrap"><canvas id="monthlyCostChart"></canvas></div>
  </div>
  <div class="section">
    <h2>Monthly Summary Table</h2>
    <table>
      <thead>
        <tr>
          <th>Month</th><th>Solar kWh</th><th>Home kWh</th><th>Import kWh</th>
          <th>Export kWh</th><th>Self-Suff</th><th>Elec Total</th><th>Gas Total</th>
          <th>Saved vs<br>No Solar</th><th>Go vs<br>Tracker</th><th>Flux vs<br>Tracker</th>
        </tr>
      </thead>
      <tbody>{monthly_rows_html}</tbody>
      <tfoot>
        <tr>
          <td>Total</td>
          <td class="pv">{_kwh(all_time.get('pv_kwh'))}</td>
          <td>{_kwh(all_time.get('home_kwh'))}</td>
          <td class="imp">{_kwh(all_time.get('octopus_import_kwh') or all_time.get('grid_import_kwh'))}</td>
          <td class="exp">{_kwh(all_time.get('best_export_kwh'))}</td>
          <td>—</td>
          <td>{_gbp(all_time.get('elec_total_gbp'))}</td>
          <td>{_gbp(all_time.get('gas_total_gbp'))}</td>
          <td class="sav">{_gbp(all_time.get('savings_vs_no_solar_gbp'))}</td>
          <td>{_gbp(all_time.get('go_saving_vs_tracker_gbp'))}</td>
          <td>{_gbp(all_time.get('flux_saving_vs_tracker_gbp'))}</td>
        </tr>
      </tfoot>
    </table>
  </div>
</div>

<!-- ====================================================================== YEARLY -->
<div id="tab-yearly" class="tab-content">
  <div style="height:12px"></div>
  <div class="section">
    <h2>Yearly Summary</h2>
    <div class="chart-wrap"><canvas id="yearlyChart"></canvas></div>
  </div>
  <div class="section">
    <h2>Yearly Table</h2>
    <table>
      <thead>
        <tr>
          <th>Year</th><th>Solar kWh</th><th>Home kWh</th><th>Import kWh</th>
          <th>Export kWh</th><th>Self-Suff</th><th>Elec Total</th><th>Gas Total</th>
          <th>Saved vs<br>No Solar</th><th>Go vs<br>Tracker</th><th>Flux vs<br>Tracker</th>
        </tr>
      </thead>
      <tbody>{yearly_rows_html}</tbody>
    </table>
  </div>
</div>

<div class="footer">
  Tariff Analyser &bull; Sigenergy Home Energy System &bull; Generated {generated}
  <br>Go/Flux comparisons apply current published rates to actual Octopus-metered consumption.
  Standing charges: Electricity {0.6152:.2f}p/day &bull; Gas {0.2906:.2f}p/day
</div>

<script>
// ---------------------------------------------------------------------------
// Tab switcher
// ---------------------------------------------------------------------------
function showTab(name) {{
  document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(el => el.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  event.target.classList.add('active');
}}

// ---------------------------------------------------------------------------
// Chart defaults
// ---------------------------------------------------------------------------
Chart.defaults.font.family = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif";
Chart.defaults.font.size   = 11;
Chart.defaults.color       = '#666';

const opts = {{
  responsive: true,
  maintainAspectRatio: false,
  plugins: {{
    legend: {{ position: 'top', labels: {{ boxWidth: 12, padding: 12 }} }},
    tooltip: {{ mode: 'index', intersect: false }},
  }},
  scales: {{
    x: {{ grid: {{ display: false }} }},
    y: {{ beginAtZero: true, grid: {{ color: '#f0f0f0' }} }},
  }},
}};

function barChart(id, labels, datasets) {{
  return new Chart(document.getElementById(id), {{
    type: 'bar',
    data: {{ labels, datasets }},
    options: {{ ...opts, scales: {{ ...opts.scales,
      x: {{ ...opts.scales.x, stacked: false }} }} }},
  }});
}}

function lineChart(id, labels, datasets) {{
  return new Chart(document.getElementById(id), {{
    type: 'line',
    data: {{ labels, datasets }},
    options: {{ ...opts }},
  }});
}}

// ---------------------------------------------------------------------------
// Data
// ---------------------------------------------------------------------------
const dailyLabels   = {_labels(daily_recent, "date")};
const dailyPV       = {_series(daily_recent, "pv_kwh")};
const dailyHome     = {_series(daily_recent, "home_kwh")};
const dailyImp      = {_series_n(daily_recent, "octopus_import_kwh")};
const dailyExp      = {_series(daily_recent, "best_export_kwh")};
const dailyCost     = {_series_n(daily_recent, "elec_total_gbp")};
const dailySavings  = {_series_n(daily_recent, "savings_vs_no_solar_gbp")};
const dailyGasKwh   = {_series_n(daily_recent, "gas_kwh")};
const dailyElecKwh  = {_series_n(daily_recent, "octopus_import_kwh")};

const weekLabels    = {_week_labels(weekly)};
const weekPV        = {_series(weekly, "pv_kwh")};
const weekExp       = {_series(weekly, "best_export_kwh")};
const weekImp       = {_series_n(weekly, "octopus_import_kwh")};
const weekCost      = {_series_n(weekly, "elec_total_gbp")};

const monthLabels   = {_month_labels(monthly)};
const monthPV       = {_series(monthly, "pv_kwh")};
const monthExp      = {_series(monthly, "best_export_kwh")};
const monthImp      = {_series_n(monthly, "octopus_import_kwh")};
const monthCost     = {_series_n(monthly, "elec_total_gbp")};
const monthGasCost  = {_series_n(monthly, "gas_total_gbp")};
const monthSavings  = {_series_n(monthly, "savings_vs_no_solar_gbp")};

const yearLabels    = {_labels(yearly, "label")};
const yearPV        = {_series(yearly, "pv_kwh")};
const yearImp       = {_series_n(yearly, "octopus_import_kwh")};
const yearGasKwh    = {_series_n(yearly, "gas_kwh")};
const yearElecCost  = {_series_n(yearly, "elec_total_gbp")};
const yearGasCost   = {_series_n(yearly, "gas_total_gbp")};
const yearSavings   = {_series_n(yearly, "savings_vs_no_solar_gbp")};

// ---------------------------------------------------------------------------
// Charts
// ---------------------------------------------------------------------------

// Overview: monthly solar + export
barChart('overviewChart', {_month_labels(monthly)}, [
  {{ label: 'Solar Generated (kWh)', data: {_series(monthly, "pv_kwh")},
     backgroundColor: 'rgba(230,81,0,0.7)' }},
  {{ label: 'Exported (kWh)',        data: {_series(monthly, "best_export_kwh")},
     backgroundColor: 'rgba(27,94,32,0.7)' }},
  {{ label: 'Import (kWh)',          data: {_series_n(monthly, "octopus_import_kwh")},
     backgroundColor: 'rgba(183,28,28,0.6)' }},
]);

// Daily: solar stacked bar
barChart('dailySolarChart', dailyLabels, [
  {{ label: 'Solar (kWh)', data: dailyPV,
     backgroundColor: 'rgba(230,81,0,0.7)' }},
  {{ label: 'Export (kWh)', data: dailyExp,
     backgroundColor: 'rgba(27,94,32,0.7)' }},
  {{ label: 'Import (kWh)', data: dailyImp,
     backgroundColor: 'rgba(183,28,28,0.5)' }},
]);

// Daily: cost + savings line
lineChart('dailyCostChart', dailyLabels, [
  {{ label: 'Elec Total (£)',      data: dailyCost,
     borderColor: '#b71c1c', backgroundColor: 'rgba(183,28,28,0.1)',
     tension: 0.3, fill: false }},
  {{ label: 'Saved vs No Solar (£)', data: dailySavings,
     borderColor: '#1565c0', backgroundColor: 'rgba(21,101,192,0.1)',
     tension: 0.3, fill: false }},
]);

// Daily: gas vs electricity kWh
barChart('dailyGasChart', dailyLabels, [
  {{ label: 'Electricity Import (kWh)', data: dailyElecKwh,
     backgroundColor: 'rgba(183,28,28,0.6)' }},
  {{ label: 'Gas (kWh)',                data: dailyGasKwh,
     backgroundColor: 'rgba(106,27,154,0.6)' }},
]);

// Weekly
barChart('weeklyChart', weekLabels, [
  {{ label: 'Solar (kWh)', data: weekPV,
     backgroundColor: 'rgba(230,81,0,0.7)' }},
  {{ label: 'Export (kWh)', data: weekExp,
     backgroundColor: 'rgba(27,94,32,0.7)' }},
  {{ label: 'Import (kWh)', data: weekImp,
     backgroundColor: 'rgba(183,28,28,0.5)' }},
]);

// Monthly energy
barChart('monthlyChart', monthLabels, [
  {{ label: 'Solar (kWh)', data: monthPV,
     backgroundColor: 'rgba(230,81,0,0.7)' }},
  {{ label: 'Export (kWh)', data: monthExp,
     backgroundColor: 'rgba(27,94,32,0.7)' }},
  {{ label: 'Import (kWh)', data: monthImp,
     backgroundColor: 'rgba(183,28,28,0.5)' }},
]);

// Monthly costs
barChart('monthlyCostChart', monthLabels, [
  {{ label: 'Electricity Total (£)', data: monthCost,
     backgroundColor: 'rgba(183,28,28,0.6)' }},
  {{ label: 'Gas Total (£)',         data: monthGasCost,
     backgroundColor: 'rgba(106,27,154,0.6)' }},
  {{ label: 'Saved vs No Solar (£)', data: monthSavings,
     backgroundColor: 'rgba(21,101,192,0.6)' }},
]);

// Yearly
barChart('yearlyChart', yearLabels, [
  {{ label: 'Solar (kWh)', data: yearPV,
     backgroundColor: 'rgba(230,81,0,0.7)' }},
  {{ label: 'Gas (kWh)',   data: yearGasKwh,
     backgroundColor: 'rgba(106,27,154,0.6)' }},
  {{ label: 'Elec Cost (£)', data: yearElecCost,
     backgroundColor: 'rgba(183,28,28,0.5)', yAxisID: 'y2' }},
  {{ label: 'Gas Cost (£)',  data: yearGasCost,
     backgroundColor: 'rgba(106,27,154,0.4)', yAxisID: 'y2' }},
], {{ scales: {{
  y:  {{ position: 'left',  title: {{ display: true, text: 'kWh' }} }},
  y2: {{ position: 'right', title: {{ display: true, text: '£' }},
        grid: {{ drawOnChartArea: false }} }},
}} }});

</script>
</body>
</html>"""

    return html
