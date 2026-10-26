#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    test_calendar_and_compatibility.py
# Description: Calendar pricing, honest ranking and shared-data compatibility.
# Author:      CliveS & Codex
# Date:        26-10-2026
# Version:     1.0

import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

SERVER = Path(__file__).resolve().parents[1] / 'TariffAnalyser.indigoPlugin/Contents/Server Plugin'
sys.path.insert(0, str(SERVER))
import tariff_engine as te
import report_generator as rg

UK = ZoneInfo('Europe/London')


def make_db(tmp_path, day, *, offsets=True, step=30):
    path = tmp_path / 'energy_timeseries.db'
    con = sqlite3.connect(path)
    con.execute('''CREATE TABLE halfhourly (
        slot_start TEXT, slot_end TEXT, grid_import_kwh REAL, grid_export_kwh REAL,
        pv_kwh REAL, home_kwh REAL, battery_soc_start_pct REAL, battery_soc_end_pct REAL,
        battery_net_kwh REAL, tracker_price_p REAL, manager_action TEXT)''')
    con.execute('CREATE TABLE daily_summary(date TEXT, octopus_import_kwh REAL)')
    con.execute('INSERT INTO daily_summary VALUES (?, ?)', (str(day), 12.3))
    t = datetime.combine(day, datetime.min.time(), UK).astimezone(timezone.utc)
    end = datetime.combine(day + timedelta(days=1), datetime.min.time(), UK).astimezone(timezone.utc)
    while t < end:
        nxt = min(t + timedelta(minutes=step), end)
        a, b = t.astimezone(UK), nxt.astimezone(UK)
        if not offsets:
            a, b = a.replace(tzinfo=None), b.replace(tzinfo=None)
        con.execute('INSERT INTO halfhourly VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                    (a.isoformat(), b.isoformat(), 1, 0, 0, 1, 50, 50, 0, 20, ''))
        t = nxt
    con.commit()
    con.close()
    return path


def compare(path, day, **kwargs):
    return te.run_comparison(str(path), '', 'F', day, day,
                             recorded_standing={str(day): 60}, recorded_export={},
                             import_tariff_keys=kwargs.pop('import_tariff_keys', ['tracker']), **kwargs)


@pytest.mark.parametrize('day', [date(2026, 3, 29), date(2026, 10, 25), date(2026, 10, 26)])
@pytest.mark.parametrize('step', [30, 37])
def test_full_calendar_day_costs_one_standing_charge(tmp_path, day, step):
    result = compare(make_db(tmp_path, day, step=step), day)
    assert result['results'][0]['standing_charge_p'] == 60
    assert result['data_coverage_pct'] == 100
    assert result['standing_day_fractions'] == {str(day): 1}
    assert result['ambiguous_time_rows'] == 0


def test_partial_day_and_overlaps_are_charged_once():
    day = date(2026, 10, 26)
    a = te.local_epoch('2026-10-26T00:00:00')
    spans = [(a, a + 6*3600), (a + 3*3600, a + 12*3600)]
    assert te.covered_day_fractions(spans, day, day) == {str(day): 0.5}


def test_midnight_crossing_is_split_at_each_days_rate(tmp_path):
    day = date(2026, 10, 26)
    path = make_db(tmp_path, day)
    con = sqlite3.connect(path)
    con.execute('DELETE FROM halfhourly')
    con.execute('INSERT INTO halfhourly VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                ('2026-10-26T23:30:00', '2026-10-27T00:30:00', 1, 0, 0, 1, 50, 50, 0, 20, ''))
    con.commit(); con.close()
    result = te.run_comparison(str(path), '', 'F', day, day + timedelta(days=1),
                              import_tariff_keys=['tracker'], recorded_export={},
                              recorded_standing={'2026-10-26': 48, '2026-10-27': 96})
    assert result['results'][0]['standing_charge_p'] == 3


def test_naive_clock_change_data_is_explicitly_uncertain(tmp_path):
    day = date(2026, 10, 25)
    result = compare(make_db(tmp_path, day, offsets=False), day)
    assert result['ambiguous_time_rows'] > 0
    path, err = rg.generate_report(result, day, day, str(tmp_path), 'Example export')
    assert err is None
    assert 'exact timing cannot be' in Path(path).read_text()


def test_illustrative_rows_keep_values_but_never_win_report(tmp_path):
    day = date(2026, 10, 26)
    path = make_db(tmp_path, day)
    result = compare(path, day, import_tariff_keys=['tracker', 'edf_fixed'])
    example = next(r for r in result['results'] if r['tariff_key'] == 'edf_fixed')
    assert example['total_cost_p'] is not None
    assert example['illustrative'] and not example['ranking_eligible']
    report, err = rg.generate_report(result, day, day, str(tmp_path), 'Example export')
    assert err is None
    html = Path(report).read_text()
    assert 'illustrative, not ranked' in html
    assert 'not a recommendation to switch' in html
    assert 'Self-sufficiency' not in html
    assert 'crossing a price change' in html


def test_only_illustrative_rows_render_without_recommendation(tmp_path):
    day = date(2026, 10, 26)
    result = compare(make_db(tmp_path, day), day, import_tariff_keys=['edf_fixed'])
    report, err = rg.generate_report(result, day, day, str(tmp_path), 'Example export')
    assert err is None
    assert '<tr class="rank-row rank-best">' not in Path(report).read_text()


def test_shared_database_and_old_result_fields_are_preserved(tmp_path):
    day = date(2026, 10, 26)
    path = make_db(tmp_path, day)
    before = path.read_bytes()
    result = compare(path, day)
    assert path.read_bytes() == before
    assert {'slots', 'days', 'common_slots', 'coverage_pct', 'results', 'monthly',
            'monthly_common', 'raw_totals', 'rate_sources', 'export_sources'} <= result.keys()
    assert {'tariff_key', 'tariff_name', 'import_cost_p', 'export_revenue_p',
            'net_cost_p', 'standing_charge_p', 'total_cost_p', 'coverage_pct',
            'own_coverage_pct', 'insufficient_data'} <= result['results'][0].keys()


def test_disjoint_price_coverage_never_ranks_zero_cost(tmp_path, monkeypatch):
    day = date(2026, 10, 26)
    path = make_db(tmp_path, day, offsets=False)
    con = sqlite3.connect(path)
    con.execute("UPDATE halfhourly SET tracker_price_p=NULL WHERE slot_start >= '2026-10-26T12:00:00'")
    con.commit(); con.close()
    prices = {f'2026-10-26T{h:02d}:{m:02d}:00': 10 for h in range(12, 24) for m in (0, 30)}
    monkeypatch.setattr(te, '_load_agile_prices', lambda *a: prices)
    result = compare(path, day, import_tariff_keys=['tracker', 'agile'])
    assert result['common_slots'] == 0
    assert all(r['insufficient_data'] and r['total_cost_p'] is None for r in result['results'])
    report, err = rg.generate_report(result, day, day, str(tmp_path), 'Example export')
    assert err is None
    assert '<tr class="rank-row rank-best">' not in Path(report).read_text()


def test_legacy_missing_end_keeps_half_hour_fallback():
    a = te.local_epoch('2026-10-26T12:00:00')
    assert te._row_span('2026-10-26T12:00:00', '') == (a, a + 1800)


def test_without_actual_baseline_does_not_claim_savings(tmp_path):
    day = date(2026, 10, 26)
    result = compare(make_db(tmp_path, day), day, import_tariff_keys=['edf_fixed'])
    report, err = rg.generate_report(result, day, day, str(tmp_path), 'Example export')
    assert err is None
    html = Path(report).read_text()
    assert 'actual cost unavailable' in html
    assert 'more by' not in html and 'cheaper by' not in html


def test_action_ids_callbacks_and_parameter_names_remain_compatible():
    import ast
    import xml.etree.ElementTree as ET
    actions = ET.parse(SERVER / 'Actions.xml').getroot()
    expected = {'generateReport': ('actionGenerateReport', {'reportDays'}),
                'updatePrices': ('actionUpdatePrices', set()),
                'updateDailySummary': ('actionUpdateDailySummary', {'rollingDays'}),
                'energySummary': ('actionEnergySummary', set())}
    actual = {a.get('id'): (a.findtext('CallbackMethod'),
                           {f.get('id') for f in a.findall('.//Field')}) for a in actions}
    assert actual == expected
    plugin = next(n for n in ast.parse((SERVER / 'plugin.py').read_text()).body
                  if isinstance(n, ast.ClassDef) and n.name == 'Plugin')
    methods = {n.name for n in plugin.body if isinstance(n, ast.FunctionDef)}
    assert {callback for callback, fields in expected.values()} <= methods
