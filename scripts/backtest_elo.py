"""Run an auditable, chronological Elo backtest for NBA regular-season games."""

from __future__ import annotations

import json
import math
import sqlite3
import uuid
from collections import defaultdict
from datetime import date

from app.database import DATABASE_PATH, initialise_database


MODEL_NAME = "elo_moneyline_v1"
FEATURE_VERSION = "elo:400,k:20,home_advantage:100"
TRAINING_CUTOFF = "2025-10-01"
HOME_ADVANTAGE = 100
K_FACTOR = 20


def probability_home_win(home_rating: float, away_rating: float) -> float:
    """Return pre-game home win probability from ratings and home advantage."""
    return 1 / (1 + 10 ** (-((home_rating + HOME_ADVANTAGE) - away_rating) / 400))


def log_loss(probability: float, outcome: int) -> float:
    safe_probability = min(max(probability, 1e-15), 1 - 1e-15)
    return -(outcome * math.log(safe_probability) + (1 - outcome) * math.log(1 - safe_probability))


def main() -> None:
    initialise_database()
    with sqlite3.connect(DATABASE_PATH) as connection:
        games = connection.execute(
            """
            SELECT game_id, game_date, home_team, away_team, home_points, away_points
            FROM games
            WHERE season_type = 'regular' AND home_points IS NOT NULL AND away_points IS NOT NULL
            ORDER BY game_date, game_id
            """
        ).fetchall()

        ratings: defaultdict[str, float] = defaultdict(lambda: 1500.0)
        evaluation_rows: list[tuple[str, float]] = []
        accuracy_hits = 0
        squared_errors: list[float] = []
        losses: list[float] = []

        for game_id, game_date, home, away, home_points, away_points in games:
            probability = probability_home_win(ratings[home], ratings[away])
            actual_home_win = int(home_points > away_points)

            if game_date > TRAINING_CUTOFF:
                evaluation_rows.append((game_id, probability))
                accuracy_hits += int((probability >= 0.5) == bool(actual_home_win))
                squared_errors.append((probability - actual_home_win) ** 2)
                losses.append(log_loss(probability, actual_home_win))

            rating_shift = K_FACTOR * (actual_home_win - probability)
            ratings[home] += rating_shift
            ratings[away] -= rating_shift

        if not evaluation_rows:
            raise RuntimeError("Aucun match après la date de validation temporelle.")

        metrics = {
            "evaluation_start": TRAINING_CUTOFF,
            "evaluation_games": len(evaluation_rows),
            "accuracy": round(accuracy_hits / len(evaluation_rows), 4),
            "brier_score": round(sum(squared_errors) / len(squared_errors), 4),
            "log_loss": round(sum(losses) / len(losses), 4),
            "home_advantage_elo": HOME_ADVANTAGE,
            "k_factor": K_FACTOR,
        }
        run_id = f"elo-{uuid.uuid4()}"
        connection.execute(
            """
            INSERT INTO model_runs (run_id, training_cutoff, model_name, feature_version, notes)
            VALUES (?, ?, ?, ?, ?)
            """,
            (run_id, TRAINING_CUTOFF, MODEL_NAME, FEATURE_VERSION, json.dumps(metrics)),
        )
        connection.executemany(
            """
            INSERT INTO predictions (prediction_id, run_id, game_id, home_win_probability)
            VALUES (?, ?, ?, ?)
            """,
            [(f"{run_id}:{game_id}", run_id, game_id, probability) for game_id, probability in evaluation_rows],
        )

    print("Backtest Elo terminé")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
