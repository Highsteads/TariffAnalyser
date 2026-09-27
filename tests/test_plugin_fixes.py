#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_plugin_fixes.py
# Description: Plugin-level regression tests for the v1.10 fixes: IndigoSecrets
#              read per key, the scheduled comparison fetching missing Agile
#              prices first, the Energy Summary's export header, the recorded
#              tariff name read from SigenEnergyManager, the new optional
#              settings, and the region letters in the settings menu.
# Author:      CliveS & Claude Opus 5.5
# Date:        27-09-2026
# Version:     1.0
#
# Uses a stub `indigo` module in the style of test_import_safety.py, and a fake
# IndigoSecrets module so the real file on the Indigo Mac is never read.

import importlib
import logging
import os
import sys
import types
import xml.etree.ElementTree as ET
from datetime import date, timedelta

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_PLUGIN = os.path.join(REPO, "TariffAnalyser.indigoPlugin", "Contents", "Server Plugin")
PLUGIN_ID = "com.clives.indigoplugin.tariffanalyser"
SIGEN_ID = "com.clives.indigoplugin.sigenergy-energy-manager"


class _Server:
    def __init__(self, folder):
        self.lines = []
        self.folder = folder

    def getInstallFolderPath(self):
        return self.folder

    def log(self, message, level=logging.INFO, **_kw):
        self.lines.append((message, level))


class _Dev:
    def __init__(self, type_id, states):
        self.deviceTypeId = type_id
        self.states = states


class _Devices:
    def __init__(self):
        self.by_plugin = {}

    def iter(self, plugin_id=None):
        return iter(self.by_plugin.get(plugin_id, []))


class _PluginBase:
    class StopThread(Exception):
        pass

    def __init__(self, plugin_id, display_name, version, prefs):
        self.pluginPrefs = prefs
        self.logger = logging.getLogger("tariffanalyser-test")


def _stub(folder):
    stub = types.ModuleType("indigo")
    stub.server = _Server(folder)
    stub.devices = _Devices()
    stub.PluginBase = _PluginBase
    stub.Dict = dict
    return stub


@pytest.fixture
def env(monkeypatch, tmp_path):
    for k in ("indigo", "plugin", "plugin_utils", "IndigoSecrets"):
        monkeypatch.delitem(sys.modules, k, raising=False)
    stub = _stub(str(tmp_path))
    monkeypatch.setitem(sys.modules, "indigo", stub)
    secrets = types.ModuleType("IndigoSecrets")      # empty unless a test fills it
    monkeypatch.setitem(sys.modules, "IndigoSecrets", secrets)
    monkeypatch.syspath_prepend(SERVER_PLUGIN)
    yield stub, secrets, tmp_path
    sys.modules.pop("plugin", None)


def _plugin(tmp_path, **prefs):
    mod = importlib.import_module("plugin")
    base = {"outputDir": str(tmp_path / "out"), "timestampEnabled": False}
    base.update(prefs)
    return mod, mod.Plugin(PLUGIN_ID, "Tariff Analyser", "test", base)


def _warnings(stub):
    return [m for m, lvl in stub.server.lines if lvl == logging.WARNING]


# --- IndigoSecrets per key --------------------------------------------------

def test_secrets_file_missing_some_keys_still_supplies_the_others(env):
    stub, secrets, tmp = env
    secrets.OCTOPUS_API_KEY = "key-from-file"
    secrets.OCTOPUS_MPAN = "1234567890123"
    # No serial, export or gas lines at all. Before v1.10 the grouped import
    # failed on the first missing name and ALL seven fell back to PluginConfig.
    mod, p = _plugin(tmp, octopusSerial="serial-from-dialog")
    cfg = p._build_octopus_config()
    assert cfg["api_key"] == "key-from-file"
    assert cfg["mpan"] == "1234567890123"
    assert cfg["serial"] == "serial-from-dialog"
    assert cfg["mprn"] == ""
    assert p._secrets_status_line() == "Loaded (from IndigoSecrets.py)"


# --- the scheduled comparison fetches missing Agile prices -----------------

def _action_setup(monkeypatch, mod, p, tmp):
    db = tmp / "energy_timeseries.db"
    db.write_text("")
    p.pluginPrefs["dbPath"] = str(db)
    made = []
    monkeypatch.setattr(mod.tariff_engine, "run_comparison",
                        lambda **kw: {"slots": 48, "days": 1, "results": [],
                                      "raw_totals": {}, "kw": kw})
    monkeypatch.setattr(mod.report_generator, "generate_report",
                        lambda *a, **k: (made.append(a) or str(tmp / "r.html"), None))
    return made


class _Action:
    def __init__(self, props):
        self.props = props


