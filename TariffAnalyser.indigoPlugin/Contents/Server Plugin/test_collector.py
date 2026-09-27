#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_collector.py
# Description: Tests for the pure helpers in daily_collector.py and
#              octopus_prices.py — TOU band assignment, window boundaries, gas
#              m3->kWh conversion, UTC->local conversion across the BST/GMT
#              boundary, and the Agile re-fetch period builder. No network or
#              Indigo runtime — these helpers are pure functions.
# Author:      CliveS & Claude Opus 4.8
# Date:        18-07-2026
# Version:     1.0
#
# Run:  python3 -m pytest test_collector.py -q

import os
import sys
import time
import unittest
from datetime import date

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

# Pin the timezone so UTC->local assertions are deterministic (the plugin runs
# on a UK machine; astimezone(tz=None) uses the system zone).
os.environ["TZ"] = "Europe/London"
try:
    time.tzset()
except AttributeError:
    pass

import daily_collector as dc     # noqa: E402
import octopus_prices as op      # noqa: E402


class TestInWindow(unittest.TestCase):

    def test_daytime_half_open(self):
        self.assertTrue(dc._in_window("02:00", "02:00", "05:00"))   # start inclusive
        self.assertTrue(dc._in_window("04:30", "02:00", "05:00"))
        self.assertFalse(dc._in_window("05:00", "02:00", "05:00"))  # end exclusive
        self.assertFalse(dc._in_window("01:30", "02:00", "05:00"))

    def test_overnight_wrap(self):
        self.assertTrue(dc._in_window("23:45", "23:30", "05:30"))
        self.assertTrue(dc._in_window("00:00", "23:30", "05:30"))
        self.assertFalse(dc._in_window("05:30", "23:30", "05:30"))
        self.assertFalse(dc._in_window("12:00", "23:30", "05:30"))


class TestApplyTou(unittest.TestCase):

    def test_go_two_band(self):
        # Go cheap 00:30-05:30 @7.5, peak @24. 1 kWh at 03:00 + 1 kWh at 12:00.
        slots = [("03:00", 1.0), ("12:00", 1.0)]
        total = dc._apply_tou_simple(slots, dc.GO_CHEAP_START, dc.GO_CHEAP_END,
                                     dc.GO_CHEAP_P, dc.GO_PEAK_P)
        self.assertAlmostEqual(total, 7.5 + 24.0, places=4)

    def test_flux_three_band(self):
        # off-peak 02:00-05:00, peak 16:00-19:00, shoulder otherwise.
        slots = [("03:00", 1.0), ("17:00", 1.0), ("09:00", 1.0)]
        total = dc._apply_tou_flux(slots, 7.01, 21.0, 33.0)
        self.assertAlmostEqual(total, 7.01 + 33.0 + 21.0, places=4)


class TestGasConversion(unittest.TestCase):

    def test_constant(self):
        # 1.02264 * 40 / 3.6 = 11.363...
        self.assertAlmostEqual(dc.GAS_KWH_PER_M3, 1.02264 * 40 / 3.6, places=3)

    def test_ten_m3(self):
        self.assertAlmostEqual(10.0 * dc.GAS_KWH_PER_M3, 113.63, places=2)


class TestUtcToLocal(unittest.TestCase):

    def test_bst_summer_offset(self):
        # 1 July: BST (UTC+1). 00:00Z -> 01:00 local.
        dt = dc._utc_to_local_dt("2026-07-01T00:00:00Z")
        self.assertEqual(dt.strftime("%Y-%m-%d %H:%M"), "2026-07-01 01:00")

    def test_gmt_winter_no_offset(self):
        # 1 Jan: GMT (UTC+0). 00:00Z -> 00:00 local.
        dt = dc._utc_to_local_dt("2026-01-01T00:00:00Z")
        self.assertEqual(dt.strftime("%Y-%m-%d %H:%M"), "2026-01-01 00:00")

    def test_octopus_prices_utc_to_local_string(self):
        s = op._utc_to_local(  # returns 'YYYY-MM-DDTHH:MM:SS' local
            "2026-07-01T00:00:00Z")
        self.assertEqual(s, "2026-07-01T01:00:00")


