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
        # an overnight window 23:30-05:30 wraps midnight
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
        # BOTH priced over 24 kWh: agile 24x5=120 + 70.04823*(24/48)=35.02 -> 155.02
        # (Agile's table standing charge, used with no live Octopus figure)
        self.assertAlmostEqual(by["agile"]["import_cost_p"], 120.0, places=1)
        self.assertAlmostEqual(by["agile"]["total_cost_p"], 155.02, places=1)
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


# ---------------------------------------------------------------------------
# v1.10 — the recorded-prices row is named from the data, not "Tracker"
# ---------------------------------------------------------------------------

def _flat_day(day, price=24.0):
    return [(f"{day}T{h:02d}:{m:02d}:00", 1.0, 0.0, 0.0, 1.0, price)
            for h in range(24) for m in (0, 30)]


def _flux_day(day):
    out = []
    for h in range(24):
        for m in (0, 30):
            if 2 <= h < 5:
                p = 14.6184
            elif 16 <= h < 19:
                p = 34.0999
            else:
                p = 24.3543
            out.append((f"{day}T{h:02d}:{m:02d}:00", 1.0, 0.0, 0.0, 1.0, p))
    return out


def _prices(rows):
    return te._day_price_counts([(r[0], None, r[1], r[2], r[3], r[4], 0, 0, 0, r[5], "")
                                 for r in rows])


class TestRecordedTariffLabel(unittest.TestCase):

    def test_flat_prices_named_tracker(self):
        label, note = te.recorded_tariff_label(_prices(_flat_day("2026-08-01")), "Octopus Tracker")
        self.assertEqual(label, "Octopus Tracker (actual)")
        self.assertEqual(note, "")

    def test_flux_bands_named_flux_not_tracker(self):
        label, note = te.recorded_tariff_label(_prices(_flux_day("2026-09-20")), "Octopus Flux")
        self.assertEqual(label, "Octopus Flux (actual)")
        self.assertNotIn("Tracker", label)

    def test_name_that_does_not_fit_the_data_is_not_used(self):
        # Flat Tracker-shaped prices while the monitor now says Flux: the
        # period predates the switch, so "Flux" would be wrong.
        label, _ = te.recorded_tariff_label(_prices(_flat_day("2026-08-01")), "Octopus Flux")
        self.assertEqual(label, te.GENERIC_RECORDED_NAME)

    def test_tariff_change_in_period_is_mixed_with_a_note(self):
        rows = _flat_day("2026-09-16") + _flat_day("2026-09-17", 25.0) + _flux_day("2026-09-18")
        label, note = te.recorded_tariff_label(_prices(rows), "Octopus Flux")
        self.assertNotIn("Tracker", label)
        self.assertIn("mixed", label)
        self.assertIn("one price a day to 17 Sep", note)
        self.assertIn("time-of-use bands (Octopus Flux) from 18 Sep", note)
        self.assertNotIn(";", note)

    def test_midnight_straggler_still_a_flat_day(self):
        rows = _flat_day("2026-09-06", 22.617)
        rows[0] = rows[0][:5] + (19.005,)      # yesterday's price in the first slot
        self.assertEqual(te._day_pattern(_prices(rows)["2026-09-06"]), "flat")

    def test_go_two_bands_is_time_of_use(self):
        rows = [(f"2026-09-01T{h:02d}:{m:02d}:00", 1.0, 0.0, 0.0, 1.0,
                 7.5 if 1 <= h < 5 else 24.0) for h in range(24) for m in (0, 30)]
        self.assertEqual(te._day_pattern(_prices(rows)["2026-09-01"]), "tou")

    def test_partial_day_is_not_classified(self):
        rows = _flux_day("2026-09-18") + _flat_day("2026-09-19")[:20]
        label, note = te.recorded_tariff_label(_prices(rows), "Octopus Flux")
        self.assertEqual(label, "Octopus Flux (actual)")
        self.assertEqual(note, "")

    def test_clean_tariff_name(self):
        self.assertEqual(te.clean_tariff_name("Octopus Flux (forced)"), "Octopus Flux")
        self.assertEqual(te.clean_tariff_name("Initialising"), "")
        self.assertEqual(te.clean_tariff_name(None), "")

    def test_run_comparison_names_the_row_from_the_data(self):
        tmp = tempfile.mkdtemp()
        try:
            ts = _make_timeseries(tmp, _flux_day("2026-09-20") + _flux_day("2026-09-21"))
            comp = te.run_comparison(ts, os.path.join(tmp, "none.db"), "F",
                                     date(2026, 9, 20), date(2026, 9, 21),
                                     import_tariff_keys=["tracker", "go"],
                                     current_tariff_name="Octopus Flux")
            row = next(r for r in comp["results"] if r["tariff_key"] == "tracker")
            self.assertEqual(row["tariff_name"], "Octopus Flux (actual)")
            self.assertEqual(comp["recorded_tariff_label"], "Octopus Flux (actual)")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)



