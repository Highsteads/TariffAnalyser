#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    plugin.py
# Description: TariffAnalyser - compares UK energy tariffs against recorded
#              half-hourly energy data from SigenEnergyManager.
#              Outputs HTML reports that open in the default browser.
# Author:      CliveS & Claude Opus 5.5
# Date:        27-09-2026
# Version:     1.10
#
# v1.10 (27-09-2026): the faults found while writing the plain-English guide.
# * Region menu: K-P named after the wrong areas (K is South Wales, L South West
#   England, M Yorkshire, N South Scotland, P North Scotland).
# * "Open report in LibreOffice" checkbox relabelled - it opens the browser.
# * Tariff Comparison dialog no longer lists Flexible, Intelligent Go and
#   Intelligent Flux, which were never compared.
# * The Generate Tariff Comparison Report action now fetches Agile prices when
#   the stored ones do not cover its period, as the menu item did; a failed
#   fetch is a WARNING and the report goes ahead. The menu item now skips the
#   network when the prices are already there (octopus_prices.missing_days).
# * Energy Summary header names the chosen export tariff and its real price
#   (SEG minimum 1.63p showed as "Octopus Outgoing 2p").
# * The recorded-prices row is named from the data (tariff_engine.
#   recorded_tariff_label) plus SigenEnergyManager's Tariff Monitor, not a fixed
#   "Octopus Tracker (actual)" - since 17-09-2026 that column holds Flux prices
#   on the author's house. A period that spans a tariff change says so.
# * Nightly collection: the solar install date (13-03-2026) and Tracker product
#   (SILVER-25-04-11) were fixed for one house. Both are optional settings now,
#   blank = no install-date cut-off / the recorded prices. Region from the
#   region setting as before. The dead Sigenergy-file importer lost its default
#   path, which was one house's own file.
# * IndigoSecrets.py read per key: a file missing any one Octopus line used to
#   be ignored entirely.
#
# v1.9.5 (23-09-2026): NO SERVER CALL AT IMPORT. The default SigenEnergyManager
# DB path was built at MODULE level from indigo.server.getInstallFolderPath().
# During a bulk restart of six plugins on 11-09-2026 that call timed out and the
# plugin died at import (ServerCommunicationError), before startup() could log
# or retry. The install folder is now resolved by Plugin._install_folder_path():
# cached once known, retried on each use until then, one WARNING per outage.
# While unknown, the timeseries DB and Agile cache read as "not found" and the
# plugin stays up. Paths are unchanged when the server answers.
# tests/test_import_safety.py imports plugin.py with a stub whose every server
# call raises.
#
# v1.9.3 (08-08-2026): REQUIRED Info.plist KEY. `CFBundleURLTypes` was PRESENT but
# EMPTY, so the plugin shipped without the support URL that becomes its
# "About" menu item — one of the SIX keys the official Developer's Guide lists as
# required. An empty array satisfies "key exists" while giving users nowhere to go,
# which is why an earlier sweep that only looked for a MISSING key passed it. Found
# by an estate check auditing the VALUE rather than the key's presence.
# No plugin logic changed.
#
# v1.9.2 (21-07-2026): shared plugin_utils.py refreshed to v1.3 — the
# estate-wide propagation of the four Appliance Monitor deep-review fixes.
# * install_timestamp_filter() is idempotent — a second call used to stack a
#   second filter, so every log line came out with two timestamps.
# * `import indigo` is soft, so the module imports outside the Indigo host and
#   can be exercised by offline tests.
# * A malformed log call keeps its arguments in the log instead of dropping
#   them, so a %-placeholder mismatch is visible.
# * New shared as_bool() — a pref re-serialised as the string "false" is
#   truthy, which is exactly the wrong answer.
#
# v1.9.1 (21-07-2026): LOG-LEVEL FIX. indigo.server.log(level=...) wants a Python
# logging INT — a STRING is silently ignored and the line logs as plain Info.
# The log() helper passed its level name straight through, so every WARNING and
# ERROR raised through it had been appearing as an ordinary Info line. Added
# _lvl() to map the name to a real level. Estate-wide sweep (38 files).
#
# v1.9 (18-07-2026) — deep-review IMPROVEMENTS batch:
# - New "Test Octopus API Connection" menu item — checks the public Agile
#   products endpoint + the discovered import/export product codes for the
#   configured region, reports cached-price coverage and whether metered-data
#   credentials are set. Confirms connectivity before running a comparison.
# - The comparison report now states when the illustrative "typical" fixed
#   tariffs (Go/Cosy/Flux/Ofgem cap/fixed suppliers) were last checked
#   (REFERENCE_RATES_UPDATED) so a user knows how current they are, and that
#   Tracker/Agile use live rates.
# - Declined by design: a fully user-configurable tariff table (JSON) — a
#   larger feature needing its own schema + validation UI; documented for a
#   future release rather than rushed into this batch.
#
# v1.8 (18-07-2026) — deep-review TEST-BUILDOUT batch:
# - New test_collector.py (12 tests): the pure helpers in daily_collector +
#   octopus_prices — TOU band assignment (Go two-band, Flux three-band),
#   _in_window daytime + overnight boundaries, the gas m3->kWh constant, UTC->
#   local conversion across the BST and GMT boundaries (TZ pinned to
#   Europe/London so it's deterministic), and the Agile re-fetch period builder.
#   Suite 15 -> 27.
# - Removed the dead fetch_log table from the agile DB schema (declared but
#   never read or written).
# - Declined by design: INSERT OR IGNORE for cached Agile prices is kept (a
#   published Agile price is final, so never overwrite it on a re-fetch); the
#   in-memory _last_auto_update flag is kept (the nightly update is idempotent,
#   so a rare restart-during-02:00 re-run is harmless).
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
# Per key (house rule): a missing single key must not blank the others. Until
# v1.10 one grouped import of all seven names meant a file lacking any one of
# them was ignored entirely and every value fell back to PluginConfig.
try:
    import IndigoSecrets as _secrets_mod
    _SECRETS_LOADED = True
