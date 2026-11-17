"""Build an auditable next-day analysis of historical model picks."""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from pathlib import Path

from app.database import DATABASE_PATH
from app.pick_journal import write_json
from app.moneyline_model import MoneylineModel
from app.total_model import RollingTotalModel
from scripts.generate_picks import model_total_pick, selected_safety_margin


OUTPUT_PATH = Path("data/history.json")
GUARD_PATH = Path("data/model_guard.json")
START_DATE = "2026-10-01"
STRONG_PICK_THRESHOLD = 0.68


def confidence_band(probability: float) -> str:
    """Group confidence into understandable, sufficiently broad bands."""
    if probability < 0.60:
        return "50–59 %"
    if probability < 0.70:
        return "60–69 %"
    return "70 % +"


def diagnostic(actual_total: int, projection: float, team_correct: bool, total_correct: bool) -> tuple[str, str]:
    """Describe the observed miss without pretending to know its real-world cause."""
    residual = round(actual_total - projection, 1)
    if not total_correct and residual >= 12:
        total_note = "score réel nettement au-dessus de la projection"
    elif not total_correct and residual <= -12:
        total_note = "score réel nettement sous la projection"
    elif not total_correct:
        total_note = "écart proche du seuil, total manqué de peu"
    else:
        total_note = "projection de total dans la bonne direction"

    winner_note = "vainqueur correctement anticipé" if team_correct else "vainqueur non anticipé"
    label = "total trop bas" if residual >= 12 else "total trop haut" if residual <= -12 else "match serré / variance"
    return label, f"{winner_note} ; {total_note}. Écart observé : {residual:+.1f} point(s)."


