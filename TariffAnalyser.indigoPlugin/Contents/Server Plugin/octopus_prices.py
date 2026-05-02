#! /usr/bin/env python
# -*- coding: utf-8 -*-
# Filename:    octopus_prices.py
# Description: Fetches and caches Octopus Agile half-hourly import/export
#              prices from the public Octopus Energy REST API.
#              No authentication required.
# Author:      CliveS & Claude Sonnet 4.6
# Date:        02-05-2026
# Version:     1.0

import json
import os
import sqlite3
import urllib.request
import urllib.error
from datetime import datetime, date, timedelta, timezone

# Octopus public API base
_API_BASE = "https://api.octopus.energy/v1"

# Page size — Octopus returns max 1500 results per page
_PAGE_SIZE = 1500


def init_agile_db(db_path):
    """Create agile_prices.db schema if it does not exist."""
    con = sqlite3.connect(db_path)
    con.executescript("""
        CREATE TABLE IF NOT EXISTS agile_import (
            slot_start  TEXT NOT NULL,
            region      TEXT NOT NULL,
            price_p     REAL NOT NULL,
            PRIMARY KEY (slot_start, region)
        );
        CREATE TABLE IF NOT EXISTS agile_export (
            slot_start  TEXT NOT NULL,
            region      TEXT NOT NULL,
            price_p     REAL NOT NULL,
            PRIMARY KEY (slot_start, region)
        );
        CREATE TABLE IF NOT EXISTS fetch_log (
            direction   TEXT NOT NULL,
            region      TEXT NOT NULL,
            fetched_to  TEXT NOT NULL,
            PRIMARY KEY (direction, region)
        );
    """)
    con.commit()
    con.close()


def fetch_agile_prices(db_path, region, date_from, date_to, log_fn=None):
    """Fetch and cache Agile import and export prices for date_from..date_to.

    Only fetches slots not already in the DB.  Discovers the current Agile
    product code dynamically from the Octopus products API.

    Args:
        db_path:   path to agile_prices.db
        region:    Octopus region letter (e.g. 'F' for North East)
        date_from: date object (inclusive)
        date_to:   date object (inclusive)
        log_fn:    optional callable(message, level='INFO')

    Returns (import_fetched, export_fetched) counts of new rows inserted.
    """
    def _log(msg, level="INFO"):
        if log_fn:
            log_fn(f"[AgileAPI] {msg}", level=level)

    init_agile_db(db_path)

    imp_count = _fetch_direction(db_path, region, date_from, date_to,
                                 "import", _log)
    exp_count = _fetch_direction(db_path, region, date_from, date_to,
                                 "export", _log)
    return imp_count, exp_count


def get_coverage(db_path, region):
    """Return (earliest_import, latest_import, earliest_export, latest_export)."""
    if not os.path.exists(db_path):
        return None, None, None, None
    try:
        con = sqlite3.connect(db_path)
        imp = con.execute(
            "SELECT MIN(slot_start), MAX(slot_start) FROM agile_import WHERE region=?",
            (region,)
        ).fetchone()
        exp = con.execute(
            "SELECT MIN(slot_start), MAX(slot_start) FROM agile_export WHERE region=?",
            (region,)
        ).fetchone()
        con.close()
        return (imp[0], imp[1], exp[0], exp[1]) if imp else (None, None, None, None)
    except Exception:
        return None, None, None, None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fetch_direction(db_path, region, date_from, date_to, direction, log_fn):
    """Fetch one direction (import or export) from the Octopus API."""
    product_code, tariff_code = _discover_product(region, direction, log_fn)
    if not product_code:
        log_fn(f"Could not discover Agile {direction} product for region {region}",
               level="WARNING")
        return 0

    log_fn(f"Agile {direction}: product={product_code}  tariff={tariff_code}")

    # Find which slots are already in the DB for this range
    existing = _existing_slots(db_path, region, direction)

    # Build list of UTC period windows to fetch (one per day)
    periods = _build_periods(date_from, date_to, existing)
    if not periods:
        log_fn(f"Agile {direction}: already up to date for requested range")
        return 0

    table    = "agile_import" if direction == "import" else "agile_export"
    inserted = 0

    for (period_from, period_to) in periods:
        url = (
            f"{_API_BASE}/products/{product_code}"
            f"/electricity-tariffs/{tariff_code}/standard-unit-rates/"
            f"?page_size={_PAGE_SIZE}"
            f"&period_from={period_from}"
            f"&period_to={period_to}"
        )
        try:
            data = _api_get(url)
        except Exception as exc:
            log_fn(f"Agile {direction} fetch error: {exc}", level="WARNING")
            continue

        results = data.get("results", [])
        if not results:
            continue

        rows = []
        for item in results:
            raw_ts  = item.get("valid_from", "")
            price_p = item.get("value_inc_vat")
            if not raw_ts or price_p is None:
                continue
            # Convert UTC ISO to local ISO (UK = UTC in winter, UTC+1 in summer)
            slot_local = _utc_to_local(raw_ts)
            rows.append((slot_local, region, float(price_p)))

        if rows:
            con = sqlite3.connect(db_path)
            con.executemany(
                f"INSERT OR IGNORE INTO {table} (slot_start, region, price_p) VALUES (?,?,?)",
                rows
            )
            con.commit()
            con.close()
            inserted += len(rows)
            log_fn(f"Agile {direction}: inserted {len(rows)} rows "
                   f"({period_from[:10]} to {period_to[:10]})")

    return inserted