except ImportError:
    _secrets_mod = None
    _SECRETS_LOADED = False


def _secret(name):
    """One IndigoSecrets value as a stripped string, "" when absent."""
    if _secrets_mod is None:
        return ""
    value = getattr(_secrets_mod, name, "")
    return str(value).strip() if value else ""


_OCTOPUS_API_KEY       = _secret("OCTOPUS_API_KEY")
_OCTOPUS_MPAN          = _secret("OCTOPUS_MPAN")
_OCTOPUS_SERIAL        = _secret("OCTOPUS_SERIAL")
_OCTOPUS_EXPORT_MPAN   = _secret("OCTOPUS_EXPORT_MPAN")
_OCTOPUS_EXPORT_SERIAL = _secret("OCTOPUS_EXPORT_SERIAL")
_OCTOPUS_GAS_MPRN      = _secret("OCTOPUS_GAS_MPRN")
_OCTOPUS_GAS_SERIAL    = _secret("OCTOPUS_GAS_SERIAL")

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

# Default SigenEnergyManager timeseries DB lives in that plugin's prefs folder,
# under the versioned Indigo install folder. The folder is resolved at RUNTIME by
# Plugin._install_folder_path() — never here. A server call at module level has
# no second chance: when it timed out during a bulk restart (11-09-2026) the
# plugin died at import, before startup() could log or retry anything.
SIGEN_PLUGIN_ID = "com.clives.indigoplugin.sigenergy-energy-manager"
SIGEN_DB_NAME   = "energy_timeseries.db"

# Octopus region used until the user picks one (F = North East England; matches
# the defaultValue of the octopusRegion menu in PluginConfig.xml)
DEFAULT_REGION = "F"


import logging


_LOG_LEVELS = {
    "DEBUG":   logging.DEBUG,
    "INFO":    logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR":   logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}


def _lvl(level):
    """Map a level NAME to a Python logging int.

    indigo.server.log(level=...) wants an int. A STRING is silently ignored
    and the line logs as plain Info, which hid every WARNING and ERROR raised
    through log() until this was corrected (21-07-2026).
    """
    if isinstance(level, int):
        return level
    return _LOG_LEVELS.get(str(level).upper(), logging.INFO)


def log(message, level="INFO"):
    indigo.server.log(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}] {message}",
                      level=_lvl(level))


