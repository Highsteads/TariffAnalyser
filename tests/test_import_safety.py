#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_import_safety.py
# Description: plugin.py must import without talking to the Indigo server, and a
#              server that does not answer at startup must leave the plugin
#              running with a WARNING, not kill it.
# Author:      CliveS & Claude Opus 5.5
# Date:        23-09-2026
# Version:     1.0
#
# Why: on 11-Sep-2026 six plugins were restarted within five seconds and Tariff
# Analyser died at import with `ServerCommunicationError -- timeout waiting for
# response`. plugin.py called indigo.server.getInstallFolderPath() at MODULE
# level to build the default SigenEnergyManager DB path, and a module-level
# failure has no second chance: the host never reaches startup(), so nothing
# can log, retry or recover. v1.9.5 moved the call into the plugin instance.
#
# The stub `indigo` below makes every server call raise unless a test says
# otherwise, so any module-level call anywhere in plugin.py fails the import.

import importlib
import logging
import os
import sys
import tempfile
import types

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_PLUGIN = os.path.join(REPO, "TariffAnalyser.indigoPlugin", "Contents", "Server Plugin")

SIGEN_ID = "com.clives.indigoplugin.sigenergy-energy-manager"
PLUGIN_ID = "com.clives.indigoplugin.tariffanalyser"


class _ServerTimeout(Exception):
    """Stands in for indigo's ServerCommunicationError."""


class _Server:
    def __init__(self):
        self.lines = []            # (message, level int)
        self.install_folder = None  # None -> every call raises

    def getInstallFolderPath(self):
        if self.install_folder is None:
            raise _ServerTimeout("timeout waiting for response")
        return self.install_folder

    def log(self, message, level=logging.INFO, **_kw):
        self.lines.append((message, level))


class _PluginBase:
    class StopThread(Exception):
        pass

    def __init__(self, plugin_id, display_name, version, prefs):
        self.pluginPrefs = prefs


def _install_stub():
    stub = types.ModuleType("indigo")
    stub.server = _Server()
    stub.PluginBase = _PluginBase
    stub.Dict = dict
    sys.modules["indigo"] = stub
    return stub


@pytest.fixture
def stub_indigo(monkeypatch):
    saved = {k: sys.modules.get(k) for k in ("indigo", "plugin", "plugin_utils")}
    for k in saved:
        sys.modules.pop(k, None)
    stub = _install_stub()
    monkeypatch.syspath_prepend(SERVER_PLUGIN)
    yield stub
    for k, v in saved.items():
        if v is None:
            sys.modules.pop(k, None)
        else:
            sys.modules[k] = v


def _import_plugin():
    return importlib.import_module("plugin")


def _make_plugin(mod, tmp):
    # outputDir in a temp folder: startup() creates it, and the default is the
    # real Perceptive Automation folder on this Mac.
    return mod.Plugin(PLUGIN_ID, "Tariff Analyser", "test",
                      {"outputDir": os.path.join(tmp, "out"), "timestampEnabled": False})


def test_import_makes_no_server_call(stub_indigo):
    """Importing plugin.py must succeed while every server call raises."""
    mod = _import_plugin()
    assert hasattr(mod, "Plugin")


def test_startup_survives_unanswered_server_and_warns(stub_indigo):
    mod = _import_plugin()
    with tempfile.TemporaryDirectory() as tmp:
        p = _make_plugin(mod, tmp)
        p.startup()                        # must not raise
        warnings = [m for m, lvl in stub_indigo.server.lines if lvl == logging.WARNING]
        assert warnings, "no WARNING logged when the install folder could not be resolved"
        assert any("install folder" in m for m in warnings)
        # The dependent features are off, not pointed at a bogus path.
        assert p._db_path() == ""
        assert p._agile_db_path() == ""
        # Warned once, not on every use.
        p._db_path()
        p._agile_db_path()
        assert len([m for m, lvl in stub_indigo.server.lines if lvl == logging.WARNING]) == 1


def test_resolves_later_once_server_answers(stub_indigo):
    mod = _import_plugin()
    with tempfile.TemporaryDirectory() as tmp:
        p = _make_plugin(mod, tmp)
        p.startup()
        assert p._db_path() == ""
        stub_indigo.server.install_folder = tmp
        expected = os.path.join(tmp, "Preferences", "Plugins", SIGEN_ID, "energy_timeseries.db")
        assert p._db_path() == expected


def test_paths_unchanged_when_server_answers(stub_indigo):
    """Behaviour is identical to v1.9.4 when the call succeeds."""
    mod = _import_plugin()
    with tempfile.TemporaryDirectory() as tmp:
        stub_indigo.server.install_folder = tmp
        p = _make_plugin(mod, tmp)
        p.startup()
        sigen_db = os.path.join(tmp, "Preferences", "Plugins", SIGEN_ID, "energy_timeseries.db")
        agile_db = os.path.join(tmp, "Preferences", "Plugins", PLUGIN_ID, "agile_prices.db")
        assert p._db_path() == sigen_db
        assert p._agile_db_path() == agile_db
        assert os.path.isfile(agile_db)    # startup created the Agile cache
        assert p._build_octopus_config()["timeseries_db"] == sigen_db
        assert not [m for m, lvl in stub_indigo.server.lines if lvl == logging.WARNING]


def test_configured_db_path_wins_without_server(stub_indigo):
    mod = _import_plugin()
    with tempfile.TemporaryDirectory() as tmp:
        p = _make_plugin(mod, tmp)
        p.pluginPrefs["dbPath"] = "/some/where/energy_timeseries.db"
        assert p._db_path() == "/some/where/energy_timeseries.db"
