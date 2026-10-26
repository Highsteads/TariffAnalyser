#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    tariff_engine.py
# Description: Tariff comparison engine - applies UK energy tariff pricing
#              to half-hourly energy flow data from energy_timeseries.db
# Author:      CliveS & Codex
# Date:        26-10-2026 15:40 UK
# Version:     1.2

import json
import os
import sqlite3
from bisect import bisect_right
from collections import Counter
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# The date the "typical" unit rates and standing charges of the tariffs that
# are not Octopus's (Ofgem cap, E.ON/EDF/Scottish Power) were last checked.
# They are illustrative and drift — surfaced in the report.
REFERENCE_RATES_UPDATED = "2026-05-02"

# The Octopus time-of-use tariffs (Go, Cosy, Flux, Economy 7 and Flux Export)
# use Octopus's published unit prices for the region, fetched by
# octopus_prices.unit_rates() for each day of the report (v1.12). The rates in
# the table below are only the fallback when that fetch fails: Octopus's region
# F (North East England) prices, direct debit, on OCTOPUS_RATES_UPDATED.
OCTOPUS_RATES_UPDATED = "2026-10-05"

# Octopus prices and SigenEnergyManager's records are UK wall-clock times.
UK_TZ = ZoneInfo("Europe/London")

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
        "cheap_p":           8.2143,
        "peak_p":            28.3072,
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
        # Three cheap windows: 04:00-07:00, 13:00-16:00 and 22:00-00:00.
        "slots": [
            {"start": "04:00", "end": "07:00", "rate_p": 11.9005},
            {"start": "13:00", "end": "16:00", "rate_p": 11.9005},
            {"start": "22:00", "end": "00:00", "rate_p": 11.9005},
        ],
        "peak_start":        "16:00",
        "peak_end":          "19:00",
        "peak_p":            36.3818,
        "shoulder_p":        24.2514,
        "standing_p_day":    61.51824,
        "octopus_name":      "Cosy Octopus",
    },
    "flux": {
        "name":              "Octopus Flux",
        "type":              "tou_multi",
        "slots": [
            {"start": "02:00", "end": "05:00", "rate_p": 13.9223},   # off-peak
        ],
        "peak_start":        "16:00",
        "peak_end":          "19:00",
        "peak_p":            32.4761,
        "shoulder_p":        23.1946,
        "standing_p_day":    61.51824,
        "octopus_name":      "Octopus Flux Import",
        # Octopus sells Flux import only with Flux Export, so the Flux row is
        # always priced with Flux Export whatever the export setting says.
        "export_tariff":     "flux_export",
    },
    "economy7": {
        # Octopus's Flexible tariff on a two-rate (Economy 7) meter. Octopus
        # publishes a day and a night price, not the hours: the night hours
        # depend on the meter, and 00:30-07:30 is assumed.
        "name":              "Economy 7 (Octopus Flexible)",
        "type":              "tou",
        "cheap_start":       "00:30",
        "cheap_end":         "07:30",
        "cheap_p":           13.7229,
        "peak_p":            31.6458,
        "standing_p_day":    61.64,
        "octopus_name":      "Flexible Octopus",
        "two_rate":          True,
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
        "name":  "Octopus Outgoing 12p",
        "type":  "fixed",
        "rate_p": 12.0,
    },
    "agile_outgoing": {
        "name":  "Octopus Agile Outgoing",
        "type":  "agile",
    },
    "flux_export": {
        "name":  "Octopus Flux Export",
        "type":  "tou_multi",
        "slots": [
            {"start": "02:00", "end": "05:00", "rate_p": 4.2064},
        ],
        "peak_start":   "16:00",
        "peak_end":     "19:00",
        "peak_p":       27.6905,
        "shoulder_p":   9.7084,
        "octopus_name": "Octopus Flux Export",
        "direction":    "EXPORT",
    },
    # Ofgem sets no minimum Smart Export Guarantee price; these two are only
    # illustrative rates for comparison.
    "seg_min": {
        "name":  "SEG low rate (illustrative 1.63p)",
        "type":  "fixed",
        "rate_p": 1.63,
    },
    "seg_typical": {
        "name":  "SEG typical rate (illustrative 7.5p)",
        "type":  "fixed",
        "rate_p": 7.5,
    },
}

