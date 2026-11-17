"""Select a conservative Elo configuration using chronological holdout data."""

from __future__ import annotations

import itertools
import json
import sqlite3
from pathlib import Path

from app.database import DATABASE_PATH
from app.moneyline_model import MoneylineModel
from app.pick_journal import write_json


CONFIG_PATH = Path("data/model_config.json")
REPORT_PATH = Path("data/strategy_search.json")
SELECTION_START = "2024-10-01"
HOLDOUT_START = "2025-10-01"
MIN_SELECTION_PICKS = 80


def evaluate(games: list[tuple], config: dict[str, int], start: str, end: str | None) -> dict[str, float | int]:
    model = MoneylineModel(**config)
    picked = correct = hits = 0
    squared_error = 0.0
    all_games = 0
    for game_date, home, away, home_points, away_points in games:
        prediction = model.predict(home, away, game_date)
        home_probability = float(prediction["home_win_probability"])
        confidence = max(home_probability, 1 - home_probability)
        actual_home_win = int(home_points > away_points)
        if game_date >= start and (end is None or game_date < end):
            all_games += 1
            hits += int((home_probability >= 0.5) == bool(actual_home_win))
            squared_error += (home_probability - actual_home_win) ** 2
            # A high-confidence-only strategy is what is surfaced as a strong pick.
            if confidence >= 0.68:
                picked += 1
                correct += int((home_probability >= 0.5) == bool(actual_home_win))
        model.learn(home, away, game_date, home_points, away_points, home_probability)
    return {"games": all_games, "all_game_accuracy": hits / all_games if all_games else None, "picks": picked, "accuracy": correct / picked if picked else 0.0, "brier": squared_error / all_games if all_games else 1.0}


def main() -> None:
    with sqlite3.connect(DATABASE_PATH) as connection:
        games = connection.execute(
            """SELECT game_date, home_team, away_team, home_points, away_points FROM games
               WHERE season_type='regular' AND home_points IS NOT NULL
               ORDER BY game_date, game_id"""
        ).fetchall()
    candidates = []
    for k_factor, home_advantage, season_retention, score_margin in itertools.product(
        (16, 24, 32), (35, 55, 70), (.65, .85, 1.0), (False, True)
    ):
        config = {"home_advantage": home_advantage, "form_weight": 0, "back_to_back_weight": 0,
                  "k_factor": k_factor, "season_retention": season_retention, "score_margin": score_margin}
        selection = evaluate(games, config, SELECTION_START, HOLDOUT_START)
        if selection["picks"] >= MIN_SELECTION_PICKS:
            candidates.append((selection, config))
    if not candidates:
        raise SystemExit("Aucune stratégie avec assez de picks historiques.")
    baseline = {"home_advantage": 70, "form_weight": 0, "back_to_back_weight": 24, "k_factor": 32}
    baseline_selection = evaluate(games, baseline, SELECTION_START, HOLDOUT_START)
    candidates.append((baseline_selection, baseline))
    selection, best = min(candidates, key=lambda item: item[0]["brier"])
    holdout = evaluate(games, best, HOLDOUT_START, None)
    write_json(CONFIG_PATH, best)
    REPORT_PATH.write_text(json.dumps({"selected": best, "selection": selection, "holdout": holdout, "baseline_holdout": evaluate(games, baseline, HOLDOUT_START, None), "candidates_tested": len(candidates), "policy": "Sélection sur 2024-25 ; vérification séparée sur 2025-26 et après. Choix au score de Brier ; le sous-ensemble simulé utilise 68 % de confiance brute."}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"selected": best, "selection_accuracy": round(float(selection["accuracy"]), 4), "holdout_accuracy": round(float(holdout["accuracy"]), 4), "holdout_picks": holdout["picks"], "candidates": len(candidates)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
