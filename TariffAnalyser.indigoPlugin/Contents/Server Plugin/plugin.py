#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    plugin.py
# Description: TariffAnalyser - compares UK energy tariffs against recorded
#              half-hourly energy data from SigenEnergyManager.
#              Outputs CSV reports openable in LibreOffice or Numbers.
# Author:      CliveS & Claude Sonnet 4.6
# Date:        02-05-2026
# Version:     1.0

import indigo
import os
import sys
import time
from datetime import datetime, date, timedelta

sys.path.insert(0, os.getcwd())
try:
    from plugin_utils import log_startup_banner
except ImportError:
    log_startup_banner = None

import tariff_engine
import octopus_prices
import report_generator

PLUGIN_ID      = "com.clives.indigoplugin.tariffanalyser"
PLUGIN_NAME    = "Tariff Analyser"
PLUGIN_VERSION = "1.0"

# Shared Perceptive Automation folder — output goes here (not inside any Indigo version folder)
_PA_SHARED = "/Library/Application Support/Perceptive Automation"
OUTPUT_DIR = os.path.join(_PA_SHARED, "TariffAnalyser")

# Default path to SigenEnergyManager timeseries DB
_SIGEN_PREFS = os.path.join(
    indigo.server.getInstallFolderPath(),
    "Preferences", "Plugins",
    "com.clives.indigoplugin.sigenergy-energy-manager"
)
DEFAULT_DB_PATH = os.path.join(_SIGEN_PREFS, "energy_timeseries.db")

# Octopus region for North East England (Medomsley, County Durham)
DEFAULT_REGION = "F"


def log(message, level="INFO"):
    indigo.server.log(f"[{datetime.now().strftime('%H:%M:%S')}] {message}",
                      level=level)