# Tariff types whose unit prices are fetched from Octopus when the tariff has
# an "octopus_name", with the table rates as the fallback.
_BANDED_TYPES = ("tou", "tou_multi")


def live_rate_specs():
    """{key: {"octopus_name", "direction", "two_rate"}} for every tariff whose
    unit prices octopus_prices.unit_rates() should fetch. Agile is fetched
    separately (octopus_prices.fetch_agile_prices)."""
    specs = {}
    for table, direction in ((IMPORT_TARIFFS, "IMPORT"), (EXPORT_TARIFFS, "EXPORT")):
        for key, t in table.items():
            if t.get("octopus_name") and t.get("type") in _BANDED_TYPES:
                specs[key] = {"octopus_name": t["octopus_name"],
                              "direction":    t.get("direction", direction),
                              "two_rate":     bool(t.get("two_rate"))}
    return specs


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


# ---------------------------------------------------------------------------
# Pricing by overlap (v1.12, TA-01)
# ---------------------------------------------------------------------------
# SigenEnergyManager's half-hourly records do not start on the hour or half
# hour (22:04:29 to 22:34:31 is typical), while prices change at :00 and :30.
# So a record is priced by OVERLAP: its energy is split across the price
# periods it touches IN PROPORTION TO TIME, i.e. we assume the energy was used
# evenly through the record. A record that touches a moment with no price is
# unpriced (None), never priced at 0p.

SLOT_SECONDS = 1800


def local_epoch(ts):
    """Epoch seconds, preserving an explicit UTC offset when supplied.
    Legacy UK wall-clock times use the first occurrence of a repeated hour;
    run_comparison reports that ambiguity rather than claiming exact timing.
    """
    value = datetime.fromisoformat(str(ts))
    if value.tzinfo is None:
        value = value.replace(tzinfo=UK_TZ)
    return value.timestamp()


def _row_span(slot_start, slot_end):
    """(start, end) epoch seconds of a record. A record with no usable end
    (the older test fixtures repeat the start) is taken as one half-hour."""
    s = local_epoch(slot_start)
    try:
        e = local_epoch(slot_end) if slot_end else s
    except (TypeError, ValueError):
        e = s
    if e <= s:
        e = s + SLOT_SECONDS
    return s, e


def covered_day_fractions(spans, date_from, date_to):
    """Union of covered seconds per UK calendar day, divided by that day's
    real length. Handles 23/25-hour days, gaps, drift and overlapping rows.
    This affects standing only; stored energy is never rewritten or split.
    """
    intervals = sorted((s, e) for s, e in spans if e > s)
    merged = []
    for s, e in intervals:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(e, merged[-1][1]))
        else:
            merged.append((s, e))
    fractions = {}
    day = date_from
    while day <= date_to:
        a, b = _band_epochs(day, "00:00", "24:00")
        seconds = sum(max(0.0, min(e, b) - max(s, a)) for s, e in merged)
        if seconds:
            fractions[day.isoformat()] = min(1.0, seconds / (b - a))
        day += timedelta(days=1)
    return fractions


def ambiguous_local_time(ts):
    """A legacy timestamp without an offset cannot distinguish the repeated
    autumn hour (or a non-existent spring time). Surface that uncertainty.
    """
    if not ts:
        return False
    try:
        value = datetime.fromisoformat(str(ts))
    except (TypeError, ValueError):
        return False
    return (value.tzinfo is None and
            value.replace(tzinfo=UK_TZ, fold=0).utcoffset() !=
            value.replace(tzinfo=UK_TZ, fold=1).utcoffset())


