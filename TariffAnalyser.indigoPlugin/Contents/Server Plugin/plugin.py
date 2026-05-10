#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    plugin.py
# Description: TariffAnalyser - compares UK energy tariffs against recorded
#              half-hourly energy data from SigenEnergyManager.
#              Outputs CSV reports openable in LibreOffice or Numbers.
#              Includes Energy Dashboard with daily_summary DB tracking.
# Author:      CliveS & Claude Sonnet 4.6
# Date:        06-05-2026
# Version:     1.1

import indigo
import os
import sqlite3
import sys
import time
from datetime import datetime, date, timedelta

sys.path.insert(0, os.getcwd())
try:
    from plugin_utils import log_startup_banner
except ImportError:
    log_startup_banner = None

sys.path.insert(0, "/Library/Application Support/Perceptive Automation")
try:
    from IndigoSecrets import (
        OCTOPUS_API_KEY        as _OCTOPUS_API_KEY,
        OCTOPUS_MPAN           as _OCTOPUS_MPAN,
        OCTOPUS_SERIAL         as _OCTOPUS_SERIAL,
        OCTOPUS_EXPORT_MPAN    as _OCTOPUS_EXPORT_MPAN,
        OCTOPUS_EXPORT_SERIAL  as _OCTOPUS_EXPORT_SERIAL,
        OCTOPUS_GAS_MPRN       as _OCTOPUS_GAS_MPRN,
        OCTOPUS_GAS_SERIAL     as _OCTOPUS_GAS_SERIAL,
    )
    _SECRETS_LOADED = True
except ImportError:
    _OCTOPUS_API_KEY = _OCTOPUS_MPAN = _OCTOPUS_SERIAL = ""
    _OCTOPUS_EXPORT_MPAN = _OCTOPUS_EXPORT_SERIAL = ""
    _OCTOPUS_GAS_MPRN = _OCTOPUS_GAS_SERIAL = ""
    _SECRETS_LOADED = False

import tariff_engine
import octopus_prices
import report_generator
import daily_collector
import energy_dashboard

PLUGIN_ID      = "com.clives.indigoplugin.tariffanalyser"
PLUGIN_NAME    = "Tariff Analyser"
PLUGIN_VERSION = "1.1"

