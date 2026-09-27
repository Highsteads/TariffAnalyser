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



# ---------------------------------------------------------------------------
# v1.11 — standing charges from Octopus and from what was paid
# ---------------------------------------------------------------------------

# Canned Octopus answers in the shape the public API gives (network stubbed).
_PRODUCTS = {"results": [
    {"code": "GO-VAR-22-10-14", "display_name": "Octopus Go", "direction": "IMPORT",
     "available_from": "2022-10-14T00:00:00+01:00"},
    {"code": "INTELLI-VAR-24-10-29", "display_name": "Intelligent Octopus Go",
     "direction": "IMPORT", "available_from": "2024-10-29T00:00:00+01:00"},
    {"code": "FLUX-IMPORT-23-02-14", "display_name": "Octopus Flux Import",
     "direction": "IMPORT", "available_from": "2023-02-14T00:00:00Z"},
    {"code": "FLUX-EXPORT-23-02-14", "display_name": "Octopus Flux Export",
     "direction": "EXPORT", "available_from": "2023-02-14T00:00:00Z"},
], "next": None}
_GO_STANDING = {"results": [
    {"value_inc_vat": 63.21819, "valid_from": "2026-04-30T23:00:00Z", "valid_to": None,
     "payment_method": None},
    {"value_inc_vat": 61.51824, "valid_from": "2026-03-31T23:00:00Z",
     "valid_to": "2026-04-30T23:00:00Z", "payment_method": None},
], "next": None}
_FLUX_STANDING = {"results": [
    {"value_inc_vat": 61.51824, "valid_from": "2026-03-31T23:00:00Z", "valid_to": None,
     "payment_method": "DIRECT_DEBIT"},
    {"value_inc_vat": 65.0, "valid_from": "2026-03-31T23:00:00Z", "valid_to": None,
     "payment_method": "NON_DIRECT_DEBIT"},
], "next": None}


class TestOctopusStandingCharges(unittest.TestCase):

    NAMES = {"go": "Octopus Go", "flux": "Octopus Flux Import"}

    def setUp(self):
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "agile_prices.db")
        self.urls = []
        self.logs = []
        self._saved = op._api_get

    def tearDown(self):
        import shutil
        op._api_get = self._saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _answer(self, url):
        self.urls.append(url)
        if "/products/?" in url:
            return _PRODUCTS
        if "/GO-VAR-22-10-14/electricity-tariffs/E-1R-GO-VAR-22-10-14-F/standing-charges/" in url:
            return _GO_STANDING
        if "/FLUX-IMPORT-23-02-14/electricity-tariffs/E-1R-FLUX-IMPORT-23-02-14-F/standing-charges/" in url:
            return _FLUX_STANDING
        raise AssertionError(f"unexpected URL {url}")

    def _log(self, msg, level="INFO"):
        self.logs.append((level, msg))

    def _fetch(self, now=1_000_000.0, **kw):
        return op.standing_charges_by_day(self.db, "F", date(2026, 4, 30), date(2026, 5, 1),
                                          names=kw.pop("names", self.NAMES),
                                          log_fn=self._log, now=now, **kw)

    def test_parses_and_picks_the_charge_valid_for_each_day(self):
        op._api_get = self._answer
        got = self._fetch()
        # Go went up at midnight on 1 May (23:00Z on 30 April in BST)
        self.assertEqual(got["go"], {"2026-04-30": 61.51824, "2026-05-01": 63.21819})
        # Flux: the direct-debit figure, not the dearer other one
        self.assertEqual(got["flux"], {"2026-04-30": 61.51824, "2026-05-01": 61.51824})
        self.assertFalse([m for lvl, m in self.logs if lvl == "WARNING"])

    def test_saved_figures_are_used_for_a_day_without_asking_again(self):
        op._api_get = self._answer
        first = self._fetch(now=1_000_000.0)

        def no_network(url):
            raise AssertionError("fetched again within a day")
        op._api_get = no_network
        self.assertEqual(self._fetch(now=1_000_000.0 + 3600), first)

    def test_failed_fetch_falls_back_with_one_warning_per_tariff(self):
        def down(url):
            raise OSError("network down")
        op._api_get = down
        got = self._fetch()
        self.assertEqual(got, {})        # the caller's own figures stand
        warnings = [m for lvl, m in self.logs if lvl == "WARNING"]
        self.assertEqual(len(warnings), 2)
        self.assertTrue(any("Octopus Go standing charge" in w for w in warnings))
        self.assertTrue(any("Octopus Flux Import standing charge" in w for w in warnings))
        self.assertTrue(all("network down" in w and "plugin's own figure" in w for w in warnings))

    def test_a_tariff_octopus_does_not_sell_is_named_in_the_warning(self):
        op._api_get = self._answer
        got = self._fetch(names={"withdrawn": "Octopus Go Faster", "go": "Octopus Go"})
        self.assertIn("go", got)
        self.assertNotIn("withdrawn", got)
        warnings = [m for lvl, m in self.logs if lvl == "WARNING"]
        self.assertEqual(len(warnings), 1)
        self.assertIn("Octopus Go Faster", warnings[0])

    def test_known_product_code_skips_the_lookup(self):
        op._api_get = self._answer
        got = self._fetch(names={}, products={"octopus_tracker": "GO-VAR-22-10-14"})
        self.assertEqual(got["octopus_tracker"]["2026-05-01"], 63.21819)
        self.assertFalse(any("/products/?" in u for u in self.urls))


