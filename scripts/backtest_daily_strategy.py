"""Tune once on 2024–25, then compare on untouched seasons 2025–26 onward."""

from datetime import datetime
from itertools import product
import sqlite3

from app.database import DATABASE_PATH
from app.pick_journal import write_json
from app.strategy import (DEFAULT_TOTAL, DEFAULT_WINNER, REPORT_PATH, TOTAL_MARGIN_OPTIONS, TOTAL_MARGIN_POINTS, TotalStrategy,
                          adjusted_total_reference,
                          WinnerStrategy, completed_games, replay, tempered)


def winner_predictions(games, params):
    model = WinnerStrategy(params)
    for game, prediction in replay(games, model.predict, model.learn):
        yield game, prediction["home_win_probability"], int(game[-2] > game[-1])


def winner_metrics(predictions, first, last, temperature):
    scored = [(tempered(p, temperature), y) for game, p, y in predictions if first <= game[2] <= last]
    n = len(scored)
    wins = sum(int((p >= .5) == y) for p, y in scored)
    return {"wins": wins, "count": n, "accuracy": wins / n,
            "brier": sum((p - y) ** 2 for p, y in scored) / n}


def total_metrics(games, params, first, last, margin=0):
    model = TotalStrategy(**params)
    count = wins = squared = error = naive_wins = 0
    for game, prediction in replay(games, model.predict, model.learn):
        if not first <= game[2] <= last:
            continue
        actual = game[-2] + game[-1]
        line = prediction["reference_line"]
        pick = adjusted_total_reference(prediction["projection"], prediction["residual_std"], line, margin)
        won = (actual > pick["line"]) == (pick["direction"] == "Over")
        count += 1
        wins += won
        naive_wins += actual < line
        squared += (pick["probability"] - won) ** 2
        error += abs(actual - prediction["projection"])
    metrics = {"wins": wins, "count": count, "accuracy": wins / count, "brier": squared / count,
               "mae": error / count}
    if margin:
        metrics["margin_points"] = margin
    else:
        metrics["always_under_accuracy"] = naive_wins / count
    return metrics


def main():
    with sqlite3.connect(DATABASE_PATH) as con:
        games = completed_games(con, datetime.now().date().isoformat())
        available = dict(con.execute("SELECT market, COUNT(*) FROM odds_snapshots GROUP BY market"))

    tuning = ("2025", "2025")
    evaluation = ("2026", games[-1][2])
    tuning_games = [game for game in games if game[2] <= tuning[1]]
    winners = []
    for home, form, rest, k, keep, margin in product((45, 70, 95), (0, 24), (0, 40), (16, 24, 36), (.45, .65, .85), (False, True)):
        params = dict(home_advantage=home, form_weight=form, back_to_back_weight=rest,
                      k_factor=k, season_retention=keep, score_margin=margin)
        predictions = list(winner_predictions(tuning_games, params))
        for temperature in (.85, 1., 1.15, 1.30):
            winners.append(({**params, "temperature": temperature}, winner_metrics(predictions, *tuning, temperature)))
    winner, winner_tuning = max(winners, key=lambda x: (x[1]["wins"], -x[1]["brier"]))
    winner_params = {k: v for k, v in winner.items() if k != "temperature"}

    totals = []
    for window, alpha, trend, shrink in product((5, 10, 20, 35), (0, .01, .04), (0, .5, 1), (.35, .65, 1)):
        params = dict(window=window, bias_alpha=alpha, recent_weight=trend, regression=shrink)
        totals.append((params, total_metrics(tuning_games, params, *tuning)))
    for alpha, shrink in product((.015, .03, .06, .10), (.65, 1, 1.25)):
        params = {**DEFAULT_TOTAL, "rating_alpha": alpha, "regression": shrink}
        totals.append((params, total_metrics(tuning_games, params, *tuning)))
    # Use the next full season as a promotion gate for the challenger.
    # The final measurement starts only after that gate.
    promotion = ("2026", "2026")
    evaluation = ("2027", games[-1][2])
    total, total_tuning = max(totals, key=lambda x: (x[1]["wins"], -x[1]["brier"], -x[1]["mae"]))
    total_challenger = total_metrics(games, total, *promotion)
    total_incumbent = total_metrics(games, DEFAULT_TOTAL, *promotion)
    if (total_challenger["wins"], -total_challenger["brier"]) < (total_incumbent["wins"], -total_incumbent["brier"]):
        total = DEFAULT_TOTAL
        total_tuning = total_metrics(tuning_games, total, *tuning)
    margin_tests = {str(margin): total_metrics(games, total, *evaluation, margin=margin)
                    for margin in TOTAL_MARGIN_OPTIONS}
    report = {
        "tuning_season": tuning[0], "total_promotion_season": promotion[0], "evaluation_seasons": evaluation,
        "evaluation_from": next(g[1] for g in games if g[2] == evaluation[0]),
        "evaluation_through": games[-1][1], "odds_snapshots": available,
        "winner": {"selected": winner, "candidates": len(winners), "validation": winner_tuning,
                   "test": winner_metrics(winner_predictions(games, winner_params), *evaluation, winner["temperature"]),
                   "baseline": winner_metrics(winner_predictions(games, DEFAULT_WINNER), *evaluation, 1.),
                   "since_2025": winner_metrics(winner_predictions(games, winner_params), "2026", evaluation[1], winner["temperature"]),
                   "baseline_since_2025": winner_metrics(winner_predictions(games, DEFAULT_WINNER), "2026", evaluation[1], 1.)},
        "total": {"selected": total, "candidates": len(totals), "validation": total_tuning,
                  "test": margin_tests["0"],
                  "adjusted_test": margin_tests[str(TOTAL_MARGIN_POINTS)],
                  "tests_by_margin": margin_tests,
                  "baseline": total_metrics(games, DEFAULT_TOTAL, *evaluation),
                  "promotion_challenger": total_challenger, "promotion_baseline": total_incumbent,
                  "reference": "Moyenne des 250 derniers totaux, ramenée au demi-point."},
    }
    write_json(REPORT_PATH, report)
    for market in ("winner", "total"):
        print(market, report[market])


if __name__ == "__main__":
    main()
