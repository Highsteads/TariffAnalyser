#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    tariff_engine.py
# Description: Tariff comparison engine - applies UK energy tariff pricing
#              to half-hourly energy flow data from energy_timeseries.db
# Author:      CliveS & Claude Sonnet 4.6
# Date:        02-05-2026
# Version:     1.0

import json
import os
import sqlite3
from collections import Counter
from datetime import datetime, timedelta

# The date the hardcoded "typical" unit rates below, and the standing charges of
# the tariffs that are not Octopus's, were last checked. Tracker and Agile unit
# prices come from live data; the fixed reference rates (Go, Cosy, Flux, Ofgem
# cap, E.ON/EDF/Scottish Power) are illustrative and drift — surfaced in the
# report so a user knows how current they are.
REFERENCE_RATES_UPDATED = "2026-05-02"

# Standing charges (v1.11). The recorded-prices row uses the figure
# SigenEnergyManager recorded for each day (daily_history.json, beside the
# timeseries DB). The Octopus rows use Octopus's published figure for the
# user's region, fetched by octopus_prices.standing_charges_by_day() using each
# tariff's "octopus_name". The standing_p_day values below are only the
# fallback: for the Octopus rows they are Octopus's region F (North East
# England) figures on OCTOPUS_STANDING_UPDATED.
OCTOPUS_STANDING_UPDATED = "2026-09-27"
DAILY_HISTORY_NAME       = "daily_history.json"
# Key under which the plugin passes Octopus's Tracker standing charge (fetched
# only when the Tracker product setting is filled in), used as the recorded
# row's fallback when that row is Tracker.
TRACKER_LIVE_KEY         = "octopus_tracker"

# ---------------------------------------------------------------------------
# Tariff definitions
# Each tariff has a 'type' that controls how rates are calculated:
#   fixed        - single unit rate all hours
#   tou          - time-of-use: cheap window + peak rate
#   tou_multi    - multiple cheap windows (Cosy)
#   variable_db  - rate stored per-slot in the timeseries DB (the prices the
#                  user actually paid, whatever tariff SigenEnergyManager's
#                  tariff monitor was on — see recorded_tariff_label())
#   agile        - half-hourly rate from agile_prices DB
# ---------------------------------------------------------------------------

