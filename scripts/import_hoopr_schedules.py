"""Import completed hoopR NBA schedules into the local SQLite database."""

from __future__ import annotations

import argparse
import csv
import sqlite3
from pathlib import Path

from app.database import DATABASE_PATH, initialise_database


SOURCE_NAME = "hoopR / SportsDataverse (ESPN NBA)"
SEASON_TYPES = {"2": "regular", "3": "playoffs"}


def integer_score(value: str, *, file: Path, game_id: str) -> int:
    """Convert the source's numeric score field while rejecting incomplete rows."""
    if not value:
        raise ValueError(f"Score absent pour le match {game_id} dans {file.name}")
    return int(float(value))


def import_file(connection: sqlite3.Connection, source_file: Path) -> tuple[int, int]:
    imported = skipped = 0
    with source_file.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            season_type = SEASON_TYPES.get(row["season_type"])
            home_team = row["home_display_name"].strip()
            away_team = row["away_display_name"].strip()
            # ESPN uses "TBD" for both sides of a handful of unassigned games.
            # They are not actionable fixtures and violate the database invariant.
            if season_type is None or not home_team or not away_team or home_team == away_team:
                skipped += 1
                continue

            source_game_id = row["game_id"] or row["id"]
            game_id = f"hoopr:{source_game_id}"
            completed = row["status_type_completed"].lower() == "true"
            connection.execute(
                """
                INSERT INTO games (
                    game_id, game_date, start_time, season, season_type, home_team, away_team,
                    home_points, away_points, source_name, source_game_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(game_id) DO UPDATE SET
                    game_date = excluded.game_date,
                    start_time = excluded.start_time,
                    season = excluded.season,
                    season_type = excluded.season_type,
                    home_team = excluded.home_team,
                    away_team = excluded.away_team,
                    home_points = COALESCE(excluded.home_points, games.home_points),
                    away_points = COALESCE(excluded.away_points, games.away_points),
                    source_name = excluded.source_name,
                    source_game_id = excluded.source_game_id
                """,
                (
                    game_id,
                    row["game_date"],
                    row.get("start_date") or None,
                    row["season"],
                    season_type,
                    home_team,
                    away_team,
                    integer_score(row["home_score"], file=source_file, game_id=game_id) if completed else None,
                    integer_score(row["away_score"], file=source_file, game_id=game_id) if completed else None,
                    SOURCE_NAME,
                    source_game_id,
                ),
            )
            connection.execute(
                """INSERT INTO live_game_snapshots
                   (game_id, status_name, status_state, period, clock, home_score, away_score)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(game_id) DO UPDATE SET
                     status_name=excluded.status_name, status_state=excluded.status_state,
                     period=excluded.period, clock=excluded.clock, home_score=excluded.home_score,
                     away_score=excluded.away_score, updated_at=CURRENT_TIMESTAMP""",
                (
                    game_id, row["status_type_name"], row["status_type_state"],
                    int(float(row["status_period"])) if row.get("status_period") else None,
                    row.get("status_display_clock") or None,
                    integer_score(row["home_score"], file=source_file, game_id=game_id) if row.get("home_score") else None,
                    integer_score(row["away_score"], file=source_file, game_id=game_id) if row.get("away_score") else None,
                ),
            )
            imported += 1
    return imported, skipped


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Importe les calendriers hoopR téléchargés dans SQLite.")
    parser.add_argument(
        "directory",
        nargs="?",
        type=Path,
        default=Path("data/raw/hoopr"),
        help="Dossier contenant les fichiers nba_schedule_*.csv.",
    )
    arguments = parser.parse_args()
    files = sorted(arguments.directory.glob("nba_schedule_*.csv"))
    if not files:
        raise SystemExit(f"Aucun fichier NBA trouvé dans {arguments.directory}")

    initialise_database()
    with sqlite3.connect(DATABASE_PATH) as connection:
        totals = [import_file(connection, file) for file in files]
    print(f"Importés ou mis à jour : {sum(item[0] for item in totals)} matchs")
    print(f"Ignorés : {sum(item[1] for item in totals)} lignes hors périmètre")