class PriceTimeline:
    """Prices over time: a sorted list of (start, end, pence_per_kWh) in
    epoch seconds. An end of None runs to the next start (or for ever)."""

    def __init__(self, periods):
        rows = sorted((float(a), b, float(p)) for a, b, p in periods if p is not None)
        fixed = []
        for i, (a, b, p) in enumerate(rows):
            if b is None:
                b = rows[i + 1][0] if i + 1 < len(rows) else float("inf")
            if b > a:
                fixed.append((a, float(b), p))
        self.periods = fixed
        self.starts  = [a for a, _b, _p in fixed]

    def __bool__(self):
        return bool(self.periods)

    def price(self, s, e):
        """Time-weighted price over [s, e), or None if any part is unpriced."""
        if e <= s or not self.periods:
            return None
        i = bisect_right(self.starts, s) - 1
        if i < 0:
            return None
        t, cost = s, 0.0
        while t < e:
            if i >= len(self.periods):
                return None
            a, b, p = self.periods[i]
            if a > t:
                return None          # a gap with no price
            if b <= t:
                i += 1
                continue
            end = min(e, b)
            cost += (end - t) * p
            t = end
            i += 1
        return cost / (e - s)


def _day_range(date_from, date_to):
    cur = date_from - timedelta(days=1)
    while cur <= date_to + timedelta(days=1):
        yield cur
        cur += timedelta(days=1)


def _day_bands(tariff):
    """[(start_hhmm, end_hhmm), ...] covering one day at every price change
    of a time-of-use table, end "24:00" for the last."""
    marks = {"00:00"}
    if tariff["type"] == "tou":
        marks |= {tariff["cheap_start"], tariff["cheap_end"]}
    elif tariff["type"] == "tou_multi":
        for slot in tariff["slots"]:
            marks |= {slot["start"], slot["end"]}
        marks |= {tariff["peak_start"], tariff["peak_end"]}
    marks = sorted(marks)
    return list(zip(marks, marks[1:] + ["24:00"]))


def _band_epochs(day, start_hhmm, end_hhmm):
    def at(d, hhmm):
        if hhmm == "24:00":
            d, hhmm = d + timedelta(days=1), "00:00"
        h, m = (int(x) for x in hhmm.split(":"))
        return datetime(d.year, d.month, d.day, h, m, tzinfo=UK_TZ).timestamp()
    return at(day, start_hhmm), at(day, end_hhmm)


def table_timeline(tariff, date_from, date_to):
    """The plugin's own band prices for a time-of-use tariff, laid out over
    each local day of the period (with a day either side)."""
    periods = []
    for day in _day_range(date_from, date_to):
        for a, b in _day_bands(tariff):
            rate = _import_rate_for_slot(f"2000-01-01T{a}:00", tariff, {})
            s, e = _band_epochs(day, a, b)
            periods.append((s, e, rate))
    return PriceTimeline(periods)


def live_timeline(tariff, registers, date_from, date_to):
    """Octopus's prices for a tariff as a PriceTimeline, or None.

    registers: {"standard": [(start, end, p), ...]} for a single-register
    tariff, whose periods carry their own times; or {"day": [...],
    "night": [...]} for Economy 7, whose prices carry dates only, laid over
    the tariff's night window."""
    if not registers:
        return None
    if registers.get("standard"):
        tl = PriceTimeline(registers["standard"])
        return tl or None
    day_tl   = PriceTimeline(registers.get("day") or [])
    night_tl = PriceTimeline(registers.get("night") or [])
    if not day_tl or not night_tl or tariff.get("type") != "tou":
        return None
    periods = []
    for day in _day_range(date_from, date_to):
        for a, b in _day_bands(tariff):
            s, e = _band_epochs(day, a, b)
            night = _slot_in_window(f"2000-01-01T{a}:00",
                                    tariff["cheap_start"], tariff["cheap_end"])
            p = (night_tl if night else day_tl).price(s, s + 1)
            if p is not None:
                periods.append((s, e, p))
    tl = PriceTimeline(periods)
    return tl or None


def agile_timeline(prices, cap=None):
    """PriceTimeline from {local slot_start: price} half-hour Agile prices."""
    periods = []
    for slot, p in (prices or {}).items():
        try:
            s = local_epoch(slot)
        except (TypeError, ValueError):
            continue
        if cap is not None:
            p = min(p, cap)
        periods.append((s, s + SLOT_SECONDS, p))
    return PriceTimeline(periods)


