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
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta

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
        CREATE TABLE IF NOT EXISTS standing_charges (
            tariff_key  TEXT NOT NULL,
            region      TEXT NOT NULL,
            product     TEXT NOT NULL,
            valid_from  TEXT NOT NULL,   -- local time, YYYY-MM-DDTHH:MM:SS
            valid_to    TEXT,            -- local time; NULL = still current
            p_day       REAL NOT NULL,   -- pence a day, VAT included
            fetched_at  REAL NOT NULL,   -- epoch seconds of the fetch
            PRIMARY KEY (tariff_key, region, valid_from)
        );
    """)
    # NB: a fetch_log table was declared here historically but never read or
    # written — removed (re-fetch is driven by _build_periods counting existing
    # slots). Existing DBs keep the empty table harmlessly.
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


def missing_days(db_path, region, date_from, date_to):
    """Number of days in date_from..date_to whose stored Agile import or export
    prices are short (the same test fetch_agile_prices uses to decide what to
    fetch). 0 means the stored prices already cover the period."""
    days = set()
    for direction in ("import", "export"):
        existing = _existing_slots(db_path, region, direction)
        for period_from, _period_to in _build_periods(date_from, date_to, existing):
            days.add(period_from)
    return len(days)


def get_coverage(db_path, region):
    """Return (earliest_import, latest_import, earliest_export, latest_export)."""
    if not os.path.exists(db_path):
        return None, None, None, None
    con = None
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
        return (imp[0], imp[1], exp[0], exp[1]) if imp else (None, None, None, None)
    except sqlite3.Error:
        # Narrowed from bare Exception; connection closed in finally (was leaked
        # on the error path before).
        return None, None, None, None
    finally:
        if con is not None:
            con.close()


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
        # Collect every candidate whose display name contains the keyword, then
        # pick the most RECENT (max available_from) rather than the first the
        # API happens to return — Octopus lists retired Agile products too, and
        # taking the first could pin an old tariff code.
        candidates = []
        for product in data.get("results", []):
            if keyword.lower() in product.get("display_name", "").lower():
                candidates.append(product)
        if not candidates:
            return None, None
        candidates.sort(key=lambda p: p.get("available_from", "") or "", reverse=True)
        if len(candidates) > 1:
            log_fn(f"Agile {direction}: {len(candidates)} product candidates matched "
                   f"'{keyword}' — using most recent {candidates[0].get('code')}")
        code   = candidates[0]["code"]
        tariff = f"E-1R-{code}-{region}"   # tariff code pattern
        return code, tariff
    except Exception as exc:
        log_fn(f"Product discovery failed: {exc}", level="WARNING")
    return None, None


# ---------------------------------------------------------------------------
# Standing charges (v1.11)
# ---------------------------------------------------------------------------
# Octopus publishes each tariff's standing charge for every region, with the
# dates each figure applies, on the same public price list as the Agile prices.
# The comparison tariffs are found by display name on the products list, the
# way _discover_product finds Agile, and the figures are kept in this database,
# fetched again at most once a day. Until v1.11 every Octopus tariff carried a
# fixed 53.35p a day, which was nobody's region.

STANDING_REFRESH_SECONDS = 24 * 3600


def standing_charges_by_day(db_path, region, date_from, date_to, names=None,
                            products=None, log_fn=None, now=None):
    """Octopus's standing charge for each day of date_from..date_to.

    names:    {key: display name of the variable Octopus import product}, e.g.
              {"go": "Octopus Go"}; the product code is looked up by that exact
              name (ignoring case), so "Octopus Go" never picks up "Intelligent
              Octopus Go" or a fixed deal.
    products: {key: product code} for a tariff whose code is already known
              (the Tracker product setting); no lookup.
    now:      epoch seconds, for tests.

    Returns {key: {"YYYY-MM-DD": pence_a_day}}. A key whose figures could not
    be fetched and were never saved is left out, and the caller uses its own
    figure. Each failure is one WARNING naming the tariff.
    """
    def _log(msg, level="INFO"):
        if log_fn:
            log_fn(f"[Standing] {msg}", level=level)

    names    = dict(names or {})
    products = dict(products or {})
    keys     = list(dict.fromkeys(list(names) + list(products)))
    if not keys:
        return {}
    now = time.time() if now is None else now
    init_agile_db(db_path)

    discovered = None       # {display name lower: code}, fetched once if needed
    discover_error = None
    for key in keys:
        label   = names.get(key) or products.get(key) or key
        fetched = _standing_fetched_at(db_path, key, region)
        if fetched is not None and now - fetched < STANDING_REFRESH_SECONDS:
            continue
        try:
            product = products.get(key)
            if not product:
                if discovered is None and discover_error is None:
                    try:
                        discovered = _discover_import_products()
                    except Exception as exc:
                        discover_error = exc
                if discover_error is not None:
                    raise discover_error
                product = discovered.get(label.lower())
                if not product:
                    raise LookupError(f"Octopus has no current tariff called '{label}'")
            periods = parse_standing_charges(_api_get_all(
                f"{_API_BASE}/products/{product}/electricity-tariffs/"
                f"E-1R-{product}-{region}/standing-charges/?page_size={_PAGE_SIZE}"))
            if not periods:
                raise LookupError("Octopus returned no standing charges")
            _store_standing(db_path, key, region, product, periods, now)
            _log(f"{label} standing charge for region {region}: "
                 f"{periods[0][2]:.2f}p a day now ({product})")
        except Exception as exc:
            saved = ("the figures saved from the last fetch" if fetched is not None
                     else "the plugin's own figure")
            _log(f"Could not fetch the {label} standing charge for region {region} "
                 f"from Octopus ({exc}). Using {saved}.", level="WARNING")

    result = {}
    for key in keys:
        periods = _load_standing(db_path, key, region)
        if not periods:
            continue
        days = {}
        cur = date_from
        while cur <= date_to:
            ds = cur.strftime("%Y-%m-%d")
            p = standing_for_day(periods, ds)
            if p is not None:
                days[ds] = p
            cur += timedelta(days=1)
        if days:
            result[key] = days
    return result


def parse_standing_charges(results):
    """[(valid_from_local, valid_to_local or None, pence_a_day), ...] from the
    Octopus standing-charges results, newest first. Where Octopus gives
    separate direct-debit and other figures, the direct-debit one is kept."""
    items = [r for r in (results or []) if isinstance(r, dict)]
    methods = {r.get("payment_method") for r in items}
    if "DIRECT_DEBIT" in methods:
        items = [r for r in items if r.get("payment_method") in (None, "", "DIRECT_DEBIT")]
    periods = []
    for item in items:
        raw_from = item.get("valid_from")
        try:
            value = float(item.get("value_inc_vat"))
        except (TypeError, ValueError):
            continue
        if not raw_from or value != value or value < 0:
            continue
        raw_to = item.get("valid_to")
        periods.append((_utc_to_local(raw_from),
                        _utc_to_local(raw_to) if raw_to else None,
                        value))
    periods.sort(key=lambda p: p[0], reverse=True)
    return periods


def standing_for_day(periods, day_str):
    """The standing charge in force at midday on day_str (local), or None."""
    midday = f"{day_str}T12:00:00"
    for valid_from, valid_to, value in periods:
        if valid_from <= midday and (valid_to is None or midday < valid_to):
            return value
    return None


def _discover_import_products():
    """{display name lower: product code} for Octopus's variable import
    products, the most recent where two share a name. Raises on failure."""
    data = _api_get(f"{_API_BASE}/products/?is_variable=true&brand=OCTOPUS_ENERGY"
                    f"&page_size=100")
    best = {}
    for product in data.get("results", []):
        name = str(product.get("display_name", "")).strip().lower()
        code = product.get("code")
        if not name or not code or product.get("direction", "IMPORT") != "IMPORT":
            continue
        when = product.get("available_from", "") or ""
        if name not in best or when > best[name][0]:
            best[name] = (when, code)
    return {name: code for name, (_when, code) in best.items()}


def _api_get_all(url):
    """Every result of a paged Octopus list."""
    results = []
    while url and len(results) < 10000:
        data = _api_get(url)
        results.extend(data.get("results", []))
        url = data.get("next")
    return results


def _standing_fetched_at(db_path, key, region):
    con = None
    try:
        con = sqlite3.connect(db_path)
        row = con.execute(
            "SELECT MAX(fetched_at) FROM standing_charges WHERE tariff_key=? AND region=?",
            (key, region)).fetchone()
        return row[0] if row and row[0] is not None else None
    except sqlite3.Error:
        return None
    finally:
        if con is not None:
            con.close()


def _store_standing(db_path, key, region, product, periods, now):
    """Replace the saved figures for this tariff and region with a fresh set."""
    con = sqlite3.connect(db_path)
    try:
        con.execute("DELETE FROM standing_charges WHERE tariff_key=? AND region=?",
                    (key, region))
        con.executemany(
            "INSERT OR REPLACE INTO standing_charges "
            "(tariff_key, region, product, valid_from, valid_to, p_day, fetched_at) "
            "VALUES (?,?,?,?,?,?,?)",
            [(key, region, product, vf, vt, p, now) for (vf, vt, p) in periods])
        con.commit()
    finally:
        con.close()


def _load_standing(db_path, key, region):
    con = None
    try:
        con = sqlite3.connect(db_path)
        rows = con.execute(
            "SELECT valid_from, valid_to, p_day FROM standing_charges "
            "WHERE tariff_key=? AND region=? ORDER BY valid_from DESC",
            (key, region)).fetchall()
        return [(r[0], r[1], r[2]) for r in rows]
    except sqlite3.Error:
        return []
    finally:
        if con is not None:
            con.close()


def _existing_slots(db_path, region, direction):
    """Return set of slot_start strings already in the DB for this region/direction."""
    table = "agile_import" if direction == "import" else "agile_export"
    if not os.path.exists(db_path):
        return set()
    con = None
    try:
        con   = sqlite3.connect(db_path)
        rows  = con.execute(
            f"SELECT slot_start FROM {table} WHERE region=?", (region,)
        ).fetchall()
        return {r[0] for r in rows}
    except sqlite3.Error:
        return set()
    finally:
        if con is not None:
            con.close()


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