def _discover_product(region, direction, log_fn):
    """Return (product_code, tariff_code) for the current Agile product."""
    keyword = "Agile Octopus" if direction == "import" else "Agile Outgoing Octopus"
    try:
        url  = f"{_API_BASE}/products/?is_variable=true&brand=OCTOPUS_ENERGY"
        data = _api_get(url)
        for product in data.get("results", []):
            if keyword.lower() in product.get("display_name", "").lower():
                code = product["code"]
                # Tariff code pattern: E-1R-{CODE}-{REGION}
                tariff = f"E-1R-{code}-{region}"
                return code, tariff
    except Exception as exc:
        log_fn(f"Product discovery failed: {exc}", level="WARNING")
    return None, None


def _existing_slots(db_path, region, direction):
    """Return set of slot_start strings already in the DB for this region/direction."""
    table = "agile_import" if direction == "import" else "agile_export"
    if not os.path.exists(db_path):
        return set()
    try:
        con   = sqlite3.connect(db_path)
        rows  = con.execute(
            f"SELECT slot_start FROM {table} WHERE region=?", (region,)
        ).fetchall()
        con.close()
        return {r[0] for r in rows}
    except Exception:
        return set()


def _build_periods(date_from, date_to, existing_slots):
    """Return list of (period_from_utc, period_to_utc) strings for missing days."""
    periods = []
    cur = date_from
    while cur <= date_to:
        # Check if this day has any data (48 slots expected)
        day_str = cur.strftime("%Y-%m-%d")
        day_slots = sum(1 for s in existing_slots if s.startswith(day_str))
        if day_slots < 40:  # tolerate a few missing slots at day boundaries
            # UTC period: previous day 23:00 to this day 23:00 (covers BST/GMT)
            utc_from = (cur - timedelta(days=1)).strftime("%Y-%m-%dT23:00:00Z")
            utc_to   = cur.strftime("%Y-%m-%dT23:00:00Z")
            periods.append((utc_from, utc_to))
        cur += timedelta(days=1)
    return periods


def _api_get(url):
    """Simple GET to Octopus API, returns parsed JSON."""
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json",
                 "User-Agent": "IndigoTariffAnalyser/1.0"}
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _utc_to_local(utc_str):
    """Convert '2026-05-01T00:00:00Z' to local time ISO without timezone suffix.

    Uses Python's timezone-aware datetime with UTC, then converts to local.
    Returns 'YYYY-MM-DDTHH:MM:SS' in local time.
    """
    try:
        dt_utc = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        dt_local = dt_utc.astimezone(tz=None)
        return dt_local.strftime("%Y-%m-%dT%H:%M:%S")
    except Exception:
        return utc_str[:19]  # fallback: strip timezone marker
