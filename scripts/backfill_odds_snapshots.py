"""Seed the odds journal once from the current market_totals.csv file."""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from app.database import DATABASE_PATH, initialise_database


PATH = Path("data/market_totals.csv")


def main() -> None:
    if not PATH.exists():
        raise SystemExit("data/market_totals.csv est absent.")
    initialise_database()
    with PATH.open(encoding="utf-8", newline="") as handle, sqlite3.connect(DATABASE_PATH) as connection:
        rows = list(csv.DictReader(handle))
        connection.executemany(
            """INSERT OR IGNORE INTO odds_snapshots
               (game_id, bookmaker, market, line, over_price, under_price, captured_at)
               VALUES (?, ?, 'total', ?, ?, ?, ?)""",
            [(r["game_id"], r["book"], float(r["total_line"]), r.get("over_price") or None, r.get("under_price") or None, r["captured_at"]) for r in rows],
        )
    print(f"Instantané archivé : {len(rows)} lignes")


if __name__ == "__main__":
    main()