class RateBook:
    """Unit prices for every tariff over one report period.

    rate(spec_key, table, s, e) returns (pence_per_kWh or None, source) where
    source is "octopus" (Octopus's published price), "table" (the plugin's
    own figure, used only where Octopus's could not be had) or "typical" (a
    fixed illustrative rate)."""

    def __init__(self, live_rates, date_from, date_to, agile_import=None, agile_export=None):
        self.live      = live_rates or {}
        self.date_from = date_from
        self.date_to   = date_to
        self.agile     = {"import": agile_import or {}, "export": agile_export or {}}
        self._live_tl  = {}
        self._table_tl = {}
        self._agile_tl = {}

    def _timelines(self, key, tariff):
        if key not in self._live_tl:
            self._live_tl[key] = (live_timeline(tariff, self.live.get(key),
                                                self.date_from, self.date_to)
                                  if tariff.get("octopus_name") else None)
            self._table_tl[key] = table_timeline(tariff, self.date_from, self.date_to)
        return self._live_tl[key], self._table_tl[key]

    def rate(self, key, tariff, s, e, direction="import"):
        ttype = tariff["type"]
        if ttype == "fixed":
            return tariff["rate_p"], "typical"
        if ttype == "agile":
            if direction not in self._agile_tl:
                self._agile_tl[direction] = agile_timeline(
                    self.agile[direction], tariff.get("cap_p"))
            p = self._agile_tl[direction].price(s, e)
            return (p, "octopus") if p is not None else (None, None)
        if ttype in _BANDED_TYPES:
            live, table = self._timelines(key, tariff)
            if live is not None:
                p = live.price(s, e)
                if p is not None:
                    return p, "octopus"
            p = table.price(s, e)
            return (p, "table") if p is not None else (None, None)
        return None, None


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
    recorded_export=None,
    live_rates=None,
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
        export_tariff_key:   key from EXPORT_TARIFFS for the comparison rows.
                             Flux always uses Flux Export (Octopus sells them
                             only as a pair), and the actual row uses the
                             export price recorded for each day, falling back
                             to this tariff for a day with none
        current_tariff_name: the tariff SigenEnergyManager's tariff monitor says
                             is active now (e.g. "Octopus Flux"), used to name
                             the recorded-prices row; "" when unknown
        recorded_standing:   {"YYYY-MM-DD": pence_a_day} the house actually paid
                             for standing; None = read SigenEnergyManager's
                             daily_history.json beside timeseries_db_path
        live_standing:       {tariff_key: {"YYYY-MM-DD": pence_a_day}} from
                             octopus_prices.standing_charges_by_day(); a
                             tariff or day not in it uses standing_p_day
        recorded_export:     {"YYYY-MM-DD": pence_per_kWh} the house was paid
                             for export; None = read daily_history.json
        live_rates:          {tariff_key: {register: [(start, end, p), ...]}}
                             from octopus_prices.unit_rates(); a tariff or
                             moment not in it uses the table rates

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

    if export_tariff_key not in EXPORT_TARIFFS:
        export_tariff_key = "outgoing_12p"

    # Load agile prices for the period (a day either side, so a record that
    # starts just before midnight can still be priced by overlap)
    agile_import = _load_agile_prices(agile_db_path, region, date_from - timedelta(days=1),
                                      date_to + timedelta(days=1), "import")
    agile_export = _load_agile_prices(agile_db_path, region, date_from - timedelta(days=1),
                                      date_to + timedelta(days=1), "export")
    book = RateBook(live_rates, date_from, date_to, agile_import, agile_export)

    # Load timeseries rows
    rows = _load_timeseries(timeseries_db_path, date_from, date_to)

    if not rows:
        return {"slots": 0, "days": 0, "results": [], "monthly": {}, "raw_totals": {}}

    if recorded_standing is None:
        recorded_standing = load_recorded_standing(recorded_standing_path(timeseries_db_path))
    if recorded_export is None:
        recorded_export = load_recorded_export(recorded_standing_path(timeseries_db_path))
    live_standing = live_standing or {}

    # Compute calendar days in range
    days = (date_to - date_from).days + 1

    totals  = {"grid_import_kwh": 0.0, "grid_export_kwh": 0.0,
               "pv_kwh": 0.0, "home_kwh": 0.0}

    # Which export tariff each row is priced with: "recorded" for the actual
    # row, the tariff's own pair (Flux -> Flux Export), else the setting.
    export_keys = {}
    for key in import_tariff_keys:
        if IMPORT_TARIFFS[key]["type"] == "variable_db":
            export_keys[key] = "recorded"
        else:
            export_keys[key] = IMPORT_TARIFFS[key].get("export_tariff", export_tariff_key)

    def _export_rate(ekey, day, s, e):
        if ekey == "recorded":
            p = recorded_export.get(day)
            if p is not None:
                return p, "recorded"
            p, _src = book.rate(export_tariff_key, EXPORT_TARIFFS[export_tariff_key],
                                s, e, "export")
            return p, "chosen"
        return book.rate(ekey, EXPORT_TARIFFS[ekey], s, e, "export")

    # --- Pass 1: resolve every tariff's per-slot rates and count own coverage ---
    slot_rates = []   # Keep spans beside rates for calendar-day standing.
    ambiguous_rows = 0
    raw_valid  = {k: 0 for k in import_tariff_keys}
    rate_sources   = {k: Counter() for k in import_tariff_keys}
    export_sources = {k: Counter() for k in import_tariff_keys}
    day_prices = _day_price_counts(rows)
    recorded_label, recorded_note = recorded_tariff_label(day_prices, current_tariff_name)
    names = {k: IMPORT_TARIFFS[k]["name"] for k in import_tariff_keys}
    if "tracker" in names:
        names["tracker"] = recorded_label
    for row in rows:
        (slot_start, slot_end,
         imp_kwh, exp_kwh, pv_kwh, home_kwh,
         soc_start, soc_end, bat_net,
         tracker_p, action) = row[:11]
        totals["grid_import_kwh"] += imp_kwh or 0.0
        totals["grid_export_kwh"] += exp_kwh or 0.0
        totals["pv_kwh"]          += pv_kwh  or 0.0
        totals["home_kwh"]        += home_kwh or 0.0
        s, e = _row_span(slot_start, slot_end)
        ambiguous_rows += bool(ambiguous_local_time(slot_start) or ambiguous_local_time(slot_end))
        day  = slot_start[:10]

        rates = {}
        exp_cache = {}
        for key in import_tariff_keys:
            tariff = IMPORT_TARIFFS[key]
            if tariff["type"] == "variable_db":
                imp_rate, src = tracker_p, ("recorded" if tracker_p is not None else None)
            else:
                imp_rate, src = book.rate(key, tariff, s, e)
            ekey = export_keys[key]
            if ekey not in exp_cache:
                exp_cache[ekey] = _export_rate(ekey, day, s, e)
            exp_rate, esrc = exp_cache[ekey]
            # An export price only matters when something was exported; a
            # missing one then leaves the slot unpriced rather than at 0p.
            if not (exp_kwh or 0.0) > 0:
                exp_rate = exp_rate if exp_rate is not None else 0.0
            if imp_rate is None or exp_rate is None:
                rates[key] = None
                continue
            rates[key] = (imp_rate, exp_rate)
            raw_valid[key] += 1
            rate_sources[key][src] += 1
            if (exp_kwh or 0.0) > 0 and esrc:
                export_sources[key][esrc] += 1
        slot_rates.append((slot_start, imp_kwh, exp_kwh, rates, s, e))

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
    common_spans = []
    common_slots   = 0
    for (slot_start, imp_kwh, exp_kwh, rates, s, e) in slot_rates:
        month_str = slot_start[:7]
        monthly.setdefault(month_str, {k: 0.0 for k in ranked_keys})
        monthly_common.setdefault(month_str, 0)
        if any(rates[k] is None for k in ranked_keys):
            continue
        common_slots += 1
        monthly_common[month_str] += 1
        common_spans.append((s, e))
        for key in ranked_keys:
            imp_rate, exp_rate = rates[key]
            cost    = (imp_kwh or 0.0) * imp_rate
            exp_rev = (exp_kwh or 0.0) * exp_rate
            acc[key]["import_p"]    += cost
            acc[key]["export_p"]    += exp_rev
            monthly[month_str][key] += cost - exp_rev

    coverage_pct  = round(common_slots / total_slots * 100.0, 1) if total_slots else 0.0

    # A daily charge belongs to a calendar day, whose elapsed length varies
    # at the clock changes. Charge only the union of the priced intervals.
    day_fractions = covered_day_fractions(common_spans, date_from, date_to)
    data_fractions = covered_day_fractions(
        [(r[-2], r[-1]) for r in slot_rates], date_from, date_to)
    if not common_slots:
        ranked_keys = []  # disjoint price coverage must never rank zero-cost rows
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
        for day in sorted(day_fractions):
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
            total += p * day_fractions[day]
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

    for result in results:
        illustrative = IMPORT_TARIFFS[result["tariff_key"]]["type"] == "fixed"
        result["illustrative"] = illustrative
        result["ranking_eligible"] = not illustrative and not result["insufficient_data"]

    return {
        "standing_day_fractions": day_fractions,
        "data_coverage_pct": round(sum(data_fractions.values()) / days * 100, 1),
        "priced_time_coverage_pct": round(sum(day_fractions.values()) / days * 100, 1),
        "ambiguous_time_rows": ambiguous_rows,
        "comparison_basis": "recorded_flows",
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
        # Where each tariff's unit prices came from, counted in half-hour
        # records: "recorded", "octopus", "table" or "typical".
        "rate_sources":   {k: dict(v) for k, v in rate_sources.items()},
        # Where each tariff's export prices came from, counted in records that
        # exported: "recorded", "chosen" (the export setting, on a day with no
        # recorded price), "octopus", "table" or "typical".
        "export_sources": {k: dict(v) for k, v in export_sources.items()},
        "export_keys":    export_keys,
        "export_tariff_key": export_tariff_key,
    }


