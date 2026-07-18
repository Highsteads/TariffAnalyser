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


if __name__ == "__main__":
    unittest.main(verbosity=2)