class TestBuildPeriods(unittest.TestCase):

    def test_missing_day_included(self):
        # No existing slots -> the day must be fetched.
        periods = op._build_periods(date(2026, 7, 1), date(2026, 7, 1), set())
        self.assertEqual(len(periods), 1)
        pf, pt = periods[0]
        # UTC window: previous day 23:00Z to this day 23:00Z (covers BST/GMT)
        self.assertEqual(pf, "2026-06-30T23:00:00Z")
        self.assertEqual(pt, "2026-07-01T23:00:00Z")

    def test_well_covered_day_skipped(self):
        # >= 40 existing slots for the day -> not re-fetched.
        existing = {f"2026-07-01T{h:02d}:{m:02d}:00" for h in range(24) for m in (0, 30)}
        self.assertEqual(len(existing), 48)
        periods = op._build_periods(date(2026, 7, 1), date(2026, 7, 1), existing)
        self.assertEqual(periods, [])

    def test_sparse_day_refetched(self):
        # Only 10 slots present (< 40) -> re-fetched.
        existing = {f"2026-07-01T{h:02d}:00:00" for h in range(10)}
        periods = op._build_periods(date(2026, 7, 1), date(2026, 7, 1), existing)
        self.assertEqual(len(periods), 1)


# ---------------------------------------------------------------------------
# v1.10 — Tracker product and install date are settings, not one house's values
# ---------------------------------------------------------------------------

class TestTrackerProductSetting(unittest.TestCase):

    def test_normalise(self):
        self.assertEqual(dc.normalise_tracker_product(""), "")
        self.assertEqual(dc.normalise_tracker_product(None), "")
        self.assertEqual(dc.normalise_tracker_product(" silver-25-04-11 "), "SILVER-25-04-11")
        self.assertEqual(dc.normalise_tracker_product("E-1R-SILVER-25-04-11-K"), "SILVER-25-04-11")
        with self.assertRaises(ValueError):
            dc.normalise_tracker_product("not a code!")

    def test_blank_product_makes_no_api_call(self):
        calls = []
        saved = dc._api_get
        dc._api_get = lambda *a, **k: calls.append(a) or {"results": []}
        try:
            rates = dc._fetch_tracker_rates(date(2026, 9, 1), date(2026, 9, 2), "F", "",
                                            lambda *a, **k: None)
        finally:
            dc._api_get = saved
        self.assertEqual(rates, {})
        self.assertEqual(calls, [])

    def test_product_and_region_build_the_tariff_code(self):
        urls = []
        saved = dc._api_get
        dc._api_get = lambda url, **k: urls.append(url) or {"results": []}
        try:
            dc._fetch_tracker_rates(date(2026, 9, 1), date(2026, 9, 2), "K",
                                    "SILVER-25-04-11", lambda *a, **k: None)
        finally:
            dc._api_get = saved
        self.assertEqual(len(urls), 1)
        self.assertIn("/products/SILVER-25-04-11/electricity-tariffs/"
                      "E-1R-SILVER-25-04-11-K/", urls[0])


class TestInstallDateSetting(unittest.TestCase):

    def test_parse(self):
        self.assertIsNone(dc.parse_install_date(""))
        self.assertEqual(dc.parse_install_date("2026-03-13"), date(2026, 3, 13))
        self.assertEqual(dc.parse_install_date("13/03/2026"), date(2026, 3, 13))
        with self.assertRaises(ValueError):
            dc.parse_install_date("March")

    def _savings(self, install_date):
        import tempfile
        import sqlite3
        ds = "2026-02-01"
        stubs = {
            "_fetch_tracker_rates":       lambda *a, **k: {ds: 20.0},
            "_fetch_flux_rates":          lambda *a, **k: {},
            "_fetch_octopus_consumption": lambda *a, **k: {},
            "_fetch_octopus_gas":         lambda *a, **k: {},
            "_aggregate_halfhourly":      lambda *a, **k: {ds: {
                "pv_kwh": 8.0, "home_kwh": 10.0, "imp_kwh": 2.0, "exp_kwh": 0.0,
                "bat_chg": 0.0, "bat_dis": 0.0, "tracker_avg_p": 20.0}},
        }
        saved = {k: getattr(dc, k) for k in stubs}
        for k, v in stubs.items():
            setattr(dc, k, v)
        tmp = tempfile.mkdtemp()
        try:
            db = os.path.join(tmp, "ts.db")
            dc.update_daily_summary(db, date(2026, 2, 1), date(2026, 2, 1),
                                    {"region": "F", "solar_install_date": install_date})
            con = sqlite3.connect(db)
            row = con.execute("SELECT savings_vs_no_solar_gbp FROM daily_summary").fetchone()
            con.close()
            return row[0]
        finally:
            for k, v in saved.items():
                setattr(dc, k, v)
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_no_install_date_counts_every_solar_day(self):
        # 8 kWh from solar at 20p = £1.60. Before v1.10 a fixed 13 March 2026
        # install date zeroed every earlier day for every user.
        self.assertAlmostEqual(self._savings(None), 1.60, places=4)

    def test_install_date_after_the_day_zeroes_its_savings(self):
        self.assertEqual(self._savings(date(2026, 3, 13)), 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
