"""Chronological validation and error diagnostics for the rolling totals model."""

from __future__ import annotations

import json
import sqlite3
import uuid

from app.database import DATABASE_PATH, initialise_database
from app.total_model import RollingTotalModel


CUTOFF = "2025-10-01"


def main() -> None:
    initialise_database()
    with sqlite3.connect(DATABASE_PATH) as connection:
        games = connection.execute(
            """SELECT game_date, home_team, away_team, home_points, away_points
               FROM games WHERE season_type = 'regular' AND home_points IS NOT NULL
               ORDER BY game_date, game_id"""
        ).fetchall()
        model = RollingTotalModel()
        errors: list[float] = []
        for game_date, home, away, home_points, away_points in games:
            projection = float(model.project(home, away)["projection"])
            actual = home_points + away_points
            if game_date > CUTOFF:
                errors.append(actual - projection)
            model.learn(home, away, home_points, away_points, projection)

        metrics = {
            "evaluation_start": CUTOFF,
            "evaluation_games": len(errors),
            "mae_total_points": round(sum(abs(error) for error in errors) / len(errors), 2),
            "mean_error": round(sum(errors) / len(errors), 2),
            "within_10_points": round(sum(abs(error) <= 10 for error in errors) / len(errors), 4),
            "learning_policy": "Les formes récentes sont mises à jour après chaque résultat final ; les paramètres ne changent qu’après validation temporelle.",
        }
        connection.execute(
            """INSERT INTO model_runs (run_id, training_cutoff, model_name, feature_version, notes)
               VALUES (?, ?, ?, ?, ?)""",
            (f"rolling-total-{uuid.uuid4()}", CUTOFF, "rolling_total_v1", "window:10", json.dumps(metrics, ensure_ascii=False)),
        )
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