# Days of records read before a savings period starts, so the battery's
# solar/grid mix is already realistic on the first day (the battery cycles at
# least daily, so two days wash out the unknown starting mix).
PROVENANCE_WARMUP_DAYS = 2
_OFGEM_FALLBACK_P      = 24.5   # pence/kWh when a record has no price at all


def _battery_kwh_per_pct(rows):
    """How many kWh one percent of state of charge holds, estimated from the
    records (net battery energy over change in SoC), or None."""
    energy = change = 0.0
    for row in rows:
        net, s0, s1 = row[8], row[6], row[7]
        if net is None or s0 is None or s1 is None or s1 == s0:
            continue
        energy += abs(net)
        change += abs(s1 - s0)
    if change <= 0 or energy <= 0:
        return None
    return energy / change


def calculate_savings(db_path, export_rate_p, date_from, date_to, recorded_export=None):
    """Calculate solar savings for a date range against the prices actually paid
    (the per-slot price SigenEnergyManager recorded — Tracker, Flux or whatever
    tariff its tariff monitor was on; see recorded_tariff_label()).

    Total saved = what you would have paid with no solar and no battery (every
    kWh the house used bought at that half-hour's price) minus what you
    actually paid (import cost minus export revenue). It splits into:
    - solar used at home: solar used directly, plus the SOLAR share of what
      the battery gave the house;
    - solar exported: export revenue, less the part that was grid-charged
      battery energy sold back;
    - time-shifting: battery energy that was charged from the GRID, valued at
      the price when it was used or sold, minus what charging it cost.

    Battery provenance (TA-R1, v1.12): the battery's contents are tracked as a
    solar part and a grid part. Charge from solar the house did not need adds
    to the solar part; charge while importing adds to the grid part; each
    discharge takes from both in proportion; and after each record both are
    scaled to the battery's real state of charge, so losses come out of both.

    The export price for each day is the one SigenEnergyManager recorded
    (recorded_export, read from daily_history.json when None), else
    export_rate_p. A record with no recorded import price uses 24.5p (a real
    0p price is kept).

    Returns a dict:
        pv_kwh               total solar generated (kWh)
        pv_to_home_kwh       solar used at home, directly or via the battery
        export_kwh           total exported (kWh)
        home_kwh             total home consumption (kWh)
        grid_import_kwh      total grid import (kWh)
        grid_charged_kwh     battery charge taken from the grid (kWh)
        grid_battery_used_kwh grid-charged battery energy used or exported
        avoided_import_p     solar used at home, in pence
        solar_export_p       solar exported, in pence
        timeshift_p          time-shifting saving, in pence (can be negative)
        export_revenue_p     all export revenue, in pence
        solar_savings_p      avoided_import_p + solar_export_p
        total_savings_p      solar_savings_p + timeshift_p
                             = cost_without_solar_p - cost_with_solar_p
        cost_with_solar_p    actual energy cost (import cost - export revenue)
        cost_without_solar_p what the bill would have been with no solar
        slots                number of slots processed
    """
    rows_all = _load_timeseries(db_path, date_from - timedelta(days=PROVENANCE_WARMUP_DAYS),
                                date_to)
    first_day = date_from.strftime("%Y-%m-%d")
    rows = [r for r in rows_all if r[0][:10] >= first_day]
    keys = ("pv_kwh", "pv_to_home_kwh", "export_kwh", "home_kwh", "grid_import_kwh",
            "grid_charged_kwh", "grid_battery_used_kwh", "avoided_import_p",
            "solar_export_p", "timeshift_p", "export_revenue_p", "solar_savings_p",
            "total_savings_p", "cost_with_solar_p", "cost_without_solar_p")
    if not rows:
        out = {k: 0.0 for k in keys}
        out["slots"] = 0
        return out

    if recorded_export is None:
        recorded_export = load_recorded_export(recorded_standing_path(db_path))
    kwh_per_pct = _battery_kwh_per_pct(rows_all)

    t = {k: 0.0 for k in keys}
    solar_part = grid_part = None   # battery contents by origin, kWh

    for row in rows_all:
        imp_kwh  = row[2] or 0.0
        exp_kwh  = row[3] or 0.0
        pv_kwh   = row[4] or 0.0
        home_kwh = row[5] or 0.0
        net      = row[8] or 0.0
        chg = row[11] if len(row) > 11 and row[11] is not None else max(0.0, net)
        dis = row[12] if len(row) > 12 and row[12] is not None else max(0.0, -net)
        chg, dis = max(0.0, chg), max(0.0, dis)

        if solar_part is None:
            # Unknown starting mix: count what is already in the battery as
            # solar. The warm-up days dilute it before the period starts.
            soc0 = row[6]
            solar_part = (soc0 * kwh_per_pct) if (kwh_per_pct and soc0 is not None) else 0.0
            grid_part  = 0.0

        # Where the battery's charge came from: solar the house did not need
        # first, then the grid (never more than was imported).
        pv_direct = min(pv_kwh, home_kwh)
        solar_spare = max(0.0, pv_kwh - pv_direct)
        grid_chg = min(max(0.0, chg - solar_spare), imp_kwh)
        solar_chg = chg - grid_chg

        # Discharge draws on both parts in proportion. An empty battery
        # (nothing tracked) counts as solar.
        held = solar_part + grid_part
        solar_frac = solar_part / held if held > 1e-9 else 1.0
        solar_part = max(0.0, solar_part - dis * solar_frac)
        grid_part  = max(0.0, grid_part - dis * (1.0 - solar_frac))
        solar_part += solar_chg
        grid_part  += grid_chg
        soc1 = row[7]
        if kwh_per_pct and soc1 is not None and solar_part + grid_part > 1e-9:
            scale = (soc1 * kwh_per_pct) / (solar_part + grid_part)
            solar_part *= scale
            grid_part  *= scale

        if row[0][:10] < first_day:
            continue                 # warm-up record: provenance only

        rate_p = row[9] if row[9] is not None else _OFGEM_FALLBACK_P
        exp_p  = recorded_export.get(row[0][:10])
        if exp_p is None:
            exp_p = export_rate_p

        bat_to_home = min(dis, max(0.0, home_kwh - pv_direct))
        bat_to_exp  = min(max(0.0, dis - bat_to_home), exp_kwh)
        grid_share  = 1.0 - solar_frac

        export_rev = exp_kwh * exp_p
        without    = home_kwh * rate_p
        with_      = imp_kwh * rate_p - export_rev
        timeshift  = (grid_share * bat_to_home * rate_p
                      + grid_share * bat_to_exp * exp_p
                      - grid_chg * rate_p)
        solar_exp  = export_rev - grid_share * bat_to_exp * exp_p
        total      = without - with_

        t["cost_without_solar_p"]  += without
        t["cost_with_solar_p"]     += with_
        t["total_savings_p"]       += total
        t["timeshift_p"]           += timeshift
        t["solar_export_p"]        += solar_exp
        # Solar used at home is what remains, so the three parts always add
        # up to the total (meter rounding included).
        t["avoided_import_p"]      += total - timeshift - solar_exp
        t["export_revenue_p"]      += export_rev
        t["grid_charged_kwh"]      += grid_chg
        t["grid_battery_used_kwh"] += grid_share * (bat_to_home + bat_to_exp)
        t["pv_to_home_kwh"]        += pv_direct + solar_frac * bat_to_home
        t["pv_kwh"]                += pv_kwh
        t["export_kwh"]            += exp_kwh
        t["home_kwh"]              += home_kwh
        t["grid_import_kwh"]       += imp_kwh

    t["solar_savings_p"] = t["avoided_import_p"] + t["solar_export_p"]
    out = {k: round(v, 3 if k.endswith("_kwh") else 2) for k, v in t.items()}
    out["slots"] = len(rows)
    return out


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


