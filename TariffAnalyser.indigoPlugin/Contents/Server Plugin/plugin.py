#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    plugin.py
# Description: TariffAnalyser - compares UK energy tariffs against recorded
#              half-hourly energy data from SigenEnergyManager.
#              Outputs HTML reports that open in the default browser.
# Author:      CliveS & Claude Opus 4.8
# Date:        18-07-2026
# Version:     1.7
#
# v1.7 (18-07-2026) — deep-review FINANCIAL-FIX batch:
# - FAIR COMPARISON (flagship): run_comparison now prices every selected tariff
#   over a COMMON slot set — the slots where ALL selected tariffs have a rate —
#   with the standing charge pro-rated to that set (1 priced half-hour = 1/48
#   day). Previously a partial-coverage tariff (Agile with a missing API price,
#   Tracker with a NULL DB price) accumulated its import cost over FEWER slots
#   yet paid a full standing charge and was ranked cheapest purely because part
#   of its usage was never counted. Export revenue (tariff-independent) is now
#   also counted once per common slot for all tariffs. Each result carries both
#   the common coverage and the tariff's own_coverage_pct; the report shows a
#   caveat when coverage < 100% and no longer highlights a no-data month as £0.
# - The two SQLite loaders in tariff_engine (and get_coverage/_existing_slots in
#   octopus_prices) narrowed from bare `except Exception` to `except sqlite3.Error`
#   with the connection closed in finally — a real schema/programming error no
#   longer masquerades as a silent empty report, and the connection isn't leaked.
# - daily_collector: a missing Tracker rate now writes NULL for the import-cost
#   columns instead of a real-looking £0 day; Go/Flux "saving vs Tracker" folds
#   each tariff's own standing charge in (like-for-like); the Octopus consumption
#   and gas fetch windows widened an hour each side so the earliest local day's
#   00:00/00:30 slots are not dropped across the BST boundary.
# - Energy Summary export rate now follows the configured export tariff instead
#   of a hardcoded 12p.
# - octopus_prices._discover_product picks the most recent matching product
#   (not the first the API returns) and logs when several match.
# - First-ever test suite: test_tariff_engine.py, 14 tests.
#
# v1.4 (23-05-2026): Millisecond timestamp [HH:MM:SS.mmm] prefix on every
# log line via plugin_utils.install_timestamp_filter() — matches Device
# Activity Monitor convention. New "Toggle Timestamps in Log" menu item.
#
# v1.2 (10-05-2026):
# - Slimmed menu to just three items: Energy Summary, Tariff Comparison,
#   Show Plugin Info.  Removed the daily / weekly / monthly / yearly /
#   custom-period menu entries (consolidated into Energy Summary), the
#   CSV export, the Energy Dashboard menu, the "Open Last Report" entry,
#   the data-coverage menu and the one-off backfill menu.
# - Tariff Comparison now uses a single "Last N days" dropdown instead of
#   the six day/month/year date pickers.
# - Energy Summary now includes Yesterday alongside Today / This week /
#   This month / This year.  Week is calendar-aligned (Monday -> today)
#   instead of last-7-days rolling.
# - Removed CSV export entirely (export_raw_csv) and the LibreOffice
#   opener; reports are HTML and open in the default browser.
# - Plugin version is now read dynamically from Info.plist
#   (self.pluginVersion); no separate Python constant.

import indigo
import os
import sys
from datetime import datetime, date, timedelta

sys.path.insert(0, os.getcwd())
try:
    from plugin_utils import log_startup_banner
except ImportError:
    log_startup_banner = None
try:
    from plugin_utils import install_timestamp_filter
except ImportError:
    install_timestamp_filter = None

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

PLUGIN_ID      = "com.clives.indigoplugin.tariffanalyser"
PLUGIN_NAME    = "Tariff Analyser"
# Plugin version is read dynamically from Info.plist via self.pluginVersion;
# Info.plist is the single source of truth.

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
    indigo.server.log(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] {message}",
                      level=level)


