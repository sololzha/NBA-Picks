"""Evaluate the form-and-rest moneyline model strictly forward in time."""

from __future__ import annotations

import json
import math
import sqlite3

from app.database import DATABASE_PATH
from app.moneyline_model import MoneylineModel
from scripts.generate_picks import calibrated_confidence, confidence_band


CUTOFF = "2025-10-01"


def main() -> None:
    with sqlite3.connect(DATABASE_PATH) as connection:
        games = connection.execute("""SELECT game_date, home_team, away_team, home_points, away_points FROM games
            WHERE season_type = 'regular' AND home_points IS NOT NULL ORDER BY game_date, game_id""").fetchall()
    model, correct, errors, losses, total = MoneylineModel(), 0, [], [], 0
    calibration = {}
    home_wins, calibrated_errors = 0, []
    for game_date, home, away, home_points, away_points in games:
        prediction = model.predict(home, away, game_date)
        probability = float(prediction["home_win_probability"])
        actual = int(home_points > away_points)
        confidence = max(probability, 1 - probability)
        selected_won = int((probability >= .5) == bool(actual))
        band = confidence_band(confidence)
        if game_date > CUTOFF:
            total += 1
            correct += selected_won
            home_wins += actual
            errors.append((probability - actual) ** 2)
            calibrated_errors.append((calibrated_confidence(confidence, calibration) - selected_won) ** 2)
            safe = min(max(probability, 1e-12), 1 - 1e-12)
            losses.append(-(actual * math.log(safe) + (1 - actual) * math.log(1 - safe)))
        model.learn(home, away, game_date, home_points, away_points, probability)
        seen, won = calibration.get(band, (0, 0))
        calibration[band] = seen + 1, won + selected_won
    print(json.dumps({"evaluation_games": total, "accuracy": round(correct / total, 4),
                      "always_home_accuracy": round(home_wins / total, 4),
                      "brier_score": round(sum(errors) / total, 4),
                      "calibrated_brier_score": round(sum(calibrated_errors) / total, 4),
                      "log_loss": round(sum(losses) / total, 4)}, indent=2))


if __name__ == "__main__":
    main()