def test_action_fetches_agile_prices_when_the_stored_ones_fall_short(env, monkeypatch):
    stub, _secrets, tmp = env
    mod, p = _plugin(tmp)
    made = _action_setup(monkeypatch, mod, p, tmp)
    fetched = []
    monkeypatch.setattr(mod.octopus_prices, "fetch_agile_prices",
                        lambda db, region, a, b, log_fn=None: fetched.append((region, a, b)) or (0, 0))
    p.actionGenerateReport(_Action({"reportDays": "7"}))
    assert len(fetched) == 1                  # empty cache -> fetched before pricing
    assert fetched[0][2] == date.today() - timedelta(days=1)   # period ends yesterday
    assert made, "report not generated"


def test_action_skips_the_fetch_when_prices_already_cover_the_period(env, monkeypatch):
    stub, _secrets, tmp = env
    mod, p = _plugin(tmp)
    _action_setup(monkeypatch, mod, p, tmp)
    monkeypatch.setattr(mod.octopus_prices, "missing_days", lambda *a: 0)
    monkeypatch.setattr(mod.octopus_prices, "fetch_agile_prices",
                        lambda *a, **k: pytest.fail("fetched although covered"))
    p.actionGenerateReport(_Action({"reportDays": "7"}))


def test_action_fetch_failure_is_logged_and_the_report_still_made(env, monkeypatch):
    stub, _secrets, tmp = env
    mod, p = _plugin(tmp)
    made = _action_setup(monkeypatch, mod, p, tmp)

    def boom(*a, **k):
        raise OSError("network down")
    monkeypatch.setattr(mod.octopus_prices, "fetch_agile_prices", boom)
    p.actionGenerateReport(_Action({"reportDays": "7"}))
    assert any("network down" in w for w in _warnings(stub))
    assert made, "a failed price fetch stopped the report"


# --- Energy Summary export header --------------------------------------------

def test_export_label_names_the_chosen_tariff_and_its_real_price(env):
    _stub_, _secrets, tmp = env
    _mod, p = _plugin(tmp, exportTariffKey="seg_min")
    assert p._export_label() == "SEG Minimum (Ofgem floor) at 1.63p"
    p.pluginPrefs["exportTariffKey"] = "agile_outgoing"
    label = p._export_label()
    assert label.startswith("Octopus Agile Outgoing") and "12p" in label


# --- recorded tariff name from SigenEnergyManager ---------------------------

def test_current_tariff_name_read_from_the_tariff_monitor(env):
    stub, _secrets, tmp = env
    _mod, p = _plugin(tmp)
    assert p._current_tariff_name() == ""
    stub.devices.by_plugin[SIGEN_ID] = [
        _Dev("batteryManager", {}),
        _Dev("tariffMonitor", {"tariffActive": "Octopus Flux (forced)"}),
    ]
    assert p._current_tariff_name() == "Octopus Flux"


# --- optional settings -------------------------------------------------------

def test_new_settings_default_to_none(env):
    _stub_, _secrets, tmp = env
    _mod, p = _plugin(tmp)
    cfg = p._build_octopus_config()
    assert cfg["tracker_product"] == ""
    assert cfg["solar_install_date"] is None


def test_settings_reach_the_collection_config(env):
    _stub_, _secrets, tmp = env
    _mod, p = _plugin(tmp, trackerProduct="SILVER-25-04-11", solarInstallDate="2026-03-13",
                      octopusRegion="K")
    cfg = p._build_octopus_config()
    assert cfg["tracker_product"] == "SILVER-25-04-11"
    assert cfg["solar_install_date"] == date(2026, 3, 13)
    assert cfg["region"] == "K"


def test_dialog_refuses_a_bad_date_and_tidies_the_product_code(env):
    _stub_, _secrets, tmp = env
    _mod, p = _plugin(tmp)
    result = p.validatePrefsConfigUi({"solarInstallDate": "March", "trackerProduct": ""})
    assert result[0] is False and "solarInstallDate" in result[2]
    ok, values = p.validatePrefsConfigUi({"solarInstallDate": "",
                                          "trackerProduct": "e-1r-silver-25-04-11-f"})
    assert ok is True and values["trackerProduct"] == "SILVER-25-04-11"


# --- region letters ----------------------------------------------------------

def test_region_menu_uses_the_octopus_letters():
    tree = ET.parse(os.path.join(SERVER_PLUGIN, "PluginConfig.xml"))
    field = next(f for f in tree.iter("Field") if f.get("id") == "octopusRegion")
    labels = {o.get("value"): o.text.split(" - ", 1)[1] for o in field.iter("Option")}
    assert labels == {
        "A": "Eastern England", "B": "East Midlands", "C": "London",
        "D": "Merseyside and North Wales", "E": "West Midlands",
        "F": "North East England", "G": "North West England",
        "H": "Southern England", "J": "South East England",
        "K": "South Wales", "L": "South West England", "M": "Yorkshire",
        "N": "South Scotland", "P": "North Scotland",
    }
