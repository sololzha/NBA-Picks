"""Choose an O/U model only after chronological selection and holdout tests."""

from __future__ import annotations

import itertools
import json
import sqlite3
from pathlib import Path

from app.database import DATABASE_PATH
from app.total_model import RollingTotalModel


CONFIG_PATH = Path("data/total_model_config.json")
REPORT_PATH = Path("data/total_strategy_search.json")
SELECTION_START = "2024-10-01"
HOLDOUT_START = "2025-10-01"
MIN_SELECTION_PICKS = 100


def evaluate(games: list[tuple], config: dict[str, float | int], start: str, end: str | None) -> dict[str, float | int]:
    model = RollingTotalModel(**config)
    picked = correct = 0
    absolute_error = 0.0
    evaluated = 0
    for game_date, home, away, home_points, away_points in games:
        info = model.project(home, away)
        projection, average = float(info["projection"]), float(info["league_average"])
        edge = abs(projection - average)
        actual_total = home_points + away_points
        if game_date >= start and (end is None or game_date < end):
            evaluated += 1
            absolute_error += abs(actual_total - projection)
            if edge >= float(config["edge_threshold"]):
                picked += 1
                correct += int(actual_total > projection) if projection >= average else int(actual_total < projection)
        model.learn(home, away, home_points, away_points, projection)
    return {"games": evaluated, "picks": picked, "accuracy": correct / picked if picked else 0.0, "mae": absolute_error / evaluated if evaluated else 999.0}


def main() -> None:
    with sqlite3.connect(DATABASE_PATH) as connection:
        games = connection.execute("""SELECT game_date, home_team, away_team, home_points, away_points FROM games
            WHERE season_type='regular' AND home_points IS NOT NULL ORDER BY game_date, game_id""").fetchall()
    candidates = []
    for window, bias_alpha, edge_threshold in itertools.product((3, 5, 7, 10, 15, 20), (0.01, 0.02, 0.05, 0.10), (0, 2, 4, 6, 8)):
        config = {"window": window, "bias_alpha": bias_alpha, "edge_threshold": edge_threshold}
        selection = evaluate(games, config, SELECTION_START, HOLDOUT_START)
        if selection["picks"] >= MIN_SELECTION_PICKS:
            candidates.append((selection, config))
    if not candidates:
        raise SystemExit("Aucune stratégie O/U avec assez de résultats.")
    selection, best = max(candidates, key=lambda item: (item[0]["accuracy"], -item[0]["mae"], item[0]["picks"]))
    holdout = evaluate(games, best, HOLDOUT_START, None)
    # A strategy that cannot beat chance on untouched data is disabled rather
    # than being presented as an O/U recommendation.
    best["enabled"] = float(holdout["accuracy"]) >= 0.52
    CONFIG_PATH.write_text(json.dumps(best, indent=2), encoding="utf-8")
    REPORT_PATH.write_text(json.dumps({"selected": best, "selection": selection, "holdout": holdout, "candidates_tested": len(candidates), "enabled": best["enabled"], "policy": "Sélection sur 2024-25 ; vérification séparée sur 2025-26 et après. La stratégie est désactivée si elle ne dépasse pas 52 % sur la vérification indépendante."}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"selected": best, "selection_accuracy": round(float(selection["accuracy"]), 4), "holdout_accuracy": round(float(holdout["accuracy"]), 4), "holdout_picks": holdout["picks"], "candidates": len(candidates)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