# How many days back to refresh on each nightly auto-update (covers Octopus data delays)
DAILY_SUMMARY_ROLLING_DAYS = 7
# Hour (local time) to run the automatic daily summary update
AUTO_UPDATE_HOUR = 2

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
        self._last_auto_update  = None   # date of last automatic daily summary run

        secrets_status = "Loaded (from secrets.py)" if _SECRETS_LOADED else "NOT FOUND - Octopus features disabled"
        if log_startup_banner:
            log_startup_banner(plugin_id, plugin_display_name, plugin_version, extras=[
                ("Timeseries DB:", self._db_path()),
                ("Agile DB:",      self._agile_db_path()),
                ("Output folder:", self._output_dir()),
                ("Region:",        self._region()),
                ("Secrets:",       secrets_status),
                ("Auto-update:",   f"Daily at {AUTO_UPDATE_HOUR:02d}:00 (rolling {DAILY_SUMMARY_ROLLING_DAYS} days)"),
            ])
        else:
            indigo.server.log(f"{plugin_display_name} v{plugin_version} starting")

    def startup(self):
        log(f"{PLUGIN_NAME} v{PLUGIN_VERSION} ready")
        os.makedirs(self._output_dir(), exist_ok=True)
        octopus_prices.init_agile_db(self._agile_db_path())
        db_path = self._db_path()
        if os.path.exists(db_path):
            daily_collector.init_daily_summary_db(db_path)
            log(f"[DailySummary] Table ready: {db_path}")

    def shutdown(self):
        log(f"{PLUGIN_NAME} shutting down")

    def runConcurrentThread(self):
        """Auto-refresh daily_summary once per day at AUTO_UPDATE_HOUR (default 02:00)."""
        while True:
            try:
                now   = datetime.now()
                today = now.date()
                if now.hour == AUTO_UPDATE_HOUR and self._last_auto_update != today:
                    self._last_auto_update = today
                    log(f"[DailySummary] Midnight auto-update starting ({DAILY_SUMMARY_ROLLING_DAYS}-day rolling)")
                    self._run_daily_summary_update()
            except self.StopThread:
                break
            except Exception as exc:
                log(f"[DailySummary] Concurrent thread error: {exc}", level="ERROR")
            self.sleep(60)

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

    def _gas_unit_rate(self):
        try:
            return float(self.pluginPrefs.get("gasUnitRateP", "6.09"))
        except (ValueError, TypeError):
            return 6.09

    def _build_octopus_config(self):
        return {
            "api_key":         _OCTOPUS_API_KEY,
            "mpan":            _OCTOPUS_MPAN,
            "serial":          _OCTOPUS_SERIAL,
            "export_mpan":     _OCTOPUS_EXPORT_MPAN,
            "export_serial":   _OCTOPUS_EXPORT_SERIAL,
            "mprn":            _OCTOPUS_GAS_MPRN,
            "gas_serial":      _OCTOPUS_GAS_SERIAL,
            "region":          self._region(),
            "gas_unit_rate_p": self._gas_unit_rate(),
            "timeseries_db":   DEFAULT_DB_PATH,
        }

    def _run_daily_summary_update(self, days=DAILY_SUMMARY_ROLLING_DAYS, label="[DailySummary]"):
        """Fetch/refresh the last N days of daily_summary data from Octopus API."""
        db_path = self._db_path()
        if not os.path.exists(db_path):
            log(f"{label} Timeseries DB not found — skipping.", level="WARNING")
            return False

        if not _SECRETS_LOADED:
            log(f"{label} secrets.py not found — Octopus credentials unavailable.", level="WARNING")
            return False

        date_to   = date.today() - timedelta(days=1)
        date_from = date_to - timedelta(days=days - 1)

        log(f"{label} Updating daily_summary: {date_from} to {date_to} ({days} days)")
        try:
            daily_collector.init_daily_summary_db(db_path)
            daily_collector.update_daily_summary(
                db_path, date_from, date_to,
                self._build_octopus_config(),
                log_fn=log,
            )
            log(f"{label} Daily summary update complete.")
            return True
        except Exception as exc:
            log(f"{label} Update failed: {exc}", level="ERROR")
            return False

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

        earliest_date = date.fromisoformat(earliest)
        latest_date   = date.fromisoformat(latest)

        if date_to < earliest_date or date_from > latest_date:
            errors["from_day"] = (
                f"No data for that date range. "
                f"Available data: {earliest_date.strftime('%d/%m/%Y')} "
                f"to {latest_date.strftime('%d/%m/%Y')} "
                f"({total_slots} slots)."
            )
            return False, valuesDict, errors

        self._ensure_agile_prices(date_from, date_to)
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
            days_held = (date.fromisoformat(latest) - date.fromisoformat(earliest)).days + 1
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
    # Menu item dialog pre-population — getMenuActionConfigUiValues is the
    # correct Indigo base-class hook (plugin_base.py line 1195) that runs
    # before the dialog opens, allowing fields to be seeded with live values.
    # ================================================================

    def getMenuActionConfigUiValues(self, menu_id):
        values_dict = indigo.Dict()
        errors_dict = indigo.Dict()
        today = date.today()
        if menu_id == "dailyEnergyReport":
            values_dict["rpt_day"]   = f"{today.day:02d}"
            values_dict["rpt_month"] = f"{today.month:02d}"
            values_dict["rpt_year"]  = str(today.year)
        return (values_dict, errors_dict)

    # ================================================================
    # Menu: Daily Energy Summary (opens dialog)
    # ================================================================

    def dailyEnergyReport(self, valuesDict, typeId):
        errors = indigo.Dict()

        today = date.today()
        try:
            report_date = date(
                int(valuesDict.get("rpt_year",  str(today.year))),
                int(valuesDict.get("rpt_month", f"{today.month:02d}")),
                int(valuesDict.get("rpt_day",   f"{today.day:02d}")),
            )
        except ValueError as exc:
            errors["rpt_day"] = f"Invalid date: {exc}"
            return False, valuesDict, errors

        if report_date > today:
            errors["rpt_day"] = "Date cannot be in the future."
            return False, valuesDict, errors

        db_path = self._db_path()
        if not os.path.exists(db_path):
            errors["rpt_day"] = "Timeseries DB not found. Check SigenEnergyManager is running v4.6+."
            return False, valuesDict, errors

        self._ensure_agile_prices(report_date, report_date)

        log(f"[Daily] Generating report for {report_date.strftime('%d/%m/%Y')}")
        path, err = report_generator.generate_daily_report(
            db_path, report_date, self._output_dir(),
            export_rate_p=12.0, log_fn=log,
        )
        if err:
            errors["rpt_day"] = err
            return False, valuesDict, errors

        self._last_report_path = path
        if valuesDict.get("rptOpenInBrowser", True):
            report_generator.open_in_browser(path, log_fn=log)

        return True, valuesDict, errors

    def actionDailyEnergyReport(self, action):
        """Action: generate daily report for yesterday. Schedulable."""
        report_date = date.today() - timedelta(days=1)
        db_path     = self._db_path()
        if not os.path.exists(db_path):
            log("[Daily] Timeseries DB not found — skipping.", level="WARNING")
            return

        log(f"[Daily] Generating scheduled report for {report_date.strftime('%d/%m/%Y')}")
        path, err = report_generator.generate_daily_report(
            db_path, report_date, self._output_dir(),
            export_rate_p=12.0, log_fn=log,
        )
        if err:
            log(f"[Daily] Report failed: {err}", level="ERROR")
        else:
            self._last_report_path = path
            log(f"[Daily] Report saved: {path}")

    # ================================================================
    # Menu: Period reports (weekly / monthly / yearly / custom)
    # ================================================================

    def _ensure_agile_prices(self, date_from, date_to):
        """Silently fetch any missing Agile price slots for the date range."""
        try:
            imp, exp = octopus_prices.fetch_agile_prices(
                self._agile_db_path(), self._region(),
                date_from, date_to, log_fn=log,
            )
            if imp or exp:
                log(f"[Prices] Auto-fetched: +{imp} import, +{exp} export slots")
        except Exception as exc:
            log(f"[Prices] Auto-fetch failed (non-fatal): {exc}", level="WARNING")

    def _period_report(self, date_from, date_to, label):
        """Shared logic for all period report menu callbacks."""
        errors  = indigo.Dict()
        db_path = self._db_path()
        if not os.path.exists(db_path):
            errors["rpt_day"] = "Timeseries DB not found. Check SigenEnergyManager v4.6+."
            return False, errors

        self._ensure_agile_prices(date_from, date_to)
        log(f"[Period] {label}: {date_from.strftime('%d/%m/%Y')} to {date_to.strftime('%d/%m/%Y')}")
        path, err = report_generator.generate_period_report(
            db_path, date_from, date_to, label,
            self._output_dir(), export_rate_p=12.0, log_fn=log,
        )
        if err:
            errors["rpt_day"] = err
            return False, errors

        self._last_report_path = path
        report_generator.open_in_browser(path, log_fn=log)
        return True, errors

    def weeklyEnergyReport(self, valuesDict, typeId):
        errors = indigo.Dict()
        try:
            date_from = date(
                int(valuesDict.get("rpt_year", "2026")),
                int(valuesDict.get("rpt_month", "05")),
                int(valuesDict.get("rpt_day",   "01")),
            )
        except ValueError as exc:
            errors["rpt_day"] = f"Invalid date: {exc}"
            return False, valuesDict, errors
        date_to = date_from + timedelta(days=6)
        ok, errors = self._period_report(date_from, date_to, "Weekly")
        return ok, valuesDict, errors

    def monthlyEnergyReport(self, valuesDict, typeId):
        errors = indigo.Dict()
        import calendar
        try:
            year  = int(valuesDict.get("rpt_year",  "2026"))
            month = int(valuesDict.get("rpt_month", "05"))
            date_from = date(year, month, 1)
            last_day  = calendar.monthrange(year, month)[1]
            date_to   = date(year, month, last_day)
        except ValueError as exc:
            errors["rpt_month"] = f"Invalid date: {exc}"
            return False, valuesDict, errors
        ok, errors = self._period_report(date_from, date_to, "Monthly")
        return ok, valuesDict, errors

    def yearlyEnergyReport(self, valuesDict, typeId):
        errors = indigo.Dict()
        try:
            year      = int(valuesDict.get("rpt_year", "2026"))
            date_from = date(year, 1, 1)
            date_to   = date(year, 12, 31)
        except ValueError as exc:
            errors["rpt_year"] = f"Invalid year: {exc}"
            return False, valuesDict, errors
        ok, errors = self._period_report(date_from, date_to, "Yearly")
        return ok, valuesDict, errors

    def customPeriodReport(self, valuesDict, typeId):
        errors = indigo.Dict()
        try:
            date_from = date(
                int(valuesDict.get("from_year",  "2026")),
                int(valuesDict.get("from_month", "04")),
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
            errors["from_day"] = "From date must be before To date."
            return False, valuesDict, errors
        ok, errors = self._period_report(date_from, date_to, "Custom Period")
        return ok, valuesDict, errors

    def actionWeeklyEnergyReport(self, action):
        """Action: last 7 complete days. Schedulable."""
        today     = date.today()
        date_to   = today - timedelta(days=1)
        date_from = date_to - timedelta(days=6)
        self._period_report(date_from, date_to, "Weekly")

    def actionMonthlyEnergyReport(self, action):
        """Action: last complete calendar month. Schedulable."""
        import calendar
        today      = date.today()
        first_this = today.replace(day=1)
        date_to    = first_this - timedelta(days=1)
        date_from  = date_to.replace(day=1)
        self._period_report(date_from, date_to, "Monthly")

    def actionYearlyEnergyReport(self, action):
        """Action: last complete calendar year. Schedulable."""
        last_year = date.today().year - 1
        self._period_report(date(last_year, 1, 1), date(last_year, 12, 31), "Yearly")

    # ================================================================
    # Menu: Savings Summary
    # ================================================================

    def savingsSummary(self, valuesDict=None, typeId=None):
        """Generate a savings summary page for today/week/month/year."""
        db_path = self._db_path()
        if not os.path.exists(db_path):
            log("[Savings] Timeseries DB not found. Check SigenEnergyManager v4.6+.",
                level="WARNING")
            return

        log("[Savings] Generating savings summary...")
        path, err = report_generator.generate_savings_summary(
            db_path, self._output_dir(), export_rate_p=12.0, log_fn=log,
        )
        if err:
            log(f"[Savings] Failed: {err}", level="ERROR")
        else:
            self._last_report_path = path
            report_generator.open_in_browser(path, log_fn=log)

    # ================================================================
    # Menu: Show Plugin Info
    # ================================================================

    def showPluginInfo(self, valuesDict=None, typeId=None):
        secrets_status = "Loaded (from secrets.py)" if _SECRETS_LOADED else "NOT FOUND - Octopus features disabled"
        if log_startup_banner:
            log_startup_banner(self.pluginId, self.pluginDisplayName,
                               self.pluginVersion, extras=[
                                   ("Timeseries DB:", self._db_path()),
                                   ("Agile DB:",      self._agile_db_path()),
                                   ("Output folder:", self._output_dir()),
                                   ("Region:",        self._region()),
                                   ("Secrets:",       secrets_status),
                                   ("Auto-update:",   f"Daily at {AUTO_UPDATE_HOUR:02d}:00 (rolling {DAILY_SUMMARY_ROLLING_DAYS} days)"),
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
    # Menu: Run Energy Backfill (one-shot historical import)
    # ================================================================

    def runBackfill(self, valuesDict=None, typeId=None):
        """Import Sigenergy File 2 XLSX then fetch all Octopus data from Jan 2026."""
        db_path = self._db_path()
        if not os.path.exists(db_path):
            log("[Backfill] Timeseries DB not found. Check SigenEnergyManager v4.6+.",
                level="WARNING")
            return

        if not _SECRETS_LOADED:
            log("[Backfill] secrets.py not found — Octopus API credentials unavailable.",
                level="WARNING")
            return

        daily_collector.init_daily_summary_db(db_path)
        log("[Backfill] Starting energy history backfill...")

        # Step 1: Sigenergy File 2 (solar/battery data from Mar 13 2026)
        xlsx = daily_collector.SIGEN_FILE2_PATH
        if os.path.exists(xlsx):
            daily_collector.import_sigenergy_file2(db_path, xlsx, log_fn=log)
        else:
            log(f"[Backfill] Sigenergy File 2 not found at: {xlsx}", level="WARNING")
            log("[Backfill] Download from Sigenergy app: Station -> Export -> Daily Energy")

        # Step 2: Octopus API backfill in monthly batches (Jan 2026 → yesterday)
        backfill_from = date(2026, 1, 1)
        backfill_to   = date.today() - timedelta(days=1)
        config        = self._build_octopus_config()

        log(f"[Backfill] Fetching Octopus data: {backfill_from} to {backfill_to}")
        cur_start = backfill_from
        while cur_start <= backfill_to:
            if cur_start.month == 12:
                next_month = date(cur_start.year + 1, 1, 1)
            else:
                next_month = date(cur_start.year, cur_start.month + 1, 1)
            cur_end = min(next_month - timedelta(days=1), backfill_to)

            try:
                daily_collector.update_daily_summary(
                    db_path, cur_start, cur_end, config, log_fn=log
                )
            except Exception as exc:
                log(f"[Backfill] Octopus fetch failed {cur_start}-{cur_end}: {exc}",
                    level="ERROR")
            cur_start = next_month

        # Summary
        try:
            con      = sqlite3.connect(db_path)
            total    = con.execute("SELECT COUNT(*) FROM daily_summary").fetchone()[0]
            solar    = con.execute("SELECT COUNT(*) FROM daily_summary WHERE pv_kwh > 0").fetchone()[0]
            gas      = con.execute("SELECT COUNT(*) FROM daily_summary WHERE gas_kwh IS NOT NULL").fetchone()[0]
            con.close()
            log(f"[Backfill] Complete — {total} days total, {solar} with solar, {gas} with gas")
            log("[Backfill] Use 'Open Energy Dashboard' to view results")
        except Exception as exc:
            log(f"[Backfill] Summary query failed: {exc}", level="WARNING")

    # ================================================================
    # Menu: Open Energy Dashboard
    # ================================================================

    def openEnergyDashboard(self, valuesDict=None, typeId=None):
        """Generate the interactive HTML energy dashboard and open it in the browser."""
        db_path = self._db_path()
        if not os.path.exists(db_path):
            log("[Dashboard] Timeseries DB not found. Check SigenEnergyManager v4.6+.",
                level="WARNING")
            return

        daily_collector.init_daily_summary_db(db_path)
        log("[Dashboard] Generating energy dashboard...")
        out_dir = self._output_dir()
        os.makedirs(out_dir, exist_ok=True)

        path, err = energy_dashboard.generate_dashboard(db_path, out_dir, log_fn=log)
        if err:
            log(f"[Dashboard] Generation failed: {err}", level="ERROR")
        else:
            log(f"[Dashboard] Dashboard saved: {path}")
            energy_dashboard.open_in_browser(path, log_fn=log)

    # ================================================================
    # Menu: Update Daily Summary Now
    # ================================================================

    def updateDailySummaryNow(self, valuesDict=None, typeId=None):
        """On-demand refresh of the daily_summary table (last 7 days)."""
        self._run_daily_summary_update(label="[DailySummary]")

    # ================================================================
    # Actions (schedulable) — Energy Dashboard
    # ================================================================

    def actionUpdateDailySummary(self, action):
        """Action: Refresh daily_summary for last 7 days. Schedule nightly via Indigo."""
        days_str = action.props.get("rollingDays", str(DAILY_SUMMARY_ROLLING_DAYS))
        try:
            days = int(days_str)
        except (ValueError, TypeError):
            days = DAILY_SUMMARY_ROLLING_DAYS
        self._run_daily_summary_update(days=days, label="[DailySummary][Action]")

    def actionOpenEnergyDashboard(self, action):
        """Action: Regenerate and open energy dashboard. Schedulable."""
        self.openEnergyDashboard()

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
