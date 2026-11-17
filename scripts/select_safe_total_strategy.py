"""Validate conservative alternative total lines on an untouched time period."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.database import DATABASE_PATH
from app.total_model import RollingTotalModel


OUTPUT_PATH = Path("data/safe_total_strategy.json")
SELECTION_START = "2024-10-01"
HOLDOUT_START = "2025-10-01"


def evaluate(games: list[tuple], margin: int, start: str, end: str | None) -> dict[str, float | int]:
    model = RollingTotalModel(window=20, bias_alpha=0.01)
    correct = games_count = 0
    for game_date, home, away, home_points, away_points in games:
        info = model.project(home, away)
        projection, average = float(info["projection"]), float(info["league_average"])
        over = projection >= average
        line = projection - margin if over else projection + margin
        if game_date >= start and (end is None or game_date < end):
            games_count += 1
            total = home_points + away_points
            correct += int(total > line) if over else int(total < line)
        model.learn(home, away, home_points, away_points, projection)
    return {"games": games_count, "accuracy": correct / games_count}


def main() -> None:
    with sqlite3.connect(DATABASE_PATH) as connection:
        games = connection.execute("""SELECT game_date, home_team, away_team, home_points, away_points FROM games
            WHERE season_type='regular' AND home_points IS NOT NULL ORDER BY game_date, game_id""").fetchall()
    trials = []
    for margin in (4, 6, 8, 10, 12, 14, 16):
        selection = evaluate(games, margin, SELECTION_START, HOLDOUT_START)
        holdout = evaluate(games, margin, HOLDOUT_START, None)
        trials.append({"margin": margin, "selection": selection, "holdout": holdout})
    valid = [trial for trial in trials if .60 <= float(trial["selection"]["accuracy"]) <= .70]
    if not valid:
        raise SystemExit("Aucune marge O/U prudente validée entre 60 % et 70 %.")
    # The requested 60–70 % band is fixed before selection.  Within it, retain
    # the strongest result on the selection period only.
    selected = max(valid, key=lambda trial: float(trial["selection"]["accuracy"]))
    OUTPUT_PATH.write_text(json.dumps({"selected": selected, "trials": trials, "policy": "Marge choisie sur 2024-25 ; vérification séparée à partir de 2025-26. Une ligne alternative réellement proposée par le bookmaker reste nécessaire pour parier."}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"margin": selected["margin"], "selection_accuracy": round(float(selected["selection"]["accuracy"]), 4), "holdout_accuracy": round(float(selected["holdout"]["accuracy"]), 4), "holdout_games": selected["holdout"]["games"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