def main() -> None:
    with sqlite3.connect(DATABASE_PATH) as connection:
        games = connection.execute(
            """SELECT game_id, game_date, home_team, away_team, home_points, away_points
               FROM games WHERE season_type = 'regular' AND home_points IS NOT NULL
               ORDER BY game_date, game_id"""
        ).fetchall()

    moneyline = MoneylineModel()
    totals = RollingTotalModel()
    safety_margin = selected_safety_margin()
    rows = []
    for game_id, game_date, home, away, home_points, away_points in games:
        moneyline_info = moneyline.predict(home, away, game_date)
        home_probability = float(moneyline_info["home_win_probability"])
        total_info = totals.project(home, away)
        total_projection = float(total_info["projection"])
        team_pick = home if home_probability >= 0.5 else away
        safe_total_pick = model_total_pick(total_projection, float(total_info["league_average"]), safety_margin)
        total_direction = str(safe_total_pick["pick"]).split()[0]
        raw_total_pick = f"{total_direction} {total_projection:.1f}"
        actual_total = home_points + away_points
        actual_winner = home if home_points > away_points else away
        safe_total_correct = actual_total > safe_total_pick["safe_line"] if total_direction == "Over" else actual_total < safe_total_pick["safe_line"]
        raw_total_correct = actual_total > total_projection if total_direction == "Over" else actual_total < total_projection
        if game_date >= START_DATE:
            selected_probability = home_probability if team_pick == home else 1 - home_probability
            error_category, total_explanation = diagnostic(actual_total, total_projection, team_pick == actual_winner, safe_total_correct)
            rows.append({
                "game_id": game_id, "date": game_date, "home_team": home, "away_team": away,
                "actual_winner": actual_winner, "team_pick": team_pick, "team_correct": team_pick == actual_winner,
                "pick_probability": round(selected_probability, 4), "confidence_band": confidence_band(selected_probability),
                "actual_total": actual_total,
                "safe_total_pick": safe_total_pick["pick"], "safe_total_correct": safe_total_correct,
                "raw_total_pick": raw_total_pick, "raw_total_correct": raw_total_correct,
                "total_projection": total_projection, "league_average": total_info["league_average"], "error_category": error_category, "total_explanation": total_explanation,
            })
        moneyline.learn(home, away, game_date, home_points, away_points, home_probability)
        totals.learn(home, away, home_points, away_points, total_projection)

    recent = list(reversed(rows[-30:]))
    calibration = []
    for band in ("50–59 %", "60–69 %", "70 % +"):
        band_rows = [row for row in rows if row["confidence_band"] == band]
        if not band_rows:
            continue
        predicted = sum(row["pick_probability"] for row in band_rows) / len(band_rows)
        observed = sum(row["team_correct"] for row in band_rows) / len(band_rows)
        calibration.append({
            "band": band,
            "games": len(band_rows),
            "predicted": round(predicted, 3),
            "observed": round(observed, 3),
            "gap": round(observed - predicted, 3),
        })
    brier_score = sum((row["pick_probability"] - int(row["team_correct"])) ** 2 for row in rows) / len(rows) if rows else None
    strong_rows = [row for row in rows if row["pick_probability"] >= STRONG_PICK_THRESHOLD]
    strong_accuracy = sum(row["team_correct"] for row in strong_rows) / len(strong_rows) if strong_rows else None
    total_threshold = safety_margin
    strong_total_rows = rows
    strong_total_accuracy = sum(row["safe_total_correct"] for row in strong_total_rows) / len(strong_total_rows) if strong_total_rows else None
    home_rows = [row for row in rows if row["team_pick"] == row["home_team"]]
    away_rows = [row for row in rows if row["team_pick"] == row["away_team"]]
    recent_strong = [row for row in rows[-30:] if row["pick_probability"] >= STRONG_PICK_THRESHOLD]
    recent_accuracy = sum(row["team_correct"] for row in recent_strong) / len(recent_strong) if recent_strong else None
    # The governor is deliberately slow to react: it avoids changing strategy
    # because of a couple of unlucky games, yet reduces exposure on a real dip.
    if recent_accuracy is not None and len(recent_strong) >= 12 and recent_accuracy < .52:
        guard = {"state": "paused", "confidence_floor": 1.0, "reason": "résultats récents insuffisants : aucun pick publié"}
    elif recent_accuracy is not None and len(recent_strong) >= 12 and recent_accuracy < .60:
        guard = {"state": "cautious", "confidence_floor": .78, "reason": "résultats récents sous surveillance : seuil renforcé"}
    else:
        guard = {"state": "normal", "confidence_floor": .75, "reason": "modèle dans sa plage de contrôle"}
    payload = {
        "updated_through": rows[-1]["date"] if rows else None,
        "summary": {
            "games_analysed": len(rows),
            "moneyline_accuracy": round(sum(row["team_correct"] for row in rows) / len(rows), 3) if rows else None,
            "strong_picks": len(strong_rows),
            "strong_moneyline_accuracy": round(strong_accuracy, 3) if strong_accuracy is not None else None,
            "strong_pick_threshold": STRONG_PICK_THRESHOLD,
            "strong_total_picks": len(strong_total_rows),
            "strong_total_accuracy": round(strong_total_accuracy, 3) if strong_total_accuracy is not None else None,
            "strong_total_threshold": total_threshold,
            "home_pick_accuracy": round(sum(row["team_correct"] for row in home_rows) / len(home_rows), 3) if home_rows else None,
            "away_pick_accuracy": round(sum(row["team_correct"] for row in away_rows) / len(away_rows), 3) if away_rows else None,
            "recent_strong_picks": len(recent_strong),
            "recent_strong_accuracy": round(recent_accuracy, 3) if recent_accuracy is not None else None,
            "safe_total_accuracy": round(sum(row["safe_total_correct"] for row in rows) / len(rows), 3) if rows else None,
            "raw_total_accuracy": round(sum(row["raw_total_correct"] for row in rows) / len(rows), 3) if rows else None,
            "brier_score": round(brier_score, 3) if brier_score is not None else None,
        },
        "calibration": calibration,
        "learning_note": "Le modèle est mis à jour uniquement après les résultats finaux. La calibration compare la confiance annoncée au taux réellement observé ; les diagnostics décrivent l’écart, sans prétendre identifier une cause certaine.",
        "games": recent,
    }
    write_json(OUTPUT_PATH, payload)
    write_json(GUARD_PATH, {**guard, "updated_through": payload["updated_through"], "recent_strong_picks": len(recent_strong), "recent_strong_accuracy": payload["summary"]["recent_strong_accuracy"]})
    print(f"Historique analysé : {len(recent)} matchs — {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
