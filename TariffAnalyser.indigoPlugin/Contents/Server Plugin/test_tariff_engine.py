#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_tariff_engine.py
# Description: Mock-free test suite for the Tariff Analyser financial engine.
#              tariff_engine imports only sqlite3 + datetime, so it is tested
#              directly against tiny in-memory-style SQLite fixtures — no Indigo
#              runtime needed. This is the plugin's FIRST test suite (v1.7):
#              the core value is correct, FAIR tariff-cost arithmetic.
# Author:      CliveS & Claude Opus 4.8
# Date:        18-07-2026
# Version:     1.0
#
# Run from the Server Plugin directory:
#   python3 -m pytest test_tariff_engine.py -q

import os
import sys
import sqlite3
import tempfile
import shutil
import unittest
from datetime import date

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
import tariff_engine as te   # noqa: E402


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

def _make_timeseries(tmp, slots):
    """slots: list of (slot_start, imp_kwh, exp_kwh, pv_kwh, home_kwh, tracker_p)."""
    path = os.path.join(tmp, "ts.db")
    con = sqlite3.connect(path)
    con.execute("""CREATE TABLE halfhourly (
        slot_start TEXT, slot_end TEXT, grid_import_kwh REAL, grid_export_kwh REAL,
        pv_kwh REAL, home_kwh REAL, battery_soc_start_pct REAL, battery_soc_end_pct REAL,
        battery_net_kwh REAL, tracker_price_p REAL, manager_action TEXT)""")
    for (s, imp, exp, pv, home, trk) in slots:
        con.execute("INSERT INTO halfhourly VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (s, s, imp, exp, pv, home, 50, 50, 0.0, trk, ""))
    con.commit(); con.close()
    return path


def _make_agile(tmp, imports, exports=None):
    """imports/exports: dict {slot_start: price_p} for region F."""
    path = os.path.join(tmp, "agile.db")
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE agile_import (slot_start TEXT, region TEXT, price_p REAL, PRIMARY KEY(slot_start,region))")
    con.execute("CREATE TABLE agile_export (slot_start TEXT, region TEXT, price_p REAL, PRIMARY KEY(slot_start,region))")
    for s, p in (imports or {}).items():
        con.execute("INSERT INTO agile_import VALUES (?,?,?)", (s, "F", p))
    for s, p in (exports or {}).items():
        con.execute("INSERT INTO agile_export VALUES (?,?,?)", (s, "F", p))
    con.commit(); con.close()
    return path


def _full_day(imp=1.0, exp=0.0, home=1.0, tracker_p=30.0, day="2026-07-01"):
    """48 half-hourly slots for one day."""
    out = []
    for h in range(24):
        for m in (0, 30):
            out.append((f"{day}T{h:02d}:{m:02d}:00", imp, exp, 0.0, home, tracker_p))
    return out


# ---------------------------------------------------------------------------
# _slot_in_window
# ---------------------------------------------------------------------------

class TestSlotInWindow(unittest.TestCase):

    def test_daytime_half_open(self):
        # go cheap window 00:30-05:30 — start inclusive, end exclusive
        self.assertTrue(te._slot_in_window("2026-07-01T00:30:00", "00:30", "05:30"))
        self.assertTrue(te._slot_in_window("2026-07-01T05:00:00", "00:30", "05:30"))
        self.assertFalse(te._slot_in_window("2026-07-01T05:30:00", "00:30", "05:30"))  # end exclusive
        self.assertFalse(te._slot_in_window("2026-07-01T00:00:00", "00:30", "05:30"))  # before start

    def test_overnight_wrap(self):
        # go_faster cheap window 23:30-05:30 wraps midnight
        self.assertTrue(te._slot_in_window("2026-07-01T23:30:00", "23:30", "05:30"))
        self.assertTrue(te._slot_in_window("2026-07-01T00:00:00", "23:30", "05:30"))
        self.assertTrue(te._slot_in_window("2026-07-01T05:00:00", "23:30", "05:30"))
        self.assertFalse(te._slot_in_window("2026-07-01T05:30:00", "23:30", "05:30"))
        self.assertFalse(te._slot_in_window("2026-07-01T12:00:00", "23:30", "05:30"))


# ---------------------------------------------------------------------------
# _import_rate_for_slot — the single pricing point (the critical finding)
# ---------------------------------------------------------------------------

class TestImportRateForSlot(unittest.TestCase):

    def test_fixed(self):
        self.assertEqual(te._import_rate_for_slot(
            "2026-07-01T12:00:00", te.IMPORT_TARIFFS["ofgem_cap"], {}), 24.50)

    def test_variable_db_returns_none(self):
        self.assertIsNone(te._import_rate_for_slot(
            "2026-07-01T12:00:00", te.IMPORT_TARIFFS["tracker"], {}))

    def test_tou_go_cheap_and_peak(self):
        go = te.IMPORT_TARIFFS["go"]
        self.assertEqual(te._import_rate_for_slot("2026-07-01T03:00:00", go, {}), 7.5)
        self.assertEqual(te._import_rate_for_slot("2026-07-01T12:00:00", go, {}), 24.0)

    def test_tou_multi_cosy_bands(self):
        cosy = te.IMPORT_TARIFFS["cosy"]
        self.assertEqual(te._import_rate_for_slot("2026-07-01T05:00:00", cosy, {}), 12.0)   # cheap slot
        self.assertEqual(te._import_rate_for_slot("2026-07-01T17:00:00", cosy, {}), 38.0)   # peak
        self.assertEqual(te._import_rate_for_slot("2026-07-01T09:00:00", cosy, {}), 26.0)   # shoulder

    def test_agile_cap_and_negative(self):
        ag = te.IMPORT_TARIFFS["agile"]   # cap_p = 100.0
        s = "2026-07-01T12:00:00"
        self.assertEqual(te._import_rate_for_slot(s, ag, {s: 15.0}), 15.0)
        self.assertEqual(te._import_rate_for_slot(s, ag, {s: 150.0}), 100.0)   # capped
        self.assertEqual(te._import_rate_for_slot(s, ag, {s: -5.0}), -5.0)     # negative preserved (no floor)
        self.assertIsNone(te._import_rate_for_slot(s, ag, {}))                 # missing -> None


# ---------------------------------------------------------------------------
# run_comparison — the FAIRNESS fix (flagship regression, v1.7)
# ---------------------------------------------------------------------------

class TestRunComparisonFairness(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_full_coverage_hand_computed(self):
        ts = _make_timeseries(self.tmp, _full_day(imp=1.0, tracker_p=30.0))
        ag = _make_agile(self.tmp, {})
        r = te.run_comparison(ts, ag, "F", date(2026, 7, 1), date(2026, 7, 1),
                              import_tariff_keys=["tracker", "ofgem_cap"],
                              export_tariff_key="outgoing_12p")
        self.assertEqual(r["common_slots"], 48)
        self.assertEqual(r["coverage_pct"], 100.0)
        by = {x["tariff_key"]: x for x in r["results"]}
        # tracker: 48 kWh x 30p + 61.64 standing = 1501.64
        self.assertAlmostEqual(by["tracker"]["total_cost_p"], 1501.64, places=1)
        # ofgem: 48 x 24.5 + 61.64 = 1237.64
        self.assertAlmostEqual(by["ofgem_cap"]["total_cost_p"], 1237.64, places=1)
        # ranked cheapest first -> ofgem
        self.assertEqual(r["results"][0]["tariff_key"], "ofgem_cap")

    def test_partial_agile_priced_over_common_set_only(self):
        """REGRESSION (v1.7): an agile tariff with only half its prices must be
        compared against fixed tariffs over the SAME 24 common slots — not
        summed over fewer slots while a rival covers all 48."""
        slots = _full_day(imp=1.0, tracker_p=30.0)
        ts = _make_timeseries(self.tmp, slots)
        # agile priced for only the first 24 of 48 slots, all at 5p
        ag_prices = {slots[i][0]: 5.0 for i in range(24)}
        ag = _make_agile(self.tmp, ag_prices)
        r = te.run_comparison(ts, ag, "F", date(2026, 7, 1), date(2026, 7, 1),
                              import_tariff_keys=["agile", "ofgem_cap"],
                              export_tariff_key="outgoing_12p")
        # common set is the 24 slots agile can price
        self.assertEqual(r["common_slots"], 24)
        self.assertEqual(r["coverage_pct"], 50.0)
        by = {x["tariff_key"]: x for x in r["results"]}
        # BOTH priced over 24 kWh: agile 24x5=120 + 53.35*(24/48)=26.675 -> 146.675
        self.assertAlmostEqual(by["agile"]["import_cost_p"], 120.0, places=1)
        self.assertAlmostEqual(by["agile"]["total_cost_p"], 146.68, places=1)
        # ofgem over the SAME 24 slots: 24x24.5=588 + 61.64*(24/48)=30.82 -> 618.82
        self.assertAlmostEqual(by["ofgem_cap"]["import_cost_p"], 588.0, places=1)
        self.assertAlmostEqual(by["ofgem_cap"]["total_cost_p"], 618.82, places=1)
        # own-coverage surfaces WHICH tariff limited the set
        self.assertEqual(by["agile"]["own_coverage_pct"], 50.0)
        self.assertEqual(by["ofgem_cap"]["own_coverage_pct"], 100.0)

    def test_zero_coverage_tariff_excluded_not_collapsing_others(self):
        """REGRESSION (v1.7): a selected tariff with NO price data (Agile with
        no cached prices) must be flagged insufficient and EXCLUDED, not drag
        every other tariff's common set to zero and collapse them all to £0."""
        ts = _make_timeseries(self.tmp, _full_day(imp=1.0, tracker_p=30.0))
        ag = _make_agile(self.tmp, {})   # no agile prices at all
        r = te.run_comparison(ts, ag, "F", date(2026, 7, 1), date(2026, 7, 1),
                              import_tariff_keys=["tracker", "agile", "ofgem_cap"],
                              export_tariff_key="outgoing_12p")
        # tracker + ofgem still compared fairly over the full 48 slots
        self.assertEqual(r["common_slots"], 48)
        by = {x["tariff_key"]: x for x in r["results"]}
        self.assertFalse(by["tracker"]["insufficient_data"])
        self.assertFalse(by["ofgem_cap"]["insufficient_data"])
        self.assertAlmostEqual(by["ofgem_cap"]["total_cost_p"], 1237.64, places=1)
        # agile flagged insufficient with a None total, not £0 or ranked
        self.assertTrue(by["agile"]["insufficient_data"])
        self.assertIsNone(by["agile"]["total_cost_p"])
        self.assertEqual(by["agile"]["own_coverage_pct"], 0.0)
        # the ranked set (non-insufficient) is what's ordered/crowned
        ranked = [x for x in r["results"] if not x["insufficient_data"]]
        self.assertEqual(ranked[0]["tariff_key"], "ofgem_cap")

    def test_export_revenue_shared_equally(self):
        """Export revenue is tariff-independent — every tariff must net the same
        export credit over the common slots (was dropped for skipped slots)."""
        slots = _full_day(imp=1.0, exp=2.0, tracker_p=30.0)
        ts = _make_timeseries(self.tmp, slots)
        ag_prices = {slots[i][0]: 5.0 for i in range(24)}
        ag = _make_agile(self.tmp, ag_prices)
        r = te.run_comparison(ts, ag, "F", date(2026, 7, 1), date(2026, 7, 1),
                              import_tariff_keys=["agile", "ofgem_cap"],
                              export_tariff_key="outgoing_12p")
        by = {x["tariff_key"]: x for x in r["results"]}
        # 24 common slots x 2 kWh x 12p = 576p export revenue — identical for both
        self.assertAlmostEqual(by["agile"]["export_revenue_p"], 576.0, places=1)
        self.assertAlmostEqual(by["ofgem_cap"]["export_revenue_p"], 576.0, places=1)


# ---------------------------------------------------------------------------
# calculate_savings arithmetic
# ---------------------------------------------------------------------------

class TestCalculateSavings(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_hand_computed_savings(self):
        # one slot: home 2 kWh, import 0.5 kWh (so 1.5 kWh met by solar/battery),
        # export 1 kWh, tracker 30p, export rate 12p.
        ts = _make_timeseries(self.tmp, [("2026-07-01T12:00:00", 0.5, 1.0, 3.0, 2.0, 30.0)])
        s = te.calculate_savings(ts, export_rate_p=12.0,
                                 date_from=date(2026, 7, 1), date_to=date(2026, 7, 1))
        # avoided import: solar_at_home = max(0, 2 - 0.5) = 1.5 kWh x 30p = 45p
        self.assertAlmostEqual(s["avoided_import_p"], 45.0, places=2)
        # export revenue: 1 kWh x 12p = 12p
        self.assertAlmostEqual(s["export_revenue_p"], 12.0, places=2)
        self.assertAlmostEqual(s["total_savings_p"], 57.0, places=2)
        # cost without solar: home 2 kWh x 30p = 60p
        self.assertAlmostEqual(s["cost_without_solar_p"], 60.0, places=2)

    def test_ofgem_fallback_when_no_tracker(self):
        # tracker_p NULL -> falls back to 24.5p
        ts = _make_timeseries(self.tmp, [("2026-07-01T12:00:00", 0.0, 0.0, 1.0, 1.0, None)])
        s = te.calculate_savings(ts, export_rate_p=12.0,
                                 date_from=date(2026, 7, 1), date_to=date(2026, 7, 1))
        # solar_at_home = max(0, 1 - 0) = 1 kWh x 24.5p fallback = 24.5p
        self.assertAlmostEqual(s["avoided_import_p"], 24.5, places=2)


# ---------------------------------------------------------------------------
# DB loaders — narrowed except must not mask, missing DB returns empty
# ---------------------------------------------------------------------------

class TestLoaders(unittest.TestCase):

    def test_missing_db_returns_empty(self):
        self.assertEqual(te._load_timeseries("/nonexistent/x.db", date(2026, 7, 1), date(2026, 7, 1)), [])
        self.assertEqual(te._load_agile_prices("/nonexistent/x.db", "F", date(2026, 7, 1), date(2026, 7, 1), "import"), {})

    def test_get_coverage_empty(self):
        tmp = tempfile.mkdtemp()
        try:
            ts = _make_timeseries(tmp, _full_day())
            earliest, latest, count = te.get_coverage(ts)
            self.assertEqual(earliest, "2026-07-01")
            self.assertEqual(count, 48)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
