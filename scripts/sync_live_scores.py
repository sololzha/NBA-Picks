"""Synchronise les scores NBA en direct depuis le scoreboard public ESPN.

Les fichiers de calendrier hoopR sont parfaits pour le programme, mais ne sont
pas assez frais pour l'affichage minute par minute. Ce script ne remplace donc
que les snapshots live avec les données du scoreboard ESPN.
"""

from __future__ import annotations

import json
import sqlite3
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from app.database import DATABASE_PATH


SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"


def scoreboard_for(day: str) -> list[dict]:
    query = urllib.parse.urlencode({"dates": day.replace("-", ""), "limit": "100"})
    request = urllib.request.Request(f"{SCOREBOARD_URL}?{query}", headers={"User-Agent": "NBA-Picks/1.0"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response).get("events", [])


def main() -> int:
    today = datetime.now(timezone.utc).date()
    dates = [(today + timedelta(days=offset)).isoformat() for offset in (-1, 0, 1)]
    live_count = 0
    final_count = 0

    with sqlite3.connect(DATABASE_PATH) as connection:
        pending = {row[0] for row in connection.execute("""
            SELECT game_id FROM games WHERE game_date BETWEEN ? AND ? AND home_points IS NULL
        """, (dates[0], dates[-1]))}
        for day in dates:
            try:
                events = scoreboard_for(day)
            except OSError as error:
                # Keep the last usable snapshot if ESPN is briefly unreachable.
                print(f"Scoreboard indisponible pour {day} : {error}")
                continue
            for event in events:
                competition = event.get("competitions", [{}])[0]
                competitors = competition.get("competitors", [])
                home = next((item for item in competitors if item.get("homeAway") == "home"), None)
                away = next((item for item in competitors if item.get("homeAway") == "away"), None)
                if not home or not away:
                    continue
                game_id = f"hoopr:{event.get('id')}"
                if game_id not in pending:
                    continue
                status = competition.get("status", {})
                kind = status.get("type", {})
                state = kind.get("state")
                if state == "post" and kind.get("completed") and home.get("score") and away.get("score"):
                    connection.execute(
                        """UPDATE games SET home_points=?, away_points=?, imported_at=CURRENT_TIMESTAMP
                           WHERE game_id=? AND home_points IS NULL""",
                        (int(home.get("score") or 0), int(away.get("score") or 0), game_id),
                    )
                    connection.execute("DELETE FROM live_game_snapshots WHERE game_id=?", (game_id,))
                    pending.remove(game_id)
                    final_count += 1
                    continue
                # Only real ongoing games may appear as live in the dashboard.
                if state != "in":
                    continue
                connection.execute(
                    """INSERT INTO live_game_snapshots
                       (game_id, status_name, status_state, period, clock, home_score, away_score, updated_at)
                       VALUES (?, ?, 'live', ?, ?, ?, ?, ?)
                       ON CONFLICT(game_id) DO UPDATE SET
                         status_name=excluded.status_name, status_state=excluded.status_state,
                         period=excluded.period, clock=excluded.clock,
                         home_score=excluded.home_score, away_score=excluded.away_score,
                         updated_at=excluded.updated_at""",
                    (
                        game_id,
                        kind.get("detail") or "En cours",
                        status.get("period"),
                        status.get("displayClock") or "",
                        int(home.get("score") or 0),
                        int(away.get("score") or 0),
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
                live_count += 1
    print(f"Scores live synchronisés : {live_count} ; résultats finaux intégrés : {final_count}")
    return final_count


if __name__ == "__main__":
    main()