IMPORT_TARIFFS = {
    # Key kept as "tracker" for compatibility; the column holds whatever tariff
    # SigenEnergyManager recorded (Tracker, then Flux from 17-09-2026 on the
    # author's house). run_comparison() names the row from the data.
    "tracker": {
        "name":              "Your tariff (actual)",
        "type":              "variable_db",
        # Last resort only: each day's recorded figure comes first, then
        # Octopus's figure for the recorded tariff.
        "standing_p_day":    61.64,
    },
    "go": {
        "name":              "Octopus Go",
        "type":              "tou",
        "cheap_start":       "00:30",
        "cheap_end":         "05:30",
        "cheap_p":           7.5,
        "peak_p":            24.0,
        "standing_p_day":    63.21819,
        "octopus_name":      "Octopus Go",
    },
    "agile": {
        "name":              "Octopus Agile",
        "type":              "agile",
        "standing_p_day":    70.04823,
        "octopus_name":      "Agile Octopus",
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
        "standing_p_day":    61.51824,
        "octopus_name":      "Cosy Octopus",
    },
    "flux": {
        "name":              "Octopus Flux",
        "type":              "tou_multi",
        "slots": [
            {"start": "02:00", "end": "05:00", "rate_p": 7.01},   # off-peak
        ],
        "peak_start":        "16:00",
        "peak_end":          "19:00",
        "peak_p":            33.00,
        "shoulder_p":        21.00,
        "standing_p_day":    61.51824,
        "octopus_name":      "Octopus Flux Import",
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
    current_tariff_name="",
    recorded_standing=None,
    live_standing=None,
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
        current_tariff_name: the tariff SigenEnergyManager's tariff monitor says
                             is active now (e.g. "Octopus Flux"), used to name
                             the recorded-prices row; "" when unknown
        recorded_standing:   {"YYYY-MM-DD": pence_a_day} the house actually paid
                             for standing; None = read SigenEnergyManager's
                             daily_history.json beside timeseries_db_path
        live_standing:       {tariff_key: {"YYYY-MM-DD": pence_a_day}} from
                             octopus_prices.standing_charges_by_day(); a
                             tariff or day not in it uses standing_p_day

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
    # A key no longer in the table (Go Faster, dropped in v1.11 because Octopus
    # sells no such tariff) is ignored rather than raising KeyError.
    import_tariff_keys = [k for k in import_tariff_keys if k in IMPORT_TARIFFS]

    export_tariff = EXPORT_TARIFFS[export_tariff_key]

    # Load agile prices for the period
    agile_import = _load_agile_prices(agile_db_path, region, date_from, date_to, "import")
    agile_export = _load_agile_prices(agile_db_path, region, date_from, date_to, "export")

    # Load timeseries rows
    rows = _load_timeseries(timeseries_db_path, date_from, date_to)

    if not rows:
        return {"slots": 0, "days": 0, "results": [], "monthly": {}, "raw_totals": {}}

    if recorded_standing is None:
        recorded_standing = load_recorded_standing(recorded_standing_path(timeseries_db_path))
    live_standing = live_standing or {}

    # Compute calendar days in range
    days = (date_to - date_from).days + 1

    totals  = {"grid_import_kwh": 0.0, "grid_export_kwh": 0.0,
               "pv_kwh": 0.0, "home_kwh": 0.0}

    # --- Pass 1: resolve every tariff's per-slot rate and count own coverage ---
    slot_rates = []   # [(slot_start, imp_kwh, exp_kwh, {key: rate}), ...]
    raw_valid  = {k: 0 for k in import_tariff_keys}
    day_prices = _day_price_counts(rows)
    recorded_label, recorded_note = recorded_tariff_label(day_prices, current_tariff_name)
    names = {k: IMPORT_TARIFFS[k]["name"] for k in import_tariff_keys}
    if "tracker" in names:
        names["tracker"] = recorded_label
    for row in rows:
        (slot_start, slot_end,
         imp_kwh, exp_kwh, pv_kwh, home_kwh,
         soc_start, soc_end, bat_net,
         tracker_p, action) = row
        totals["grid_import_kwh"] += imp_kwh or 0.0
        totals["grid_export_kwh"] += exp_kwh or 0.0
        totals["pv_kwh"]          += pv_kwh  or 0.0
        totals["home_kwh"]        += home_kwh or 0.0

        rates = {}
        for key in import_tariff_keys:
            tariff = IMPORT_TARIFFS[key]
            if tariff["type"] == "variable_db":
                rates[key] = tracker_p
            else:
                rates[key] = _import_rate_for_slot(slot_start, tariff, agile_import)
            if rates[key] is not None:
                raw_valid[key] += 1
        slot_rates.append((slot_start, imp_kwh, exp_kwh, rates))

    total_slots = len(rows)

    # A tariff must have data for at least RANK_MIN_COVERAGE of the period to be
    # RANKED — otherwise (e.g. Agile with no cached prices) it would drag the
    # common comparison set to near-zero and collapse every tariff to £0. Such
    # tariffs are surfaced separately as "insufficient data", not ranked.
    RANK_MIN_COVERAGE = 0.5
    ranked_keys = [k for k in import_tariff_keys
                   if total_slots and raw_valid[k] / total_slots >= RANK_MIN_COVERAGE]
    # If nothing clears the bar, fall back to any tariff with SOME data so the
    # report is not empty.
    if not ranked_keys:
        ranked_keys = [k for k in import_tariff_keys if raw_valid[k] > 0]

    # --- Pass 2: price the ranked tariffs over their COMMON slot set ---
    # FAIR COMPARISON: only price a slot into the totals when EVERY ranked tariff
    # has a rate for it. Tariffs summed over different slot sets are not
    # comparable — a partial-coverage tariff would otherwise accumulate cost over
    # fewer slots yet pay a full standing charge and rank cheapest purely because
    # part of its usage was never counted.
    acc   = {k: {"import_p": 0.0, "export_p": 0.0} for k in ranked_keys}
    monthly        = {}   # {month_str: {tariff_key: net_energy_cost_p}} (common slots)
    monthly_common = {}   # {month_str: common_slot_count}
    common_by_day  = Counter()   # {date_str: common_slot_count}, for standing
    common_slots   = 0
    for (slot_start, imp_kwh, exp_kwh, rates) in slot_rates:
        month_str = slot_start[:7]
        monthly.setdefault(month_str, {k: 0.0 for k in ranked_keys})
        monthly_common.setdefault(month_str, 0)
        if any(rates[k] is None for k in ranked_keys):
            continue
        common_slots += 1
        monthly_common[month_str] += 1
        common_by_day[slot_start[:10]] += 1
        exp_rate = _export_rate_for_slot(slot_start, export_tariff, agile_export)
        exp_rev  = (exp_kwh or 0.0) * (exp_rate or 0.0)
        for key in ranked_keys:
            cost = (imp_kwh or 0.0) * rates[key]
            acc[key]["import_p"]    += cost
            acc[key]["export_p"]    += exp_rev
            monthly[month_str][key] += cost - exp_rev

    coverage_pct  = round(common_slots / total_slots * 100.0, 1) if total_slots else 0.0

    # Standing is charged per PRICED half-hour (1 slot = 1/48 of a day) so unit
    # cost and standing sit on the same slot basis as the common comparison,
    # each half-hour at the figure for its own day.
    recorded_name = clean_tariff_name(current_tariff_name)
    name_fits     = bool(recorded_name) and recorded_label == f"{recorded_name} (actual)"
    recorded_live = live_standing.get(live_standing_key(recorded_name), {}) if name_fits else {}
    standing_by_key  = {}
    standing_sources = {}
    recorded_fallback_days = []
    for key in ranked_keys:
        table_p = IMPORT_TARIFFS[key].get("standing_p_day", 0.0)
        live    = recorded_live if key == "tracker" else live_standing.get(key, {})
        total, used = 0.0, set()
        for day in sorted(common_by_day):
            p = recorded_standing.get(day) if key == "tracker" else None
            if p is not None:
                used.add("recorded")
            else:
                if key == "tracker":
                    recorded_fallback_days.append(day)
                p = live.get(day)
                if p is not None:
                    used.add("octopus")
                else:
                    p = table_p
                    used.add("table")
            total += p * common_by_day[day] / 48.0
        standing_by_key[key]  = total
        standing_sources[key] = sorted(used)

    results = []
    for key in ranked_keys:
        a = acc[key]
        standing = standing_by_key[key]
        net      = a["import_p"] - a["export_p"]
        total    = net + standing
        own_cov  = (raw_valid[key] / total_slots * 100.0) if total_slots else 0.0
        results.append({
            "tariff_key":        key,
            "tariff_name":       names[key],
            "import_cost_p":     round(a["import_p"],   2),
            "export_revenue_p":  round(a["export_p"],   2),
            "net_cost_p":        round(net,              2),
            "standing_charge_p": round(standing,         2),
            "total_cost_p":      round(total,            2),
            "coverage_pct":      coverage_pct,             # common basis (same for all)
            "own_coverage_pct":  round(own_cov,          1),  # this tariff's own data
            "insufficient_data": False,
        })

    # Sort ranked tariffs by total_cost_p ascending (cheapest first) — a fair
    # like-for-like ranking because every ranked tariff is priced over the
    # identical common slot set.
    results.sort(key=lambda r: r["total_cost_p"])

    # Append the excluded (insufficient-data) tariffs so the report can show
    # them below the ranking with their own coverage, not silently drop them.
    for key in import_tariff_keys:
        if key in ranked_keys:
            continue
        own_cov = (raw_valid[key] / total_slots * 100.0) if total_slots else 0.0
        results.append({
            "tariff_key":        key,
            "tariff_name":       names[key],
            "import_cost_p":     None,
            "export_revenue_p":  None,
            "net_cost_p":        None,
            "standing_charge_p": None,
            "total_cost_p":      None,
            "coverage_pct":      coverage_pct,
            "own_coverage_pct":  round(own_cov, 1),
            "insufficient_data": True,
        })

    return {
        "slots":          total_slots,
        "common_slots":   common_slots,
        "coverage_pct":   coverage_pct,
        "days":           days,
        "results":        results,
        "monthly":        monthly,
        "monthly_common": monthly_common,
        "raw_totals":     {k: round(v, 3) for k, v in totals.items()},
        "recorded_tariff_label": recorded_label,
        "recorded_tariff_note":  recorded_note,
        # Where each ranked tariff's standing charge came from: any of
        # "recorded" (SigenEnergyManager's daily figure), "octopus" (Octopus's
        # published figure) and "table" (standing_p_day).
        "standing_sources":      standing_sources,
        "recorded_standing_fallback_days": recorded_fallback_days,
        "recorded_standing_live_name": recorded_name if recorded_live else "",
    }


def calculate_savings(db_path, export_rate_p, date_from, date_to):
    """Calculate solar savings for a date range against the prices actually paid
    (the per-slot price SigenEnergyManager recorded — Tracker, Flux or whatever
    tariff its tariff monitor was on; see recorded_tariff_label()).

    Savings = what you would have paid without solar − what you actually paid.
    - Avoided import: solar/battery energy used at home × recorded rate per slot
    - Export revenue: grid export × flat export rate
    Falls back to Ofgem cap (24.5p) for slots with no recorded price.

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


# ---------------------------------------------------------------------------
# Which tariff do the recorded prices belong to?
# ---------------------------------------------------------------------------
# The halfhourly table's price column is named tracker_price_p, but it holds the
# rate of whatever tariff SigenEnergyManager's tariff monitor was on for that
# half-hour. On the author's house that was Tracker until 17-09-2026 and Flux
# after, with an Agile rehearsal in between. The table records no tariff name,
# so the shape of each day's prices says what kind of tariff it was:
#   flat        one price all day (Tracker, Flexible)
#   tou         a few prices in fixed bands (Go, Flux, Cosy)
#   halfhourly  a new price nearly every half-hour (Agile)

# A day needs at least this many priced half-hours to be classified, so a day
# still in progress, or one with gaps, cannot pass for a flat-rate day.
_MIN_CLASSIFY_SLOTS = 40
# A price must appear in at least this many half-hours of a day to count as a
# band. The slot either side of midnight can carry yesterday's Tracker price,
# which would otherwise make a Tracker day look like a two-band tariff.
_BAND_MIN_SLOTS = 3
# More distinct prices than this in one day is a half-hourly tariff.
_TOU_MAX_PRICES = 6

_PATTERN_WORDS = {
    "flat":       "one price a day",
    "tou":        "time-of-use bands",
    "halfhourly": "a new price every half-hour",
}

# The pattern each tariff name implies, for checking the name really fits the
# data before putting it on the row.
_NAME_PATTERNS = (
    ("agile",    "halfhourly"),
    ("tracker",  "flat"),
    ("flexible", "flat"),
    ("flux",     "tou"),
    ("cosy",     "tou"),
    ("go",       "tou"),
)

GENERIC_RECORDED_NAME = "Your tariff (actual)"


def clean_tariff_name(raw):
    """Tidy SigenEnergyManager's tariffActive state into a display name, or ""
    when it holds no real tariff ("", "Unknown", "Initialising", "?")."""
    name = str(raw or "").strip()
    if name.lower().endswith("(forced)"):
        name = name[:-len("(forced)")].strip()
    if name.lower() in ("", "unknown", "initialising", "?", "none"):
        return ""
    return name


def _expected_pattern(name):
    words = name.lower().replace("-", " ").split()
    for word, pattern in _NAME_PATTERNS:
        if word in words:
            return pattern
    return None


def _day_price_counts(rows):
    """{date_str: Counter({price: slots})} from _load_timeseries rows."""
    days = {}
    for row in rows:
        price = row[9]
        if price is None:
            continue
        days.setdefault(row[0][:10], Counter())[round(float(price), 4)] += 1
    return days


def _day_pattern(prices):
    """Classify one day's Counter of prices, or None if too few to tell."""
    if sum(prices.values()) < _MIN_CLASSIFY_SLOTS:
        return None
    if len(prices) > _TOU_MAX_PRICES:
        return "halfhourly"
    bands = sum(1 for n in prices.values() if n >= _BAND_MIN_SLOTS)
    return "flat" if bands <= 1 else "tou"


def recorded_tariff_label(day_prices, current_name=""):
    """Name the recorded-prices row from the data, not from a fixed label.

    day_prices:   {date_str: Counter({price: slots})}
    current_name: the tariff SigenEnergyManager says is active now, or "".
                  It is only used for the latest run of days, and only when
                  its kind matches that run's price pattern.

    Returns (label, note). note is "" when the whole period shows one pattern,
    otherwise a plain-English line saying when the pattern changed.
    """
    current_name = clean_tariff_name(current_name)
    runs = []   # [[pattern, first_date, last_date], ...]
    for ds in sorted(day_prices):
        pattern = _day_pattern(day_prices[ds])
        if pattern is None:
            continue
        if runs and runs[-1][0] == pattern:
            runs[-1][2] = ds
        else:
            runs.append([pattern, ds, ds])

    latest_pattern = runs[-1][0] if runs else None
    expected = _expected_pattern(current_name) if current_name else None
    name_fits = bool(current_name) and (
        expected is None or latest_pattern is None or expected == latest_pattern)

    if len(runs) <= 1:
        if name_fits:
            return f"{current_name} (actual)", ""
        return GENERIC_RECORDED_NAME, ""

    def _day(ds):
        try:
            return datetime.strptime(ds, "%Y-%m-%d").strftime("%-d %b")
        except ValueError:
            return ds

    parts = []
    for i, (pattern, first, last) in enumerate(runs):
        words = _PATTERN_WORDS[pattern]
        if i == len(runs) - 1:
            tail = f" ({current_name})" if name_fits else ""
            parts.append(f"{words}{tail} from {_day(first)}")
        elif i == 0:
            parts.append(f"{words} to {_day(last)}")
        else:
            parts.append(f"{words} {_day(first)} to {_day(last)}")
    joined = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
    note = (f"Your tariff changed during this period. The prices SigenEnergyManager "
            f"recorded show {joined}. The actual-prices row covers all of them.")
    return "Your tariffs (actual, mixed)", note


def recorded_tariff_for_period(timeseries_db_path, date_from, date_to, current_name=""):
    """recorded_tariff_label() for a date range read from the timeseries DB."""
    rows = _load_timeseries(timeseries_db_path, date_from, date_to)
    return recorded_tariff_label(_day_price_counts(rows), current_name)


# ---------------------------------------------------------------------------
# Standing charges the house actually paid (v1.11)
# ---------------------------------------------------------------------------

def recorded_standing_path(timeseries_db_path):
    """SigenEnergyManager's daily_history.json, which sits in the same prefs
    folder as its energy_timeseries.db. "" when there is no DB path."""
    if not timeseries_db_path:
        return ""
    return os.path.join(os.path.dirname(timeseries_db_path), DAILY_HISTORY_NAME)


def load_recorded_standing(path, field="elec_standing_p_day"):
    """{"YYYY-MM-DD": pence_a_day} from SigenEnergyManager's daily_history.json
    (a JSON list of day records). Days without the field — older records
    predate it — are left out, so the caller falls back for them. A missing or
    unreadable file gives {}."""
    if not path:
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, list):
        return {}
    out = {}
    for rec in data:
        if not isinstance(rec, dict):
            continue
        ds = rec.get("date")
        if not isinstance(ds, str) or len(ds) != 10:
            continue
        try:
            value = float(rec.get(field))
        except (TypeError, ValueError):
            continue
        if value != value or value <= 0:      # NaN or nonsense
            continue
        out[ds] = value
    return out


def live_standing_key(name):
    """The live_standing key holding Octopus's standing charge for a tariff
    named like SigenEnergyManager's Tariff Monitor names it, or None."""
    words = clean_tariff_name(name).lower().replace("-", " ").split()
    if not words or "intelligent" in words:
        return None
    if "tracker" in words:
        return TRACKER_LIVE_KEY
    for word, key in (("agile", "agile"), ("flux", "flux"), ("cosy", "cosy")):
        if word in words:
            return key
    if "go" in words and "faster" not in words:
        return "go"
    return None


def format_day_ranges(days):
    """"3 Jun to 5 Jun and 9 Jun" from a list of YYYY-MM-DD strings."""
    parsed = sorted({datetime.strptime(d, "%Y-%m-%d").date() for d in days})
    runs = []
    for d in parsed:
        if runs and (d - runs[-1][1]).days == 1:
            runs[-1][1] = d
        else:
            runs.append([d, d])

    def _one(d):
        return f"{d.day} {d.strftime('%b')}"
    parts = [_one(a) if a == b else f"{_one(a)} to {_one(b)}" for a, b in runs]
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


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
    except sqlite3.Error:
        # Expected: DB missing / locked / table absent -> fall through to empty coverage.
        # Narrowed from a bare 'except Exception' which also masked real programming errors.
        pass
    return None, None, 0


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_timeseries(db_path, date_from, date_to):
    """Return list of rows from halfhourly table for the date range."""
    import os
    if not db_path or not os.path.exists(db_path):
        return []
    con = None
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
        return rows
    except sqlite3.Error:
        # Expected: DB missing / locked / table absent -> empty result. Narrowed
        # from bare `except Exception` so a real programming error (bad SQL,
        # schema change) is NOT masked as a silent "no data" empty report.
        return []
    finally:
        if con is not None:
            con.close()


def _load_agile_prices(db_path, region, date_from, date_to, direction):
    """Return dict {slot_start_str: price_p} from agile_prices DB."""
    import os
    table = "agile_import" if direction == "import" else "agile_export"
    if not db_path or not os.path.exists(db_path):
        return {}
    con = None
    try:
        con  = sqlite3.connect(db_path)
        rows = con.execute(
            f"SELECT slot_start, price_p FROM {table} "
            f"WHERE region=? AND slot_start >= ? AND slot_start < ?",
            (region,
             date_from.strftime("%Y-%m-%dT00:00:00"),
             (date_to + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00"))
        ).fetchall()
        return {r[0]: r[1] for r in rows}
    except sqlite3.Error:
        # Narrowed from bare `except Exception` — a genuine error must not be
        # masked as "no agile prices" (which silently zeroes agile tariffs).
        return {}
    finally:
        if con is not None:
            con.close()
