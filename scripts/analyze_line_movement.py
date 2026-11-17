"""Generate a transparent opening-to-latest line-movement report."""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from pathlib import Path

from app.database import DATABASE_PATH


OUTPUT_PATH = Path("data/line_movement.json")


def main() -> None:
    with sqlite3.connect(DATABASE_PATH) as connection:
        data = connection.execute(
            """SELECT o.game_id, o.bookmaker, o.line, o.over_price, o.under_price, o.captured_at,
                      g.game_date, g.home_team, g.away_team, g.home_points, g.away_points
               FROM odds_snapshots o JOIN games g ON g.game_id = o.game_id
               WHERE o.market = 'total' ORDER BY o.game_id, o.bookmaker, o.captured_at"""
        ).fetchall()
    groups: defaultdict[tuple[str, str], list[tuple]] = defaultdict(list)
    for item in data:
        groups[(item[0], item[1])].append(item)
    movements = []
    for (_, bookmaker), snapshots in groups.items():
        opening, latest = snapshots[0], snapshots[-1]
        movements.append({
            "game_id": latest[0], "bookmaker": bookmaker, "date": latest[6],
            "away_team": latest[8], "home_team": latest[7], "opening_line": opening[2],
            "latest_line": latest[2], "movement": round(latest[2] - opening[2], 1) if len(snapshots) > 1 else None,
            "samples": len(snapshots), "latest_at": latest[5],
            "status": "final" if latest[9] is not None else "upcoming",
            "actual_total": (latest[9] + latest[10]) if latest[9] is not None else None,
        })
    OUTPUT_PATH.write_text(json.dumps({"movements": sorted(movements, key=lambda item: (item["date"], item["away_team"]))}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Mouvements analysés : {len(movements)} — {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
