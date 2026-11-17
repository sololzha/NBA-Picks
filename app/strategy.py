"""Pregame model replay shared by the dashboard and the strategy backtest."""

from collections import defaultdict, deque
from datetime import datetime, timezone
from itertools import groupby
import json
from math import erf, exp, log, sqrt
from pathlib import Path

from app.moneyline_model import MoneylineModel
from app.total_model import RollingTotalModel


REPORT_PATH = Path(__file__).resolve().parents[1] / "data" / "strategy_evaluation.json"
DEFAULT_WINNER = dict(home_advantage=70, form_weight=0, back_to_back_weight=0,
                      k_factor=24, season_retention=.65, score_margin=True)
DEFAULT_TOTAL = dict(window=20, bias_alpha=.01, recent_weight=0, regression=1)
TOTAL_MARGIN_POINTS = 5
TOTAL_MARGIN_OPTIONS = (0, TOTAL_MARGIN_POINTS, 10)


def completed_games(connection, through):
    return connection.execute("""
        SELECT game_id, game_date, season, home_team, away_team, home_points, away_points
        FROM games
        WHERE season_type='regular' AND home_points IS NOT NULL AND game_date <= ?
          AND (start_time IS NULL OR julianday(start_time) < julianday(?))
        ORDER BY game_date, start_time, game_id
    """, (through, datetime.now(timezone.utc).isoformat())).fetchall()


def replay(games, predict, learn):
    """Predict an entire NBA date before updating with any results from it."""
    for _, slate in groupby(games, key=lambda game: game[1]):
        predictions = [(game, predict(game)) for game in slate]
        yield from predictions
        for game, prediction in predictions:
            learn(game, prediction)


class WinnerStrategy:
    def __init__(self, params):
        self.model = MoneylineModel(**params)

    def predict(self, game):
        _, day, _, home, away, *_ = game
        return self.model.predict(home, away, day)

    def learn(self, game, prediction):
        _, day, _, home, away, hs, aws = game
        self.model.learn(home, away, day, hs, aws, prediction["home_win_probability"])


class TotalStrategy:
    def __init__(self, window, bias_alpha, recent_weight, regression, rating_alpha=0):
        self.model = RollingTotalModel(window=window, bias_alpha=bias_alpha)
        self.recent_weight = recent_weight
        self.regression = regression
        self.rating_alpha = rating_alpha
        self.attack = defaultdict(float)
        self.defense = defaultdict(float)
        self.league = deque(maxlen=250)
        self.errors = deque(maxlen=600)
        self.error_sum = 0.
        self.error_square_sum = 0.

    def predict(self, game):
        _, _, _, home, away, *_ = game
        recent = sum(self.league) / len(self.league) if self.league else 220
        line = int(recent) + .5
        form = self.model.project(home, away)
        trend = self.recent_weight * (recent - self.model.league_average)
        if self.rating_alpha:
            deviation = self.attack[home] + self.defense[away] + self.attack[away] + self.defense[home]
            raw = recent + deviation
        else:
            raw = float(form["projection"]) + trend
        base = recent + self.regression * (raw - recent)
        bias = self.error_sum / len(self.errors) if self.errors else 0
        variance = self.error_square_sum / len(self.errors) - bias ** 2 if self.errors else 400
        return {**form, "base": base, "projection": base + bias, "rolling_projection": form["projection"],
                "reference_line": line, "league_points": recent / 2,
                "residual_std": sqrt(max(100, variance))}

    def learn(self, game, prediction):
        _, _, _, home, away, hs, aws = game
        total = hs + aws
        if self.rating_alpha:
            center = prediction["league_points"]
            home_error = hs - center - self.attack[home] - self.defense[away]
            away_error = aws - center - self.attack[away] - self.defense[home]
            self.attack[home] += self.rating_alpha * home_error
            self.defense[away] += self.rating_alpha * home_error
            self.attack[away] += self.rating_alpha * away_error
            self.defense[home] += self.rating_alpha * away_error
        error = total - prediction["base"]
        if len(self.errors) == self.errors.maxlen:
            oldest = self.errors[0]
            self.error_sum -= oldest
            self.error_square_sum -= oldest ** 2
        self.errors.append(error)
        self.error_sum += error
        self.error_square_sum += error ** 2
        self.league.append(total)
        self.model.learn(home, away, hs, aws, prediction["rolling_projection"])


def total_selection(projection, spread, line, direction=None):
    """Map a continuous distribution to integer scores and handle pushes."""
    def cdf(value):
        return (1 + erf((value - projection) / (spread * sqrt(2)))) / 2

    line = float(line)
    adjustment = .5 if line.is_integer() else 0
    under = cdf(line - adjustment)
    over = 1 - cdf(line + adjustment)
    direction = direction or ("Over" if over >= under else "Under")
    probability = over if direction == "Over" else under
    return dict(selection=f"{direction} {line:.1f}", direction=direction,
                line=line, probability=probability, push_probability=max(0., 1 - over - under))


def adjusted_total_reference(projection, spread, line, margin=TOTAL_MARGIN_POINTS):
    direction = total_selection(projection, spread, line)["direction"]
    adjusted = line - margin if direction == "Over" else line + margin
    return {**total_selection(projection, spread, adjusted, direction),
            "base_line": line, "margin_points": margin}


def total_reference_options(projection, spread, line):
    return {str(margin): adjusted_total_reference(projection, spread, line, margin)
            for margin in TOTAL_MARGIN_OPTIONS}


def tempered(probability, temperature):
    return 1 / (1 + exp(-log(probability / (1 - probability)) / temperature))


def load_strategy():
    if REPORT_PATH.exists():
        return json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    return {"winner": {"selected": DEFAULT_WINNER}, "total": {"selected": DEFAULT_TOTAL}}
