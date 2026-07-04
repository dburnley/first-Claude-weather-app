"""Step 4: SQLite state per truck_search_config.json's "state" block.

Dedupes listings by VIN across runs and records a price history so
score_listings.py's price_drop_history component has real data to work
with instead of the "unavailable" stub from step 3.
"""
import os
import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    vin TEXT PRIMARY KEY,
    make TEXT,
    model TEXT,
    year INTEGER,
    first_seen_at TEXT,
    last_seen_at TEXT,
    current_price REAL
);
CREATE TABLE IF NOT EXISTS price_history (
    vin TEXT,
    price REAL,
    seen_at TEXT
);
"""


def db_path_from_config(config):
    return os.path.join(os.path.dirname(__file__), config["state"]["db_file"])


def connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def upsert_listing(conn, vin, make, model, year, price):
    """Record this run's sighting of `vin`. Returns is_new / price_changed / previous_price."""
    now = datetime.now(timezone.utc).isoformat()
    row = conn.execute("SELECT current_price FROM listings WHERE vin = ?", (vin,)).fetchone()

    if row is None:
        conn.execute(
            "INSERT INTO listings (vin, make, model, year, first_seen_at, last_seen_at, current_price) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (vin, make, model, year, now, now, price),
        )
        conn.execute("INSERT INTO price_history (vin, price, seen_at) VALUES (?, ?, ?)", (vin, price, now))
        conn.commit()
        return {"is_new": True, "price_changed": False, "previous_price": None}

    previous_price = row[0]
    price_changed = price is not None and previous_price is not None and price != previous_price

    conn.execute("UPDATE listings SET last_seen_at = ?, current_price = ? WHERE vin = ?", (now, price, vin))
    if price_changed:
        conn.execute("INSERT INTO price_history (vin, price, seen_at) VALUES (?, ?, ?)", (vin, price, now))
    conn.commit()

    return {"is_new": False, "price_changed": price_changed, "previous_price": previous_price}


def price_drop_pct(conn, vin):
    """Fraction dropped from first recorded price to latest, clipped to [0, 1].
    None if we don't have at least two price points yet for this VIN."""
    rows = conn.execute(
        "SELECT price FROM price_history WHERE vin = ? ORDER BY seen_at ASC", (vin,)
    ).fetchall()
    prices = [r[0] for r in rows if r[0] is not None]
    if len(prices) < 2 or prices[0] <= 0:
        return None
    return max(0.0, min(1.0, (prices[0] - prices[-1]) / prices[0]))
