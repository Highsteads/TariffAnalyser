#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_pricing.py
# Description: Tests for the v1.12 pricing fixes: Octopus unit prices fetched
#              for Flux, Go, Cosy and Economy 7 (with the plugin's own figures
#              only as the fallback), Flux Export and the export prices the
#              house really had, pricing by OVERLAP with the price periods
#              (TA-01), a real 0p price kept (TA-02), and battery provenance in
#              the savings summary (TA-R1). No network, no Indigo.
# Author:      CliveS & Claude Opus 5.5
# Date:        05-10-2026
# Version:     1.0
#
# Run:  python3 -m pytest test_pricing.py -q

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

os.environ["TZ"] = "Europe/London"
try:
    time.tzset()
except AttributeError:
    pass

import tariff_engine as te       # noqa: E402
import octopus_prices as op      # noqa: E402
import report_generator as rg    # noqa: E402

UK = ZoneInfo("Europe/London")


def _epoch(ts):
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UK).timestamp()


def _make_ts(tmp, rows, battery_cols=False):
    """rows: (slot_start, slot_end, imp, exp, pv, home, soc_s, soc_e, net, price)
    plus (chg, dis) when battery_cols."""
    path = os.path.join(tmp, "energy_timeseries.db")
    con = sqlite3.connect(path)
    extra = ", battery_charge_kwh REAL, battery_discharge_kwh REAL" if battery_cols else ""
    con.execute(f"""CREATE TABLE halfhourly (
        slot_start TEXT, slot_end TEXT, grid_import_kwh REAL, grid_export_kwh REAL,
        pv_kwh REAL, home_kwh REAL, battery_soc_start_pct REAL, battery_soc_end_pct REAL,
        battery_net_kwh REAL, tracker_price_p REAL, manager_action TEXT{extra})""")
    for r in rows:
        if battery_cols:
            con.execute("INSERT INTO halfhourly VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        tuple(r[:10]) + ("",) + tuple(r[10:12]))
        else:
            con.execute("INSERT INTO halfhourly VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        tuple(r[:10]) + ("",))
    con.commit()
    con.close()
    return path


def _make_agile(tmp, imports=None, exports=None):
    path = os.path.join(tmp, "agile.db")
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE agile_import (slot_start TEXT, region TEXT, price_p REAL, PRIMARY KEY(slot_start,region))")
    con.execute("CREATE TABLE agile_export (slot_start TEXT, region TEXT, price_p REAL, PRIMARY KEY(slot_start,region))")
    for s, p in (imports or {}).items():
        con.execute("INSERT INTO agile_import VALUES (?,?,?)", (s, "F", p))
    for s, p in (exports or {}).items():
        con.execute("INSERT INTO agile_export VALUES (?,?,?)", (s, "F", p))
    con.commit()
    con.close()
    return path


def _row(start, end, imp=1.0, exp=0.0, pv=0.0, home=1.0, price=20.0):
    return (start, end, imp, exp, pv, home, 50, 50, 0.0, price)


def _flux_periods(day, off=13.9223, mid=23.1946, peak=32.4761):
    """Octopus's Flux import periods for one BST day, in epoch seconds."""
    d = day
    return [
        (_epoch(f"{d}T00:00:00"), _epoch(f"{d}T02:00:00"), mid),
        (_epoch(f"{d}T02:00:00"), _epoch(f"{d}T05:00:00"), off),
        (_epoch(f"{d}T05:00:00"), _epoch(f"{d}T16:00:00"), mid),
        (_epoch(f"{d}T16:00:00"), _epoch(f"{d}T19:00:00"), peak),
        (_epoch(f"{d}T19:00:00"), _epoch(f"{d}T23:59:59") + 1, mid),
    ]


class _TmpCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# 1. Flux / Go / Cosy / E7 unit prices
# ---------------------------------------------------------------------------

class TestFallbackTables(unittest.TestCase):

    def test_flux_fallback_is_octopus_region_f_not_the_old_7p(self):
        flux = te.IMPORT_TARIFFS["flux"]
        rate = te._import_rate_for_slot
        self.assertAlmostEqual(rate("2026-10-05T03:00:00", flux, {}), 13.9223)
        self.assertAlmostEqual(rate("2026-10-05T12:00:00", flux, {}), 23.1946)
        self.assertAlmostEqual(rate("2026-10-05T17:00:00", flux, {}), 32.4761)

    def test_cosy_has_its_late_evening_cheap_window(self):
        cosy = te.IMPORT_TARIFFS["cosy"]
        rate = te._import_rate_for_slot
        cheap = rate("2026-10-05T05:00:00", cosy, {})
        self.assertEqual(rate("2026-10-05T22:30:00", cosy, {}), cheap)
        self.assertEqual(rate("2026-10-05T23:30:00", cosy, {}), cheap)
        self.assertNotEqual(rate("2026-10-05T21:30:00", cosy, {}), cheap)

    def test_octopus_fallback_figures_are_dated(self):
        self.assertEqual(te.OCTOPUS_RATES_UPDATED, "2026-10-05")


class TestLiveUnitRatesInComparison(_TmpCase):

    def _run(self, live_rates):
        rows = [_row(f"2026-10-05T{h:02d}:{m:02d}:00", f"2026-10-05T{h:02d}:{m + 30 - 1:02d}:59")
                for h in range(24) for m in (0, 30)]
        ts = _make_ts(self.tmp, rows)
        ag = _make_agile(self.tmp)
        return te.run_comparison(ts, ag, "F", date(2026, 10, 5), date(2026, 10, 5),
                                 import_tariff_keys=["tracker", "flux"],
                                 export_tariff_key="outgoing_12p",
                                 recorded_standing={}, recorded_export={},
                                 live_rates=live_rates)

    def test_flux_row_uses_octopus_prices_when_fetched(self):
        live = {"flux": {"standard": _flux_periods("2026-10-05", off=10.0, mid=20.0, peak=30.0)}}
        r = self._run(live)
        flux = next(x for x in r["results"] if x["tariff_key"] == "flux")
        # 1 kWh every half-hour: 6 off-peak, 6 peak, 36 mid
        self.assertAlmostEqual(flux["import_cost_p"], 6 * 10 + 6 * 30 + 36 * 20, places=2)
        self.assertEqual(r["rate_sources"]["flux"], {"octopus": 48})

    def test_flux_falls_back_to_dated_table_and_says_so(self):
        r = self._run({})
        flux = next(x for x in r["results"] if x["tariff_key"] == "flux")
        self.assertAlmostEqual(flux["import_cost_p"],
                               6 * 13.9223 + 6 * 32.4761 + 36 * 23.1946, places=2)
        self.assertEqual(r["rate_sources"]["flux"], {"table": 48})
        notes = " ".join(rg.rate_notes(r))
        self.assertIn("5 Oct 2026", notes)
        self.assertIn("Octopus Flux", notes)


class TestUnitRateFetch(unittest.TestCase):

    PRODUCTS = {"results": [
        {"code": "FLUX-IMPORT-23-02-14", "display_name": "Octopus Flux Import",
         "direction": "IMPORT", "available_from": "2023-02-14T00:00:00Z"},
        {"code": "FLUX-EXPORT-23-02-14", "display_name": "Octopus Flux Export",
         "direction": "EXPORT", "available_from": "2023-02-14T00:00:00Z"},
        {"code": "INTELLI-FLUX-IMPORT-23-07-14", "display_name": "Intelligent Octopus Flux Import",
         "direction": "IMPORT", "available_from": "2023-07-13T00:00:00Z"},
        {"code": "VAR-22-11-01", "display_name": "Flexible Octopus",
         "direction": "IMPORT", "available_from": "2023-03-28T00:00:00Z"},
    ], "next": None}

    FLUX_RATES = {"results": [
        {"valid_from": "2026-10-05T15:00:00Z", "valid_to": "2026-10-05T18:00:00Z", "value_inc_vat": 32.4761},
        {"valid_from": "2026-10-05T04:00:00Z", "valid_to": "2026-10-05T15:00:00Z", "value_inc_vat": 23.1946},
        {"valid_from": "2026-10-05T01:00:00Z", "valid_to": "2026-10-05T04:00:00Z", "value_inc_vat": 13.9223},
    ], "next": None}

    EXPORT_RATES = {"results": [
        {"valid_from": "2026-10-05T15:00:00Z", "valid_to": "2026-10-05T18:00:00Z", "value_inc_vat": 27.6905},
    ], "next": None}

    NIGHT = {"results": [
        {"valid_from": "2026-09-30T23:00:00Z", "valid_to": None, "value_inc_vat": 13.7229,
         "payment_method": "DIRECT_DEBIT"},
        {"valid_from": "2026-09-30T23:00:00Z", "valid_to": None, "value_inc_vat": 14.4902,
         "payment_method": "NON_DIRECT_DEBIT"},
    ], "next": None}
    DAY = {"results": [
        {"valid_from": "2026-09-30T23:00:00Z", "valid_to": None, "value_inc_vat": 31.6458,
         "payment_method": "DIRECT_DEBIT"},
    ], "next": None}

    SPECS = {
        "flux":        {"octopus_name": "Octopus Flux Import", "direction": "IMPORT"},
        "flux_export": {"octopus_name": "Octopus Flux Export", "direction": "EXPORT"},
        "economy7":    {"octopus_name": "Flexible Octopus", "direction": "IMPORT", "two_rate": True},
    }

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "agile_prices.db")
        self.urls, self.logs = [], []
        self._saved = op._api_get

    def tearDown(self):
        op._api_get = self._saved
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _answer(self, url):
        self.urls.append(url)
        if "/products/?" in url:
            return self.PRODUCTS
        if "E-1R-FLUX-IMPORT-23-02-14-F/standard-unit-rates/" in url:
            return self.FLUX_RATES
        if "E-1R-FLUX-EXPORT-23-02-14-F/standard-unit-rates/" in url:
            return self.EXPORT_RATES
        if "E-2R-VAR-22-11-01-F/night-unit-rates/" in url:
            return self.NIGHT
        if "E-2R-VAR-22-11-01-F/day-unit-rates/" in url:
            return self.DAY
        raise AssertionError(f"unexpected URL {url}")

    def _log(self, msg, level="INFO"):
        self.logs.append((level, msg))

    def _fetch(self, now=2_000_000_000.0):
        return op.unit_rates(self.db, "F", date(2026, 10, 5), date(2026, 10, 5),
                             specs=self.SPECS, log_fn=self._log, now=now)

    def test_found_by_exact_name_and_direction_and_saved(self):
        op._api_get = self._answer
        got = self._fetch()
        peak = [p for p in got["flux"]["standard"] if p[2] == 32.4761]
        self.assertEqual(peak[0][0], _epoch("2026-10-05T16:00:00"))
        self.assertEqual(got["flux_export"]["standard"][0][2], 27.6905)
        # the direct-debit figure for each Economy 7 register
        self.assertEqual([p[2] for p in got["economy7"]["night"]], [13.7229])
        self.assertEqual([p[2] for p in got["economy7"]["day"]], [31.6458])
        self.assertFalse(any("INTELLI" in u for u in self.urls))
        self.assertFalse([m for lvl, m in self.logs if lvl == "WARNING"])

    def test_saved_prices_reused_within_a_day(self):
        op._api_get = self._answer
        first = self._fetch()

        def no_network(url):
            raise AssertionError("fetched again within a day")
        op._api_get = no_network
        self.assertEqual(self._fetch(now=2_000_000_000.0 + 3600), first)

    def test_failure_is_one_warning_per_tariff_and_nothing_invented(self):
        def down(url):
            raise OSError("network down")
        op._api_get = down
        got = self._fetch()
        self.assertEqual(got, {})
        warnings = [m for lvl, m in self.logs if lvl == "WARNING"]
        self.assertEqual(len(warnings), 3)
        self.assertTrue(all("network down" in w for w in warnings))


class TestEconomy7Live(_TmpCase):

    def test_e7_uses_the_two_register_prices_in_its_night_window(self):
        rows = [_row("2026-10-05T03:00:00", "2026-10-05T03:30:00"),
                _row("2026-10-05T12:00:00", "2026-10-05T12:30:00")]
        ts = _make_ts(self.tmp, rows)
        start = _epoch("2026-10-01T00:00:00")
        live = {"economy7": {"night": [(start, None, 13.0)], "day": [(start, None, 31.0)]}}
        r = te.run_comparison(ts, _make_agile(self.tmp), "F", date(2026, 10, 5), date(2026, 10, 5),
                              import_tariff_keys=["economy7"], recorded_standing={},
                              recorded_export={}, live_rates=live)
        e7 = r["results"][0]
        self.assertAlmostEqual(e7["import_cost_p"], 13.0 + 31.0, places=2)
        self.assertEqual(r["rate_sources"]["economy7"], {"octopus": 2})


# ---------------------------------------------------------------------------
# 2. Export
# ---------------------------------------------------------------------------

class TestExport(_TmpCase):

    def test_flux_export_exists_and_seg_is_not_called_an_ofgem_floor(self):
        self.assertIn("flux_export", te.EXPORT_TARIFFS)
        self.assertEqual(te.EXPORT_TARIFFS["flux_export"]["octopus_name"], "Octopus Flux Export")
        for key in ("seg_min", "seg_typical"):
            name = te.EXPORT_TARIFFS[key]["name"].lower()
            self.assertNotIn("floor", name)
            self.assertNotIn("minimum", name)
            self.assertIn("illustrative", name)

    def test_each_row_gets_the_export_price_it_would_really_have(self):
        # 1 kWh exported at 17:00 on a Flux day and at 17:00 the day before the switch
        rows = [_row("2026-09-16T17:00:00", "2026-09-16T17:30:00", imp=0.0, exp=1.0),
                _row("2026-09-18T17:00:00", "2026-09-18T17:30:00", imp=0.0, exp=1.0)]
        ts = _make_ts(self.tmp, rows)
        recorded_export = {"2026-09-16": 12.0, "2026-09-18": 25.0}
        r = te.run_comparison(ts, _make_agile(self.tmp), "F",
                              date(2026, 9, 16), date(2026, 9, 18),
                              import_tariff_keys=["tracker", "flux", "ofgem_cap"],
                              export_tariff_key="outgoing_12p",
                              recorded_standing={}, recorded_export=recorded_export,
                              live_rates={})
        by = {x["tariff_key"]: x for x in r["results"]}
        # actual row: the export price recorded for each day
        self.assertAlmostEqual(by["tracker"]["export_revenue_p"], 12.0 + 25.0, places=2)
        # Flux comes paired with Flux Export (table peak 27.6905 here, no fetch)
        self.assertAlmostEqual(by["flux"]["export_revenue_p"], 2 * 27.6905, places=2)
        # anything else: the export tariff chosen in the settings
        self.assertAlmostEqual(by["ofgem_cap"]["export_revenue_p"], 24.0, places=2)
        self.assertEqual(r["export_sources"]["tracker"], {"recorded": 2})

    def test_a_day_with_no_recorded_export_uses_the_chosen_tariff(self):
        rows = [_row("2026-09-16T17:00:00", "2026-09-16T17:30:00", imp=0.0, exp=1.0)]
        ts = _make_ts(self.tmp, rows)
        r = te.run_comparison(ts, _make_agile(self.tmp), "F",
                              date(2026, 9, 16), date(2026, 9, 16),
                              import_tariff_keys=["tracker"], export_tariff_key="seg_typical",
                              recorded_standing={}, recorded_export={}, live_rates={})
        self.assertAlmostEqual(r["results"][0]["export_revenue_p"], 7.5, places=2)
        self.assertEqual(r["export_sources"]["tracker"], {"chosen": 1})

    def test_recorded_export_read_from_daily_history(self):
        ts = os.path.join(self.tmp, "energy_timeseries.db")
        with open(os.path.join(self.tmp, "daily_history.json"), "w", encoding="utf-8") as fh:
            json.dump([{"date": "2026-09-16", "export_rate_p": 12.0},
                       {"date": "2026-09-18", "export_rate_p": 24.2095},
                       {"date": "2026-09-19"}], fh)
        got = te.load_recorded_export(te.recorded_standing_path(ts))
        self.assertEqual(got, {"2026-09-16": 12.0, "2026-09-18": 24.2095})


# ---------------------------------------------------------------------------
# 3. TA-01 — price by overlap with the price periods
# ---------------------------------------------------------------------------

class TestOverlapPricing(_TmpCase):

    def test_unaligned_agile_slot_priced_from_both_half_hours(self):
        # a real slot: 22:04:29 to 22:34:31 straddles the 22:00 and 22:30 prices
        rows = [_row("2026-10-05T22:04:29", "2026-10-05T22:34:31")]
        ts = _make_ts(self.tmp, rows)
        ag = _make_agile(self.tmp, {"2026-10-05T22:00:00": 10.0, "2026-10-05T22:30:00": 40.0})
        r = te.run_comparison(ts, ag, "F", date(2026, 10, 5), date(2026, 10, 5),
                              import_tariff_keys=["agile"], recorded_standing={},
                              recorded_export={}, live_rates={})
        agile = r["results"][0]
        self.assertFalse(agile["insufficient_data"])
        first = _epoch("2026-10-05T22:30:00") - _epoch("2026-10-05T22:04:29")
        second = _epoch("2026-10-05T22:34:31") - _epoch("2026-10-05T22:30:00")
        expected = (first * 10.0 + second * 40.0) / (first + second)
        self.assertAlmostEqual(agile["import_cost_p"], expected, places=2)

    def test_slot_starting_before_the_peak_is_mostly_peak(self):
        # 15:56 to 16:26: 4 minutes at the day rate, 26 minutes at peak. Priced
        # from its start alone it was all day rate.
        rows = [_row("2026-10-05T15:56:00", "2026-10-05T16:26:00")]
        ts = _make_ts(self.tmp, rows)
        r = te.run_comparison(ts, _make_agile(self.tmp), "F", date(2026, 10, 5), date(2026, 10, 5),
                              import_tariff_keys=["flux"], recorded_standing={},
                              recorded_export={}, live_rates={})
        flux = r["results"][0]
        expected = (4 * 23.1946 + 26 * 32.4761) / 30
        self.assertAlmostEqual(flux["import_cost_p"], expected, places=2)

    def test_missing_agile_outgoing_price_is_missing_not_zero(self):
        rows = [_row("2026-10-05T12:00:00", "2026-10-05T12:30:00", exp=1.0),
                _row("2026-10-05T12:30:00", "2026-10-05T13:00:00", exp=1.0)]
        ts = _make_ts(self.tmp, rows)
        ag = _make_agile(self.tmp, exports={"2026-10-05T12:00:00": 15.0})
        r = te.run_comparison(ts, ag, "F", date(2026, 10, 5), date(2026, 10, 5),
                              import_tariff_keys=["ofgem_cap"], export_tariff_key="agile_outgoing",
                              recorded_standing={}, recorded_export={}, live_rates={})
        ofgem = r["results"][0]
        # the slot with no export price is left out, not credited at 0p
        self.assertEqual(r["common_slots"], 1)
        self.assertAlmostEqual(ofgem["export_revenue_p"], 15.0, places=2)
        self.assertAlmostEqual(ofgem["own_coverage_pct"], 50.0, places=1)


# ---------------------------------------------------------------------------
# 4. TA-02 — a real 0p price is a price
# ---------------------------------------------------------------------------

class TestZeroPrice(_TmpCase):

    def test_zero_pence_recorded_price_is_not_replaced_by_24_5(self):
        rows = [_row("2026-07-01T12:00:00", "2026-07-01T12:30:00",
                     imp=0.0, home=1.0, pv=1.0, price=0.0)]
        ts = _make_ts(self.tmp, rows)
        s = te.calculate_savings(ts, 12.0, date(2026, 7, 1), date(2026, 7, 1),
                                 recorded_export={})
        self.assertAlmostEqual(s["cost_without_solar_p"], 0.0, places=4)
        self.assertAlmostEqual(s["total_savings_p"], 0.0, places=4)


# ---------------------------------------------------------------------------
# 5. TA-R1 — grid-charged battery energy is time-shifting, not solar
# ---------------------------------------------------------------------------

class TestBatteryProvenance(_TmpCase):

    def _rows(self):
        # Battery 10 kWh a 100% (0.1 kWh per %). Night: 5 kWh charged from the
        # grid at 10p. Midday: 2 kWh of solar beyond the house charges it.
        # Evening: 7 kWh discharged to the house at 30p, no solar.
        R = []
        R.append(("2026-07-01T02:00:00", "2026-07-01T02:30:00",
                  5.0, 0.0, 0.0, 0.0, 0.0, 50.0, 5.0, 10.0, 5.0, 0.0))
        R.append(("2026-07-01T12:00:00", "2026-07-01T12:30:00",
                  0.0, 0.0, 3.0, 1.0, 50.0, 70.0, 2.0, 30.0, 2.0, 0.0))
        R.append(("2026-07-01T18:00:00", "2026-07-01T18:30:00",
                  0.0, 0.0, 0.0, 7.0, 70.0, 0.0, -7.0, 30.0, 0.0, 7.0))
        return R

    def test_only_the_solar_share_counts_as_solar_and_the_rest_is_shown(self):
        ts = _make_ts(self.tmp, self._rows(), battery_cols=True)
        s = te.calculate_savings(ts, 12.0, date(2026, 7, 1), date(2026, 7, 1),
                                 recorded_export={})
        # without solar: 8 kWh at the house, 7 of it at 30p and 1 at 30p = 240p
        self.assertAlmostEqual(s["cost_without_solar_p"], 8 * 30.0, places=2)
        # with: 5 kWh imported at 10p = 50p
        self.assertAlmostEqual(s["cost_with_solar_p"], 50.0, places=2)
        # the headline agrees with without minus with
        self.assertAlmostEqual(s["total_savings_p"],
                               s["cost_without_solar_p"] - s["cost_with_solar_p"], places=2)
        # The battery held 5 kWh grid + 2 kWh solar: 5/7 of the evening's 7 kWh
        # came from the grid. Solar: 1 kWh direct + 2 kWh via the battery = 90p.
        self.assertAlmostEqual(s["avoided_import_p"], 3 * 30.0, places=1)
        # time-shifting: 5 kWh used at 30p, bought at 10p = 100p
        self.assertAlmostEqual(s["timeshift_p"], 5 * 30.0 - 5 * 10.0, places=1)
        self.assertAlmostEqual(s["grid_charged_kwh"], 5.0, places=2)
        self.assertAlmostEqual(s["avoided_import_p"] + s["solar_export_p"] + s["timeshift_p"],
                               s["total_savings_p"], places=2)

    def test_summary_page_shows_time_shifting_and_agrees_with_itself(self):
        ts = _make_ts(self.tmp, self._rows(), battery_cols=True)
        s = te.calculate_savings(ts, 12.0, date(2026, 7, 1), date(2026, 7, 1),
                                 recorded_export={})
        html = rg.savings_card_html("Today", date(2026, 7, 1), date(2026, 7, 1), s)
        self.assertIn("charged from the grid", html)
        self.assertIn("£1.90", html)    # 240 - 50 = 190p total saved
        self.assertIn("£1.00", html)    # time-shifting


# ---------------------------------------------------------------------------
# get_coverage must not read the whole table
# ---------------------------------------------------------------------------

class TestCoverageQueries(_TmpCase):

    def test_agile_coverage_searches_the_index(self):
        db = os.path.join(self.tmp, "agile_prices.db")
        op.init_agile_db(db)
        plans = []
        real = sqlite3.connect

        class _Con:
            def __init__(self, *a, **k):
                self._c = real(*a, **k)

            def execute(self, sql, params=()):
                plans.extend(r[3] for r in self._c.execute("EXPLAIN QUERY PLAN " + sql, params))
                return self._c.execute(sql, params)

            def close(self):
                self._c.close()
        op.sqlite3.connect = _Con
        try:
            op.get_coverage(db, "F")
        finally:
            op.sqlite3.connect = real
        self.assertTrue(plans)
        self.assertFalse([p for p in plans if p.startswith("SCAN agile_")], plans)


if __name__ == "__main__":
    unittest.main(verbosity=2)