class Plugin(indigo.PluginBase):

    def __init__(self, plugin_id, plugin_display_name, plugin_version, plugin_prefs):
        super().__init__(plugin_id, plugin_display_name, plugin_version, plugin_prefs)
        self.pluginId           = plugin_id
        self.pluginDisplayName  = plugin_display_name
        self.pluginVersion      = plugin_version

        self._last_report_path  = None   # path of most recently generated report
        self._last_auto_update  = None   # date of last automatic daily summary run
        self._install_folder    = None   # resolved lazily; see _install_folder_path()
        self._install_warned    = False  # one WARNING per outage, not one per use
        self.timestamp_enabled  = bool(plugin_prefs.get("timestampEnabled", True))

        if install_timestamp_filter:
            self._ts_filter = install_timestamp_filter(self, enabled=self.timestamp_enabled)
        else:
            self._ts_filter = None

        # Startup banner moved to showPluginInfo on demand (revised 25-May-2026 per Jay).

    def startup(self):
        log(f"{PLUGIN_NAME} v{self.pluginVersion} ready")
        os.makedirs(self._output_dir(), exist_ok=True)
        agile_db = self._agile_db_path()
        if agile_db:
            octopus_prices.init_agile_db(agile_db)
        db_path = self._db_path()
        if db_path and os.path.exists(db_path):
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

    def validatePrefsConfigUi(self, valuesDict):
        """Refuse an install date or Tracker product code the collection could
        not use, rather than saving it and ignoring it every night."""
        errors = indigo.Dict()
        try:
            daily_collector.parse_install_date(valuesDict.get("solarInstallDate", ""))
        except ValueError:
            errors["solarInstallDate"] = ("Enter the date as YYYY-MM-DD, such as "
                                          "2026-03-13, or leave it blank.")
        try:
            product = daily_collector.normalise_tracker_product(
                valuesDict.get("trackerProduct", ""))
            valuesDict["trackerProduct"] = product
        except ValueError:
            errors["trackerProduct"] = ("Enter a Tracker product code such as "
                                        "SILVER-25-04-11, or leave it blank.")
        if errors:
            return False, valuesDict, errors
        return True, valuesDict

    # ================================================================
    # Plugin prefs helpers
    # ================================================================

    def _install_folder_path(self):
        """The versioned Indigo install folder, or None if the server has not
        answered. Cached once known; retried on every use until then, so a
        server that is slow at startup costs a WARNING, not the plugin."""
        if self._install_folder:
            return self._install_folder
        try:
            folder = indigo.server.getInstallFolderPath()
        except Exception as exc:
            if not self._install_warned:
                self._install_warned = True
                log(f"Could not get the Indigo install folder from the server ({exc}). "
                    f"The SigenEnergyManager timeseries DB and the Agile price cache "
                    f"are unavailable until it answers; will retry on next use.",
                    level="WARNING")
            return None
        if not folder:
            return None
        self._install_folder = folder
        if self._install_warned:
            self._install_warned = False
            log(f"Indigo install folder now resolved: {folder}")
        return folder

    def _default_db_path(self):
        """SigenEnergyManager's timeseries DB, or "" while the install folder
        is unknown (callers treat "" as not found)."""
        folder = self._install_folder_path()
        if not folder:
            return ""
        return os.path.join(folder, "Preferences", "Plugins", SIGEN_PLUGIN_ID, SIGEN_DB_NAME)

    def _db_path(self):
        configured = self.pluginPrefs.get("dbPath", "").strip()
        return configured if configured else self._default_db_path()

    def _agile_db_path(self):
        """Agile price cache path, or "" while the install folder is unknown."""
        folder = self._install_folder_path()
        if not folder:
            return ""
        data_dir = os.path.join(folder, "Preferences", "Plugins", PLUGIN_ID)
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

    def _export_label(self):
        """Energy Summary header text: the export tariff's real name and the
        flat price the summary uses for it."""
        tariff = tariff_engine.EXPORT_TARIFFS.get(self._export_tariff_key(), {})
        name   = tariff.get("name", self._export_tariff_key())
        return report_generator.export_tariff_label(
            name, self._export_rate_flat_p(),
            flat_rate_known=tariff.get("rate_p") is not None)

    def _current_tariff_name(self):
        """The tariff SigenEnergyManager's Tariff Monitor says is active now
        (e.g. "Octopus Flux"), or "" if there is no such device or no answer.
        Used only to name the recorded-prices row; the data decides whether the
        name fits (tariff_engine.recorded_tariff_label)."""
        try:
            for dev in indigo.devices.iter(SIGEN_PLUGIN_ID):
                if dev.deviceTypeId == "tariffMonitor":
                    return tariff_engine.clean_tariff_name(
                        dev.states.get("tariffActive", ""))
        except Exception as exc:
            self.logger.debug(f"Could not read the Tariff Monitor device: {exc}")
        return ""

    def _solar_install_date(self):
        """The optional solar install date setting, or None (blank or not a
        date — a bad value is refused by the dialog, so only a hand-edited
        pref reaches the warning)."""
        raw = self.pluginPrefs.get("solarInstallDate", "")
        try:
            return daily_collector.parse_install_date(raw)
        except ValueError:
            log(f"Solar install date '{raw}' is not a YYYY-MM-DD date - ignored, "
                f"so every day with solar data counts.", level="WARNING")
            return None

    def _tracker_product(self):
        raw = self.pluginPrefs.get("trackerProduct", "")
        try:
            return daily_collector.normalise_tracker_product(raw)
        except ValueError:
            log(f"Tracker product code '{raw}' is not a product code - ignored, "
                f"so the collection uses the prices SigenEnergyManager recorded.",
                level="WARNING")
            return ""

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
            "timeseries_db":   self._default_db_path(),
            "tracker_product":    self._tracker_product(),
            "solar_install_date": self._solar_install_date(),
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
            current_tariff_name = self._current_tariff_name(),
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
        """Fetch Agile prices for the period when the stored ones do not cover
        it. Used before every comparison, from the menu and the action. A
        failure is logged and the report goes ahead with the prices it has."""
        agile_db = self._agile_db_path()
        if not agile_db:
            return   # install folder unknown — already warned
        region = self._region()
        try:
            missing = octopus_prices.missing_days(agile_db, region, date_from, date_to)
        except Exception as exc:
            log(f"[Prices] Could not check the stored Agile prices: {exc}", level="WARNING")
            missing = 1
        if not missing:
            self.logger.debug(f"[Prices] Agile prices already cover {date_from} to {date_to}")
            return
        log(f"[Prices] Stored Agile prices are missing {missing} day(s) of "
            f"{date_from} to {date_to} - fetching them")
        try:
            octopus_prices.fetch_agile_prices(
                agile_db, region,
                date_from, date_to, log_fn=log,
            )
        except Exception as exc:
            log(f"[Prices] Could not fetch Agile prices ({exc}). The report uses "
                f"the prices already stored.", level="WARNING")

    def updatePriceData(self, valuesDict=None, typeId=None):
        days = self._default_days()
        date_to   = date.today()
        date_from = date_to - timedelta(days=days - 1)

        agile_db = self._agile_db_path()
        if not agile_db:
            log("[Prices] Agile price cache unavailable (Indigo install folder not "
                "known yet) — try again shortly.", level="WARNING")
            return
        log(f"[Prices] Fetching Agile prices {date_from} to {date_to} "
            f"(region {self._region()})")
        try:
            imp, exp = octopus_prices.fetch_agile_prices(
                agile_db,
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
        today = date.today()
        tariff_label, tariff_note = tariff_engine.recorded_tariff_for_period(
            db_path, today.replace(month=1, day=1), today, self._current_tariff_name())
        path, err = report_generator.generate_savings_summary(
            db_path, self._output_dir(),
            export_rate_p=self._export_rate_flat_p(), log_fn=log,
            export_label=self._export_label(),
            tariff_label=tariff_label, tariff_note=tariff_note,
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
            ("Timeseries DB:",     self._db_path() or "(install folder unknown)"),
            ("Agile DB:",          self._agile_db_path() or "(install folder unknown)"),
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

    def testOctopusApi(self, valuesDict=None, typeId=None):
        """Menu: Test Octopus API Connection — checks the public Agile products
        endpoint (no auth) and the discovered Agile import/export product codes,
        so a user can confirm connectivity + region before running a comparison.
        Full banner first (fleet convention) so the log dump is support-ready."""
        if log_startup_banner:
            log_startup_banner(self.pluginId, self.pluginDisplayName, self.pluginVersion)
        region = self._region()
        log(f"[APITest] Testing Octopus API for region {region} ...")
        ok = True
        for direction in ("import", "export"):
            try:
                code, tariff = octopus_prices._discover_product(region, direction, log)
                if code:
                    log(f"[APITest] Agile {direction}: product={code} tariff={tariff}")
                else:
                    log(f"[APITest] Agile {direction}: NO product discovered "
                        f"(region {region}) — check region setting", level="WARNING")
                    ok = False
            except Exception as exc:
                log(f"[APITest] Agile {direction} discovery FAILED: {exc}", level="ERROR")
                ok = False
        earliest_i, latest_i, earliest_e, latest_e = octopus_prices.get_coverage(
            self._agile_db_path(), region)
        log(f"[APITest] Cached Agile import: {earliest_i or '(none)'} .. {latest_i or '(none)'}")
        log(f"[APITest] Cached Agile export: {earliest_e or '(none)'} .. {latest_e or '(none)'}")
        creds = "yes" if self._have_octopus_creds() else "NO (metered consumption unavailable)"
        log(f"[APITest] Metered-data credentials configured: {creds}")
        log(f"[APITest] Result: {'PASSED' if ok else 'issues found — see warnings above'}")

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
        # Same as the menu item: top up the Agile prices first, or a scheduled
        # report showed Agile as "insufficient price data" whenever nothing had
        # fetched them (nothing does so nightly).
        self._ensure_agile_prices(date_from, date_to)
        comparison = tariff_engine.run_comparison(
            timeseries_db_path = db_path,
            agile_db_path      = self._agile_db_path(),
            region             = self._region(),
            date_from          = date_from,
            date_to            = date_to,
            export_tariff_key  = self._export_tariff_key(),
            current_tariff_name = self._current_tariff_name(),
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
        log(f"[Compare] {'Tariff':<35} {'Cost':>8}  {'vs actual':>12}  {'Cover':>6}")
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
