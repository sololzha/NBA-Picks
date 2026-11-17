"""Chronological moneyline model using Elo, recent form, and rest days."""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import date
import json
from pathlib import Path

from scripts.backtest_elo import K_FACTOR, probability_home_win


HOME_ADVANTAGE = 100
FORM_WEIGHT = 28
BACK_TO_BACK_WEIGHT = 24
CONFIG_PATH = Path(__file__).resolve().parents[1] / "data" / "model_config.json"


class MoneylineModel:
    def __init__(self, home_advantage: int | None = None, form_weight: int | None = None, back_to_back_weight: int | None = None, k_factor: int | None = None, season_retention: float = 1.0, score_margin: bool = False) -> None:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8")) if CONFIG_PATH.exists() else {}
        self.home_advantage = home_advantage if home_advantage is not None else int(config.get("home_advantage", HOME_ADVANTAGE))
        self.form_weight = form_weight if form_weight is not None else int(config.get("form_weight", FORM_WEIGHT))
        self.back_to_back_weight = back_to_back_weight if back_to_back_weight is not None else int(config.get("back_to_back_weight", BACK_TO_BACK_WEIGHT))
        self.k_factor = k_factor if k_factor is not None else int(config.get("k_factor", K_FACTOR))
        explicit = any(value is not None for value in (home_advantage, form_weight, back_to_back_weight, k_factor))
        self.season_retention = season_retention if explicit else float(config.get("season_retention", season_retention))
        self.score_margin = score_margin if explicit else bool(config.get("score_margin", score_margin))
        self.season = None
        self.ratings: defaultdict[str, float] = defaultdict(lambda: 1500.0)
        self.results: defaultdict[str, deque[int]] = defaultdict(lambda: deque(maxlen=10))
        self.last_played: dict[str, date] = {}

    def rest_days(self, team: str, game_date: str) -> int | None:
        previous = self.last_played.get(team)
        if previous is None:
            return None
        return max(0, (date.fromisoformat(game_date) - previous).days - 1)

    def predict(self, home: str, away: str, game_date: str) -> dict[str, float | int | None]:
        year = int(game_date[:4])
        season = year if game_date[5:7] >= "10" else year - 1
        if self.season is not None and season > self.season:
            for team in self.ratings:
                self.ratings[team] = 1500 + (self.ratings[team] - 1500) * self.season_retention
            self.results.clear()
        self.season = season
        home_form = sum(self.results[home]) / len(self.results[home]) if self.results[home] else 0.5
        away_form = sum(self.results[away]) / len(self.results[away]) if self.results[away] else 0.5
        home_rest, away_rest = self.rest_days(home, game_date), self.rest_days(away, game_date)
        rest_delta = 0
        if home_rest == 0 and away_rest not in (None, 0):
            rest_delta -= self.back_to_back_weight
        elif away_rest == 0 and home_rest not in (None, 0):
            rest_delta += self.back_to_back_weight
        adjusted_home_rating = self.ratings[home] + self.form_weight * (home_form - away_form) + rest_delta
        probability = probability_home_win(adjusted_home_rating - self.home_advantage, self.ratings[away])
        return {
            "home_win_probability": probability,
            "home_rest_days": home_rest,
            "away_rest_days": away_rest,
            "home_form": round(home_form, 2),
            "away_form": round(away_form, 2),
        }

    def learn(self, home: str, away: str, game_date: str, home_points: int, away_points: int, probability: float) -> None:
        home_win = int(home_points > away_points)
        shift = self.k_factor * (home_win - probability)
        if self.score_margin:
            shift *= .65 + min(abs(home_points - away_points), 35) / 35
        self.ratings[home] += shift
        self.ratings[away] -= shift
        self.results[home].append(home_win)
        self.results[away].append(1 - home_win)
        parsed = date.fromisoformat(game_date)
        self.last_played[home] = parsed
        self.last_played[away] = parsed
