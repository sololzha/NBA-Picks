"""Sync verified NBA totals from HoopsAPI into the local market-lines file.

The API key is read only from the HOOPS_API_KEY environment variable and is
never written to this repository or database.
"""

from __future__ import annotations

import csv
import json
import os
import sqlite3
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path

from app.database import DATABASE_PATH
from app.pick_journal import instant


API_URL = "https://hoopsapi.com/api/v1/games?" + urllib.parse.urlencode({"competition": "NBA"})
OUTPUT_PATH = Path("data/market_totals.csv")
PREFERRED_BOOKS = ("pinnacle", "fanduel")


def main() -> None:
    api_key = os.environ.get("HOOPS_API_KEY")
    if not api_key:
        raise SystemExit("HOOPS_API_KEY est absent. Définis-le temporairement avant de lancer la synchronisation.")

    request = urllib.request.Request(API_URL, headers={"Authorization": f"Bearer {api_key}"})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)

    with sqlite3.connect(DATABASE_PATH) as connection:
        scheduled = connection.execute(
            """SELECT game_id, home_team, away_team, start_time FROM games
               WHERE season_type = 'regular' AND home_points IS NULL"""
        ).fetchall()
    now = datetime.now(timezone.utc)
    def team_key(name):
        name = str(name).strip().casefold()
        return name.replace("los angeles clippers", "la clippers")

    rows = []
    snapshots = []
    captured_at = now.isoformat()
    for game in payload.get("games", []):
        provider_time = game.get("start_time")
        start = instant(provider_time)
        if start is None and isinstance(provider_time, str):
            start = instant(provider_time + "+00:00")
        if start is None or start <= now:
            continue
        match = [
            game_id for game_id, home, away, local_time in scheduled
            if (team_key(home), team_key(away)) == (team_key(game.get("home")), team_key(game.get("away")))
            and (local_start := instant(local_time)) is not None and local_start > now
            and abs((local_start - start).total_seconds()) <= 3600
        ]
        if len(match) != 1:
            continue
        game_id = match[0]
        full_time = game.get("periods", {}).get("ft", {})
        for bookmaker in PREFERRED_BOOKS:
            markets = full_time.get(bookmaker, {})
            for market, first, second in (("total", "over", "under"), ("moneyline", "home", "away")):
                prices = markets.get(market)
                if isinstance(prices, list):
                    prices = next(iter(prices), None)
                if not isinstance(prices, dict):
                    continue
                try:
                    line = float(prices["line"]) if market == "total" else 0.0
                    a, b = float(prices[first]), float(prices[second])
                except (KeyError, TypeError, ValueError):
                    continue
                if not all(map(isfinite, (line, a, b))) or min(a, b) <= 1:
                    continue
                snapshots.append((game_id, bookmaker, market, line, a, b, captured_at))
                if market == "total":
                    rows.append(dict(game_id=game_id, total_line=line, book=bookmaker,
                                     over_price=a, under_price=b, captured_at=captured_at))

    with OUTPUT_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["game_id", "total_line", "book", "over_price", "under_price", "captured_at"])
        writer.writeheader()
        writer.writerows(rows)
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.executemany(
            """INSERT OR IGNORE INTO odds_snapshots
               (game_id, bookmaker, market, line, over_price, under_price, captured_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            snapshots,
        )
    print(f"Lignes synchronisées : {len(rows)} — {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