def load_recorded_export(path):
    """{"YYYY-MM-DD": pence_per_kWh}: the export price SigenEnergyManager
    recorded for each day (export_rate_p in daily_history.json — the flat
    Outgoing price, or on a banded tariff such as Flux Export the day's
    export revenue divided by its export). Days without it are left out."""
    return load_recorded_standing(path, "export_rate_p", allow_zero=True)


def load_recorded_standing(path, field="elec_standing_p_day", allow_zero=False):
    """{"YYYY-MM-DD": pence_a_day} from SigenEnergyManager's daily_history.json
    (a JSON list of day records). Days without the field — older records
    predate it — are left out, so the caller falls back for them. A missing or
    unreadable file gives {}. allow_zero keeps a recorded 0 (a price can be
    0p; a standing charge cannot)."""
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
        if value != value or value < 0 or (value == 0 and not allow_zero):
            continue                          # NaN or nonsense
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
        # MIN and MAX asked for together make SQLite read the whole table;
        # asked for separately each comes straight off the index.
        row = con.execute(
            "SELECT (SELECT MIN(slot_start) FROM halfhourly), "
            "(SELECT MAX(slot_start) FROM halfhourly), "
            "(SELECT COUNT(*) FROM halfhourly)"
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
    """Return list of rows from halfhourly table for the date range.

    Each row: slot_start, slot_end, grid_import_kwh, grid_export_kwh, pv_kwh,
    home_kwh, battery_soc_start_pct, battery_soc_end_pct, battery_net_kwh,
    tracker_price_p, manager_action, battery_charge_kwh,
    battery_discharge_kwh. The last two are None on databases that predate
    those columns."""
    if not db_path or not os.path.exists(db_path):
        return []
    con = None
    try:
        con  = sqlite3.connect(db_path)
        cols = {r[1] for r in con.execute("PRAGMA table_info(halfhourly)")}
        chg  = "battery_charge_kwh" if "battery_charge_kwh" in cols else "NULL"
        dis  = "battery_discharge_kwh" if "battery_discharge_kwh" in cols else "NULL"
        rows = con.execute(
            f"""SELECT slot_start, slot_end,
                      grid_import_kwh, grid_export_kwh, pv_kwh, home_kwh,
                      battery_soc_start_pct, battery_soc_end_pct, battery_net_kwh,
                      tracker_price_p, manager_action, {chg}, {dis}
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