class TestCollectorStandingCharges(unittest.TestCase):

    def _run(self, history, live):
        import json
        import shutil
        import sqlite3
        import tempfile
        d1, d2 = "2026-09-20", "2026-09-21"
        slots = [("03:00", 1.0), ("12:00", 1.0)]
        stubs = {
            "_fetch_tracker_rates":       lambda *a, **k: {},
            "_fetch_flux_rates":          lambda *a, **k: {},
            "_fetch_octopus_consumption": lambda api, mpan, *a, **k:
                {d1: slots, d2: slots} if mpan == "import" else {},
            "_fetch_octopus_gas":         lambda *a, **k: {d1: 10.0, d2: 10.0},
            "_aggregate_halfhourly":      lambda *a, **k: {d: {
                "pv_kwh": 0.0, "home_kwh": 2.0, "imp_kwh": 2.0, "exp_kwh": 0.0,
                "bat_chg": 0.0, "bat_dis": 0.0, "tracker_avg_p": 20.0} for d in (d1, d2)},
        }
        saved = {k: getattr(dc, k) for k in stubs}
        for k, v in stubs.items():
            setattr(dc, k, v)
        tmp = tempfile.mkdtemp()
        try:
            ts = os.path.join(tmp, "energy_timeseries.db")
            with open(os.path.join(tmp, "daily_history.json"), "w", encoding="utf-8") as fh:
                json.dump(history, fh)
            db = os.path.join(tmp, "summary.db")
            dc.update_daily_summary(db, date(2026, 9, 20), date(2026, 9, 21),
                                    {"region": "F", "api_key": "k", "mpan": "import",
                                     "serial": "s", "timeseries_db": ts,
                                     "live_standing": live})
            con = sqlite3.connect(db)
            con.row_factory = sqlite3.Row
            rows = {r["date"]: dict(r) for r in con.execute("SELECT * FROM daily_summary")}
            con.close()
            return rows
        finally:
            for k, v in saved.items():
                setattr(dc, k, v)
            shutil.rmtree(tmp, ignore_errors=True)

    def test_recorded_and_live_figures_used_and_missing_day_falls_back(self):
        rows = self._run(
            [{"date": "2026-09-20", "elec_standing_p_day": 60.0, "gas_standing_p_day": 30.0},
             {"date": "2026-09-21"}],                               # no standing recorded
            {"go": {"2026-09-20": 70.0}, "flux": {"2026-09-20": 50.0}})
        day1, day2 = rows["2026-09-20"], rows["2026-09-21"]
        # day 1: what was paid, and Octopus's Go and Flux figures
        self.assertAlmostEqual(day1["elec_standing_charge_gbp"], 0.60, places=4)
        self.assertAlmostEqual(day1["elec_total_gbp"], (2 * 20.0 + 60.0) / 100, places=4)
        self.assertAlmostEqual(day1["gas_standing_charge_gbp"], 0.30, places=4)
        # Go: 7.5 + 24 = 31.5p of energy. Saving = (40 + 60) - (31.5 + 70)
        self.assertAlmostEqual(day1["go_saving_vs_tracker_gbp"], -0.015, places=4)
        # Flux: 7.01 + 21 = 28.01p. Saving = (40 + 60) - (28.01 + 50)
        self.assertAlmostEqual(day1["flux_saving_vs_tracker_gbp"], 0.2199, places=4)
        # day 2: nothing recorded, no Octopus figure -> the constants
        self.assertAlmostEqual(day2["elec_standing_charge_gbp"],
                               round(dc.ELEC_STANDING_P_DAY / 100, 4), places=4)
        self.assertAlmostEqual(day2["gas_standing_charge_gbp"],
                               round(dc.GAS_STANDING_P_DAY / 100, 4), places=4)
        self.assertAlmostEqual(
            day2["go_saving_vs_tracker_gbp"],
            round(((40 + dc.ELEC_STANDING_P_DAY) - (31.5 + dc.GO_STANDING_P_DAY)) / 100, 4),
            places=4)

    def test_fallback_constants_are_octopus_region_f_figures(self):
        self.assertEqual(dc.GO_STANDING_P_DAY, 63.21819)
        self.assertEqual(dc.FLUX_STANDING_P_DAY, 61.51824)

if __name__ == "__main__":
    unittest.main(verbosity=2)