class Plugin(indigo.PluginBase):

    def __init__(self, plugin_id, plugin_display_name, plugin_version, plugin_prefs):
        super().__init__(plugin_id, plugin_display_name, plugin_version, plugin_prefs)
        self.pluginId           = plugin_id
        self.pluginDisplayName  = plugin_display_name
        self.pluginVersion      = plugin_version

        self._last_report_path  = None   # path of most recently generated report

        if log_startup_banner:
            log_startup_banner(plugin_id, plugin_display_name, plugin_version, extras=[
                ("Timeseries DB:", self._db_path()),
                ("Agile DB:",      self._agile_db_path()),
                ("Output folder:", self._output_dir()),
                ("Region:",        self._region()),
            ])
        else:
            indigo.server.log(f"{plugin_display_name} v{plugin_version} starting")

    def startup(self):
        log(f"{PLUGIN_NAME} v{PLUGIN_VERSION} ready")
        os.makedirs(self._output_dir(), exist_ok=True)
        octopus_prices.init_agile_db(self._agile_db_path())

    def shutdown(self):
        log(f"{PLUGIN_NAME} shutting down")

    # ================================================================
    # Plugin prefs helpers
    # ================================================================

    def _db_path(self):
        configured = self.pluginPrefs.get("dbPath", "").strip()
        return configured if configured else DEFAULT_DB_PATH

    def _agile_db_path(self):
        prefs_dir = indigo.server.getInstallFolderPath()
        data_dir  = os.path.join(prefs_dir, "Preferences", "Plugins", PLUGIN_ID)
        os.makedirs(data_dir, exist_ok=True)
        return os.path.join(data_dir, "agile_prices.db")

    def _output_dir(self):
        configured = self.pluginPrefs.get("outputDir", "").strip()
        return configured if configured else OUTPUT_DIR

    def _region(self):
        return self.pluginPrefs.get("octopusRegion", DEFAULT_REGION)

    def _default_days(self):
        try:
            return int(self.pluginPrefs.get("defaultDays", "30"))
        except (ValueError, TypeError):
            return 30

    def _export_tariff_key(self):
        return self.pluginPrefs.get("exportTariffKey", "outgoing_12p")

    # ================================================================
    # Menu: Run Tariff Comparison (opens dialog)
    # ================================================================

    def runTariffComparison(self, valuesDict, typeId):
        errors = indigo.Dict()

        # Assemble dates from day/month/year dropdowns
        try:
            date_from = date(
                int(valuesDict.get("from_year", "2026")),
                int(valuesDict.get("from_month", "01")),
                int(valuesDict.get("from_day",   "01")),
            )
        except ValueError as exc:
            errors["from_day"] = f"Invalid from date: {exc}"
            return False, valuesDict, errors

        try:
            date_to = date(
                int(valuesDict.get("to_year",  "2026")),
                int(valuesDict.get("to_month", "05")),
                int(valuesDict.get("to_day",   "02")),
            )
        except ValueError as exc:
            errors["to_day"] = f"Invalid to date: {exc}"
            return False, valuesDict, errors

        if date_from > date_to:
            errors["from_day"] = "From date must be before To date"
            return False, valuesDict, errors

        db_path = self._db_path()
        if not os.path.exists(db_path):
            errors["from_day"] = (
                f"Timeseries DB not found. "
                f"Check SigenEnergyManager is running v4.6+ and data has been collected."
            )
            return False, valuesDict, errors

        # Check coverage so the error message can tell the user what dates are available
        earliest, latest, total_slots = tariff_engine.get_coverage(db_path)
        if not earliest:
            errors["from_day"] = (
                "No data in the timeseries DB yet. "
                "SigenEnergyManager v4.6+ must run for at least one 30-min cycle first."
            )
            return False, valuesDict, errors

        earliest_date = datetime.strptime(earliest, "%Y-%m-%dT%H:%M:%S").date()
        latest_date   = datetime.strptime(latest,   "%Y-%m-%dT%H:%M:%S").date()

        if date_to < earliest_date or date_from > latest_date:
            errors["from_day"] = (
                f"No data for that date range. "
                f"Available data: {earliest_date.strftime('%d/%m/%Y')} "
                f"to {latest_date.strftime('%d/%m/%Y')} "
                f"({total_slots} slots)."
            )
            return False, valuesDict, errors

        log(f"[Compare] Running comparison {date_from} to {date_to}")

        comparison = tariff_engine.run_comparison(
            timeseries_db_path = db_path,
            agile_db_path      = self._agile_db_path(),
            region             = self._region(),
            date_from          = date_from,
            date_to            = date_to,
            export_tariff_key  = self._export_tariff_key(),
        )

        slots = comparison.get("slots", 0)
        if slots == 0:
            errors["from_day"] = (
                f"No data for {date_from.strftime('%d/%m/%Y')} to {date_to.strftime('%d/%m/%Y')}. "
                f"Available: {earliest_date.strftime('%d/%m/%Y')} to {latest_date.strftime('%d/%m/%Y')}."
            )
            return False, valuesDict, errors

        export_name = tariff_engine.EXPORT_TARIFFS[self._export_tariff_key()]["name"]
        path, err = report_generator.generate_report(
            comparison, date_from, date_to, self._output_dir(), export_name
        )
        if err:
            log(f"[Compare] Report generation failed: {err}", level="ERROR")
            errors["from_day"] = f"Report generation failed: {err}"
            return False, valuesDict, errors

        self._last_report_path = path
        self._log_comparison_summary(comparison, date_from, date_to)

        open_now = valuesDict.get("openInLibreOffice", True)
        if open_now:
            report_generator.open_in_libreoffice(path, log_fn=log)

        log(f"[Compare] Report saved: {path}")
        return True, valuesDict, errors

    # ================================================================
    # Menu: Export Raw Data
    # ================================================================

    def exportRawData(self, valuesDict=None, typeId=None):
        db_path = self._db_path()
        if not os.path.exists(db_path):
            log(f"[Export] Timeseries DB not found: {db_path}", level="WARNING")
            return

        path, err = report_generator.export_raw_csv(
            db_path, self._output_dir(), log_fn=log
        )
        if err:
            log(f"[Export] Failed: {err}", level="ERROR")
        else:
            log(f"[Export] Raw CSV written: {path}")
            report_generator.open_in_libreoffice(path, log_fn=log)

    # ================================================================
    # Menu: Update Octopus Price Data
    # ================================================================

    def updatePriceData(self, valuesDict=None, typeId=None):
        days = self._default_days()
        date_to   = date.today()
        date_from = date_to - timedelta(days=days - 1)

        log(f"[Prices] Fetching Agile prices {date_from} to {date_to} "
            f"(region {self._region()})")
        try:
            imp, exp = octopus_prices.fetch_agile_prices(
                self._agile_db_path(),
                self._region(),
                date_from,
                date_to,
                log_fn=log,
            )
            log(f"[Prices] Complete - import: +{imp} rows, export: +{exp} rows")
        except Exception as exc:
            log(f"[Prices] Fetch failed: {exc}", level="ERROR")

    # ================================================================
    # Menu: Show Data Coverage
    # ================================================================

    def showDataCoverage(self, valuesDict=None, typeId=None):
        db_path = self._db_path()
        earliest, latest, count = tariff_engine.get_coverage(db_path)

        if not earliest:
            log("[Coverage] No timeseries data found yet. "
                "SigenEnergyManager must be running v4.6+ and collect at least one 30-min slot.",
                level="WARNING")
        else:
            days_held = (datetime.strptime(latest, "%Y-%m-%dT%H:%M:%S").date() -
                         datetime.strptime(earliest, "%Y-%m-%dT%H:%M:%S").date()).days + 1
            expected  = days_held * 48
            coverage  = count / expected * 100.0 if expected else 0.0
            log(f"[Coverage] Timeseries: {earliest[:10]} to {latest[:10]}")
            log(f"[Coverage] {count} slots over {days_held} days "
                f"({coverage:.0f}% of expected 48/day)")

        # Agile price coverage
        ai, al, ei, el = octopus_prices.get_coverage(
            self._agile_db_path(), self._region()
        )
        if ai:
            log(f"[Coverage] Agile import: {ai[:10]} to {al[:10]}")
        else:
            log("[Coverage] No Agile import prices cached yet. Run 'Update Octopus Price Data'.")

        if ei:
            log(f"[Coverage] Agile export: {ei[:10]} to {el[:10]}")
        else:
            log("[Coverage] No Agile export prices cached yet.")

    # ================================================================
    # Menu: Open Last Report
    # ================================================================

    def openLastReport(self, valuesDict=None, typeId=None):
        if not self._last_report_path or not os.path.exists(self._last_report_path):
            # Fall back to most recent file in output dir
            out_dir = self._output_dir()
            try:
                files = sorted(
                    [f for f in os.listdir(out_dir) if f.startswith("tariff_comparison")],
                    reverse=True
                )
                if files:
                    self._last_report_path = os.path.join(out_dir, files[0])
            except Exception:
                pass

        if self._last_report_path and os.path.exists(self._last_report_path):
            report_generator.open_in_libreoffice(self._last_report_path, log_fn=log)
        else:
            log("[Report] No report found. Run a tariff comparison first.", level="WARNING")

    # ================================================================
    # Menu: Show Plugin Info
    # ================================================================

    def showPluginInfo(self, valuesDict=None, typeId=None):
        if log_startup_banner:
            log_startup_banner(self.pluginId, self.pluginDisplayName,
                               self.pluginVersion, extras=[
                                   ("Timeseries DB:", self._db_path()),
                                   ("Agile DB:",      self._agile_db_path()),
                                   ("Output folder:", self._output_dir()),
                                   ("Region:",        self._region()),
                               ])
        else:
            log(f"{self.pluginDisplayName} v{self.pluginVersion}")

    # ================================================================
    # Actions (schedulable)
    # ================================================================

    def actionGenerateReport(self, action):
        """Action: Generate a monthly report. Schedulable via Indigo schedules."""
        days_str = action.props.get("reportDays", "30")
        try:
            days = int(days_str)
        except (ValueError, TypeError):
            days = 30

        date_to   = date.today() - timedelta(days=1)
        date_from = date_to - timedelta(days=days - 1)

        db_path = self._db_path()
        if not os.path.exists(db_path):
            log(f"[Action] Timeseries DB not found: {db_path}", level="WARNING")
            return

        log(f"[Action] Generating report: last {days} days ({date_from} to {date_to})")
        comparison = tariff_engine.run_comparison(
            timeseries_db_path = db_path,
            agile_db_path      = self._agile_db_path(),
            region             = self._region(),
            date_from          = date_from,
            date_to            = date_to,
            export_tariff_key  = self._export_tariff_key(),
        )

        if comparison.get("slots", 0) == 0:
            log("[Action] No data for period — report skipped.", level="WARNING")
            return

        export_name = tariff_engine.EXPORT_TARIFFS[self._export_tariff_key()]["name"]
        path, err = report_generator.generate_report(
            comparison, date_from, date_to, self._output_dir(), export_name
        )
        if err:
            log(f"[Action] Report failed: {err}", level="ERROR")
        else:
            self._last_report_path = path
            self._log_comparison_summary(comparison, date_from, date_to)
            log(f"[Action] Report saved: {path}")

            open_on_action = self.pluginPrefs.get("openOnScheduledReport", False)
            if open_on_action:
                report_generator.open_in_libreoffice(path, log_fn=log)

    def actionUpdatePrices(self, action):
        """Action: Fetch latest Agile prices. Schedulable."""
        self.updatePriceData()

    # ================================================================
    # Internal helpers
    # ================================================================

    def _log_comparison_summary(self, comparison, date_from, date_to):
        results = comparison.get("results", [])
        totals  = comparison.get("raw_totals", {})
        slots   = comparison.get("slots", 0)
        days    = comparison.get("days", 0)

        tracker_row = next((r for r in results if r["tariff_key"] == "tracker"), None)
        baseline_p  = tracker_row["total_cost_p"] if tracker_row else 0.0

        log(f"[Compare] {date_from} to {date_to} | {days} days | {slots} slots")
        log(f"[Compare] Import: {totals.get('grid_import_kwh', 0):.1f} kWh  "
            f"Export: {totals.get('grid_export_kwh', 0):.1f} kWh  "
            f"PV: {totals.get('pv_kwh', 0):.1f} kWh")
        log(f"[Compare] {'Tariff':<35} {'Cost':>8}  {'vs Tracker':>12}  {'Cover':>6}")
        log(f"[Compare] {'-'*65}")
        for r in results:
            total_gbp  = r["total_cost_p"] / 100.0
            diff_gbp   = (r["total_cost_p"] - baseline_p) / 100.0
            diff_str   = f"{diff_gbp:+.2f}"
            marker     = " <<" if r["tariff_key"] == "tracker" else ""
            log(f"[Compare] {r['tariff_name']:<35} GBP{total_gbp:>6.2f}  "
                f"{diff_str:>12}  {r['coverage_pct']:>5.0f}%{marker}")