class Plugin(indigo.PluginBase):

    def __init__(self, plugin_id, plugin_display_name, plugin_version, plugin_prefs):
        super().__init__(plugin_id, plugin_display_name, plugin_version, plugin_prefs)
        self.pluginId           = plugin_id
        self.pluginDisplayName  = plugin_display_name
        self.pluginVersion      = plugin_version

        self._last_report_path  = None   # path of most recently generated report
        self._last_auto_update  = None   # date of last automatic daily summary run
        self.timestamp_enabled  = bool(plugin_prefs.get("timestampEnabled", True))

        if install_timestamp_filter:
            self._ts_filter = install_timestamp_filter(self, enabled=self.timestamp_enabled)
        else:
            self._ts_filter = None

        # Startup banner moved to showPluginInfo on demand (revised 25-May-2026 per Jay).

    def startup(self):
        log(f"{PLUGIN_NAME} v{self.pluginVersion} ready")
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

    def _export_rate_flat_p(self):
        """Flat export rate (p/kWh) for the configured export tariff, for the
        savings summary. Agile Outgoing has no single flat rate, so fall back
        to Octopus Outgoing 12p."""
        tariff = tariff_engine.EXPORT_TARIFFS.get(self._export_tariff_key(), {})
        rate = tariff.get("rate_p")
        return float(rate) if rate is not None else 12.0

    def _gas_unit_rate(self):
        try:
            return float(self.pluginPrefs.get("gasUnitRateP", "6.09"))
        except (ValueError, TypeError):
            return 6.09

    def _build_octopus_config(self):
        """Resolve Octopus credentials — IndigoSecrets.py first, PluginConfig
        fallback. Per the global secrets policy, PluginConfig must provide a
        usable channel for users who don't maintain IndigoSecrets.py."""
        prefs = self.pluginPrefs
        return {
            "api_key":         _OCTOPUS_API_KEY        or prefs.get("octopusApiKey",       "").strip(),
            "mpan":            _OCTOPUS_MPAN           or prefs.get("octopusMpan",         "").strip(),
            "serial":          _OCTOPUS_SERIAL         or prefs.get("octopusSerial",       "").strip(),
            "export_mpan":     _OCTOPUS_EXPORT_MPAN    or prefs.get("octopusExportMpan",   "").strip(),
            "export_serial":   _OCTOPUS_EXPORT_SERIAL  or prefs.get("octopusExportSerial", "").strip(),
            "mprn":            _OCTOPUS_GAS_MPRN       or prefs.get("octopusGasMprn",      "").strip(),
            "gas_serial":      _OCTOPUS_GAS_SERIAL     or prefs.get("octopusGasSerial",    "").strip(),
            "region":          self._region(),
            "gas_unit_rate_p": self._gas_unit_rate(),
            "timeseries_db":   DEFAULT_DB_PATH,
        }

    def _have_octopus_creds(self):
        """True if at least the API key resolves from either source."""
        cfg = self._build_octopus_config()
        return bool(cfg["api_key"])

    def _secrets_status_line(self):
        """One-line human description of where credentials are coming from."""
        if _SECRETS_LOADED and _OCTOPUS_API_KEY:
            return "Loaded (from IndigoSecrets.py)"
        if self._have_octopus_creds():
            return "Loaded (from PluginConfig — IndigoSecrets.py not used)"
        return "NOT FOUND — set in IndigoSecrets.py or PluginConfig; Octopus features disabled"

    def _run_daily_summary_update(self, days=DAILY_SUMMARY_ROLLING_DAYS, label="[DailySummary]"):
        """Fetch/refresh the last N days of daily_summary data from Octopus API."""
        db_path = self._db_path()
        if not os.path.exists(db_path):
            log(f"{label} Timeseries DB not found — skipping.", level="WARNING")
            return False

        if not self._have_octopus_creds():
            log(f"{label} Octopus API key not configured — set in IndigoSecrets.py OR "
                f"Plugins -> Tariff Analyser -> Configure.", level="WARNING")
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
    # Menu: Tariff Comparison (lookbackDays dropdown — no date pickers)
    # ================================================================

    def tariffComparison(self, valuesDict, typeId):
        """Run the tariff-comparison report over a rolling N-day window
        ending yesterday.  Opens the resulting HTML in the default browser."""
        errors = indigo.Dict()
        try:
            days = int(valuesDict.get("lookbackDays", "30"))
        except (ValueError, TypeError):
            days = 30
        date_to   = date.today() - timedelta(days=1)
        date_from = date_to - timedelta(days=days - 1)

        db_path = self._db_path()
        if not os.path.exists(db_path):
            errors["lookbackDays"] = (
                "Timeseries DB not found. Check SigenEnergyManager is running v4.6+."
            )
            return False, valuesDict, errors

        earliest, latest, total_slots = tariff_engine.get_coverage(db_path)
        if not earliest:
            errors["lookbackDays"] = (
                "No data in the timeseries DB yet. "
                "SigenEnergyManager v4.6+ must run for at least one 30-min cycle first."
            )
            return False, valuesDict, errors

        # Clamp request to actual data coverage
        earliest_date = date.fromisoformat(earliest)
        if date_from < earliest_date:
            date_from = earliest_date

        self._ensure_agile_prices(date_from, date_to)
        log(f"[Compare] Running comparison {date_from} to {date_to} ({days}-day lookback)")

        comparison = tariff_engine.run_comparison(
            timeseries_db_path = db_path,
            agile_db_path      = self._agile_db_path(),
            region             = self._region(),
            date_from          = date_from,
            date_to            = date_to,
            export_tariff_key  = self._export_tariff_key(),
        )
        if comparison.get("slots", 0) == 0:
            errors["lookbackDays"] = (
                f"No data for {date_from.strftime('%d/%m/%Y')} to "
                f"{date_to.strftime('%d/%m/%Y')}."
            )
            return False, valuesDict, errors

        export_name = tariff_engine.EXPORT_TARIFFS[self._export_tariff_key()]["name"]
        path, err = report_generator.generate_report(
            comparison, date_from, date_to, self._output_dir(), export_name
        )
        if err:
            log(f"[Compare] Report generation failed: {err}", level="ERROR")
            errors["lookbackDays"] = f"Report generation failed: {err}"
            return False, valuesDict, errors

        self._last_report_path = path
        self._log_comparison_summary(comparison, date_from, date_to)
        report_generator.open_in_browser(path, log_fn=log)
        log(f"[Compare] Report saved: {path}")
        return True, valuesDict, errors

    # ================================================================
    # Helper: Octopus Agile price refresh
    # ================================================================

    def _ensure_agile_prices(self, date_from, date_to):
        """Silently fetch any missing Agile price slots for the date range."""
        try:
            octopus_prices.fetch_agile_prices(
                self._agile_db_path(), self._region(),
                date_from, date_to, log_fn=log,
            )
        except Exception as exc:
            log(f"[Prices] Background fetch failed: {exc}", level="WARNING")

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
    # Menu: Energy Summary
    # ================================================================

    def energySummary(self, valuesDict=None, typeId=None):
        """Generate a savings summary page for today/week/month/year."""
        db_path = self._db_path()
        if not os.path.exists(db_path):
            log("[Savings] Timeseries DB not found. Check SigenEnergyManager v4.6+.",
                level="WARNING")
            return

        log("[Savings] Generating savings summary...")
        path, err = report_generator.generate_savings_summary(
            db_path, self._output_dir(),
            export_rate_p=self._export_rate_flat_p(), log_fn=log,
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
        secrets_status = self._secrets_status_line()
        extras = [
            ("Timeseries DB:",     self._db_path()),
            ("Agile DB:",          self._agile_db_path()),
            ("Output folder:",     self._output_dir()),
            ("Region:",            self._region()),
            ("Secrets:",           secrets_status),
            ("Auto-update:",       f"Daily at {AUTO_UPDATE_HOUR:02d}:00 (rolling {DAILY_SUMMARY_ROLLING_DAYS} days)"),
            ("Timestamps in Log:", "ON" if self.timestamp_enabled else "OFF"),
        ]
        if log_startup_banner:
            log_startup_banner(self.pluginId, self.pluginDisplayName,
                               self.pluginVersion, extras=extras)
        else:
            log(f"{self.pluginDisplayName} v{self.pluginVersion}")

    def menuToggleTimestamps(self):
        self.timestamp_enabled = not self.timestamp_enabled
        self.pluginPrefs["timestampEnabled"] = self.timestamp_enabled
        if self._ts_filter:
            self._ts_filter.enabled = self.timestamp_enabled
        state = "ON" if self.timestamp_enabled else "OFF"
        indigo.server.log(f"[{self.pluginDisplayName}] Timestamps in Log -> {state}")

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
                report_generator.open_in_browser(path, log_fn=log)

    def actionUpdatePrices(self, action):
        """Action: Fetch latest Agile prices. Schedulable."""
        self.updatePriceData()

    # ================================================================
    # Actions (schedulable)
    # ================================================================

    def actionUpdateDailySummary(self, action):
        """Action: Refresh daily_summary for last N days. Schedule nightly via Indigo."""
        days_str = action.props.get("rollingDays", str(DAILY_SUMMARY_ROLLING_DAYS))
        try:
            days = int(days_str)
        except (ValueError, TypeError):
            days = DAILY_SUMMARY_ROLLING_DAYS
        self._run_daily_summary_update(days=days, label="[DailySummary][Action]")

    def actionEnergySummary(self, action):
        """Action: regenerate the Energy Summary and open in browser. Schedulable."""
        self.energySummary()

    # ================================================================
    # Internal helpers
    # ================================================================

    def _log_comparison_summary(self, comparison, date_from, date_to):
        results = comparison.get("results", [])
        totals  = comparison.get("raw_totals", {})
        slots   = comparison.get("slots", 0)
        days    = comparison.get("days", 0)

        ranked      = [r for r in results if not r.get("insufficient_data")]
        tracker_row = next((r for r in ranked if r["tariff_key"] == "tracker"), None)
        baseline_p  = tracker_row["total_cost_p"] if tracker_row else 0.0

        log(f"[Compare] {date_from} to {date_to} | {days} days | {slots} slots")
        log(f"[Compare] Import: {totals.get('grid_import_kwh', 0):.1f} kWh  "
            f"Export: {totals.get('grid_export_kwh', 0):.1f} kWh  "
            f"PV: {totals.get('pv_kwh', 0):.1f} kWh")
        log(f"[Compare] {'Tariff':<35} {'Cost':>8}  {'vs Tracker':>12}  {'Cover':>6}")
        log(f"[Compare] {'-'*65}")
        for r in ranked:
            total_gbp  = r["total_cost_p"] / 100.0
            diff_gbp   = (r["total_cost_p"] - baseline_p) / 100.0
            diff_str   = f"{diff_gbp:+.2f}"
            marker     = " <<" if r["tariff_key"] == "tracker" else ""
            log(f"[Compare] {r['tariff_name']:<35} GBP{total_gbp:>6.2f}  "
                f"{diff_str:>12}  {r.get('own_coverage_pct', r['coverage_pct']):>5.0f}%{marker}")
        for r in results:
            if r.get("insufficient_data"):
                log(f"[Compare] {r['tariff_name']:<35} {'(insufficient data)':>22}  "
                    f"{r.get('own_coverage_pct', 0):>5.0f}%")