# ---------------------------------------------------------------------------
# v1.11 — standing charges from the real figures
# ---------------------------------------------------------------------------

def _write_history(tmp, records):
    """SigenEnergyManager's daily_history.json beside the fixture's ts.db."""
    import json
    with open(os.path.join(tmp, te.DAILY_HISTORY_NAME), "w", encoding="utf-8") as fh:
        json.dump(records, fh)


class TestStandingCharges(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_recorded_standing_summed_per_day_and_pro_rated(self):
        d1, d2 = "2026-09-20", "2026-09-21"
        slots = _full_day(day=d1) + _full_day(day=d2)
        ts = _make_timeseries(self.tmp, slots)
        # Agile has prices for all of day 1 and half of day 2, so the common
        # set is 72 half-hours: one whole day and half of the next.
        ag = _make_agile(self.tmp, {s[0]: 10.0 for s in slots[:72]})
        _write_history(self.tmp, [
            {"date": d1, "elec_standing_p_day": 60.0},
            {"date": d2, "elec_standing_p_day": 62.0},
        ])
        r = te.run_comparison(ts, ag, "F", date(2026, 9, 20), date(2026, 9, 21),
                              import_tariff_keys=["tracker", "agile"],
                              live_standing={"agile": {d1: 70.0, d2: 72.0}})
        self.assertEqual(r["common_slots"], 72)
        by = {x["tariff_key"]: x for x in r["results"]}
        # recorded: 60 for day 1 + 62 x 24/48 for day 2 (not 61.64 x 1.5)
        self.assertAlmostEqual(by["tracker"]["standing_charge_p"], 91.0, places=2)
        # Octopus's figure for each day: 70 + 72 x 24/48 (not 53.35 or 70.05 x 1.5)
        self.assertAlmostEqual(by["agile"]["standing_charge_p"], 106.0, places=2)
        self.assertEqual(r["standing_sources"]["tracker"], ["recorded"])
        self.assertEqual(r["standing_sources"]["agile"], ["octopus"])
        self.assertEqual(r["recorded_standing_fallback_days"], [])

    def test_day_missing_the_field_falls_back_to_octopus_then_the_table(self):
        d1, d2 = "2026-09-20", "2026-09-21"
        ts = _make_timeseries(self.tmp, _flux_day(d1) + _flux_day(d2))
        _write_history(self.tmp, [
            {"date": d1, "elec_standing_p_day": 60.0},
            {"date": d2, "home_kwh": 20.0},            # an older record: no field
        ])
        kw = dict(import_tariff_keys=["tracker", "flux"], current_tariff_name="Octopus Flux")
        r = te.run_comparison(ts, os.path.join(self.tmp, "none.db"), "F",
                              date(2026, 9, 20), date(2026, 9, 21),
                              live_standing={"flux": {d1: 61.5, d2: 61.5}}, **kw)
        by = {x["tariff_key"]: x for x in r["results"]}
        # day 2 takes Octopus's Flux figure, the tariff the row is named after
        self.assertAlmostEqual(by["tracker"]["standing_charge_p"], 121.5, places=2)
        self.assertEqual(r["recorded_standing_fallback_days"], [d2])
        self.assertEqual(r["standing_sources"]["tracker"], ["octopus", "recorded"])
        self.assertEqual(r["recorded_standing_live_name"], "Octopus Flux")

        # With no Octopus figure the table value is the last resort.
        r = te.run_comparison(ts, os.path.join(self.tmp, "none.db"), "F",
                              date(2026, 9, 20), date(2026, 9, 21), **kw)
        by = {x["tariff_key"]: x for x in r["results"]}
        table = te.IMPORT_TARIFFS["tracker"]["standing_p_day"]
        self.assertAlmostEqual(by["tracker"]["standing_charge_p"], 60.0 + table, places=2)
        self.assertEqual(r["standing_sources"]["tracker"], ["recorded", "table"])
        flux_table = te.IMPORT_TARIFFS["flux"]["standing_p_day"]
        self.assertAlmostEqual(by["flux"]["standing_charge_p"], 2 * flux_table, places=2)

    def test_load_recorded_standing_skips_what_it_cannot_use(self):
        path = os.path.join(self.tmp, te.DAILY_HISTORY_NAME)
        self.assertEqual(te.load_recorded_standing(path), {})       # no file
        _write_history(self.tmp, [
            {"date": "2026-09-01", "elec_standing_p_day": 61.51824, "gas_standing_p_day": 29.06169},
            {"date": "2026-09-02", "elec_standing_p_day": None},
            {"date": "2026-09-03", "elec_standing_p_day": "n/a"},
            {"date": "2026-09-04", "elec_standing_p_day": 0},
            "not a record",
            {"elec_standing_p_day": 50.0},
        ])
        self.assertEqual(te.load_recorded_standing(path), {"2026-09-01": 61.51824})
        self.assertEqual(te.load_recorded_standing(path, "gas_standing_p_day"),
                         {"2026-09-01": 29.06169})
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        self.assertEqual(te.load_recorded_standing(path), {})
        self.assertEqual(te.recorded_standing_path(os.path.join(self.tmp, "energy_timeseries.db")),
                         path)

    def test_octopus_tariffs_no_longer_share_one_made_up_figure(self):
        for key in ("go", "agile", "cosy", "flux"):
            self.assertNotEqual(te.IMPORT_TARIFFS[key]["standing_p_day"], 53.35, key)
            self.assertTrue(te.IMPORT_TARIFFS[key]["octopus_name"], key)

    def test_live_standing_key(self):
        self.assertEqual(te.live_standing_key("Octopus Flux (forced)"), "flux")
        self.assertEqual(te.live_standing_key("Agile Octopus"), "agile")
        self.assertEqual(te.live_standing_key("Octopus Go"), "go")
        self.assertEqual(te.live_standing_key("Octopus Tracker"), te.TRACKER_LIVE_KEY)
        self.assertIsNone(te.live_standing_key("Intelligent Octopus Go"))
        self.assertIsNone(te.live_standing_key("EDF Fixed"))
        self.assertIsNone(te.live_standing_key(""))

    def test_go_faster_dropped_and_an_old_key_cannot_crash(self):
        self.assertNotIn("go_faster", te.IMPORT_TARIFFS)
        ts = _make_timeseries(self.tmp, _full_day())
        r = te.run_comparison(ts, os.path.join(self.tmp, "none.db"), "F",
                              date(2026, 7, 1), date(2026, 7, 1),
                              import_tariff_keys=["go_faster", "ofgem_cap"])
        self.assertEqual([x["tariff_key"] for x in r["results"]], ["ofgem_cap"])

    def test_format_day_ranges(self):
        self.assertEqual(te.format_day_ranges(["2026-06-03", "2026-06-04", "2026-06-05",
                                               "2026-06-09"]),
                         "3 Jun to 5 Jun and 9 Jun")
        self.assertEqual(te.format_day_ranges(["2026-06-03"]), "3 Jun")

if __name__ == "__main__":
    unittest.main(verbosity=2)
