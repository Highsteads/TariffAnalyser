#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_report_generator.py
# Description: Tests for the report headers — the export tariff is named with
#              its real price, and the recorded-prices row is not called
#              Tracker when the data is another tariff.
# Author:      CliveS & Claude Opus 5.5
# Date:        27-09-2026
# Version:     1.0
#
# Run:  python3 -m pytest test_report_generator.py -q

import os
import shutil
import sys
import tempfile
import unittest
from datetime import date

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import report_generator as rg    # noqa: E402
import tariff_engine as te       # noqa: E402


class TestFormatPence(unittest.TestCase):

    def test_whole_and_fractional_prices(self):
        self.assertEqual(rg.format_pence(12.0), "12p")
        self.assertEqual(rg.format_pence(7.5), "7.5p")
        self.assertEqual(rg.format_pence(1.63), "1.63p")

    def test_export_label(self):
        seg = te.EXPORT_TARIFFS["seg_min"]
        self.assertEqual(rg.export_tariff_label(seg["name"], seg["rate_p"]),
                         "SEG Minimum (Ofgem floor) at 1.63p")
        out = te.EXPORT_TARIFFS["outgoing_12p"]
        self.assertEqual(rg.export_tariff_label(out["name"], out["rate_p"]),
                         "Octopus Outgoing 12p (actual)")
        agile = rg.export_tariff_label("Octopus Agile Outgoing", 12.0, flat_rate_known=False)
        self.assertIn("Octopus Agile Outgoing", agile)
        self.assertIn("12p", agile)


class TestSavingsSummaryHeader(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _html(self, **kw):
        path, err = rg.generate_savings_summary(
            os.path.join(self.tmp, "missing.db"), self.tmp, **kw)
        self.assertIsNone(err)
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_seg_minimum_is_named_and_not_rounded(self):
        seg = te.EXPORT_TARIFFS["seg_min"]
        html = self._html(export_rate_p=seg["rate_p"],
                          export_label=rg.export_tariff_label(seg["name"], seg["rate_p"]))
        self.assertIn("Export tariff: SEG Minimum (Ofgem floor) at 1.63p", html)
        self.assertNotIn("Octopus Outgoing", html)
        self.assertNotIn("Outgoing 2p", html)

    def test_default_header_keeps_the_real_price(self):
        html = self._html(export_rate_p=1.63)
        self.assertIn("1.63p", html)
        self.assertNotIn("Octopus Outgoing 2p", html)

    def test_tariff_label_and_note_replace_tracker(self):
        html = self._html(export_rate_p=12.0, tariff_label="Octopus Flux (actual)",
                          tariff_note="Your tariff changed during this period.")
        self.assertIn("Octopus Flux (actual)", html)
        self.assertIn("Your tariff changed during this period.", html)
        self.assertNotIn("Tracker", html)


class TestComparisonReportLabels(unittest.TestCase):

    def test_vs_column_and_note_follow_the_recorded_tariff(self):
        tmp = tempfile.mkdtemp()
        try:
            row = {"tariff_key": "tracker", "tariff_name": "Octopus Flux (actual)",
                   "import_cost_p": 100.0, "export_revenue_p": 10.0,
                   "standing_charge_p": 53.0, "total_cost_p": 143.0,
                   "coverage_pct": 100.0, "own_coverage_pct": 100.0,
                   "insufficient_data": False}
            comp = {"results": [row], "monthly": {}, "raw_totals": {}, "slots": 48,
                    "days": 1, "coverage_pct": 100.0,
                    "recorded_tariff_label": "Octopus Flux (actual)",
                    "recorded_tariff_note": ""}
            path, err = rg.generate_report(comp, date(2026, 9, 20), date(2026, 9, 20),
                                           tmp, "Octopus Outgoing 12p (actual)")
            self.assertIsNone(err)
            with open(path, encoding="utf-8") as fh:
                html = fh.read()
            self.assertIn("<th>vs actual</th>", html)
            self.assertNotIn("Tracker", html)
            self.assertNotIn("Intelligent Go", html)
            self.assertIn("the prices you actually paid (Octopus Flux (actual))", html)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)



class TestStandingNotes(unittest.TestCase):

    def _comp(self, sources, fallback=(), live_name=""):
        results = [{"tariff_key": k, "tariff_name": te.IMPORT_TARIFFS[k]["name"],
                    "insufficient_data": False} for k in sources]
        results[0]["tariff_name"] = "Octopus Flux (actual)"
        return {"results": results, "standing_sources": sources,
                "recorded_standing_fallback_days": list(fallback),
                "recorded_standing_live_name": live_name}

    def test_notes_say_where_each_figure_came_from(self):
        comp = self._comp({"tracker": ["octopus", "recorded"], "go": ["octopus"],
                           "flux": ["octopus"], "agile": ["table"],
                           "ofgem_cap": ["table"]},
                          fallback=["2026-06-03", "2026-06-04"], live_name="Octopus Flux")
        notes = rg.standing_notes(comp, "Octopus Flux (actual)")
        text = " ".join(notes)
        self.assertIn("uses the standing charge SigenEnergyManager recorded for each day", text)
        self.assertIn("It recorded none for 3 Jun to 4 Jun, so those days use "
                      "Octopus's published figure for Octopus Flux.", text)
        self.assertIn("Octopus Go and Octopus Flux use the standing charge Octopus "
                      "publishes for your region.", text)
        self.assertIn("Octopus Agile uses the plugin's own standing charge", text)
        self.assertIn("Ofgem Price Cap (SVT) uses a typical standing charge last checked", text)
        self.assertNotIn("may differ", text)
        self.assertNotIn(";", text)

    def test_report_carries_the_notes_not_the_old_line(self):
        tmp = tempfile.mkdtemp()
        try:
            comp = self._comp({"tracker": ["recorded"]})
            comp["results"][0].update({"import_cost_p": 100.0, "export_revenue_p": 0.0,
                                       "standing_charge_p": 61.5, "total_cost_p": 161.5,
                                       "coverage_pct": 100.0, "own_coverage_pct": 100.0})
            comp.update({"monthly": {}, "raw_totals": {}, "slots": 48, "days": 1,
                         "coverage_pct": 100.0,
                         "recorded_tariff_label": "Octopus Flux (actual)",
                         "recorded_tariff_note": ""})
            path, err = rg.generate_report(comp, date(2026, 9, 20), date(2026, 9, 20),
                                           tmp, "Octopus Outgoing 12p (actual)")
            self.assertIsNone(err)
            with open(path, encoding="utf-8") as fh:
                html = fh.read()
            self.assertNotIn("Standing charges use published rates and may differ", html)
            self.assertIn("<li>Octopus Flux (actual) uses the standing charge "
                          "SigenEnergyManager recorded for each day, which is what you paid.</li>",
                          html)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

if __name__ == "__main__":
    unittest.main(verbosity=2)
