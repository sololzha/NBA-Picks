"""Transparent rolling-total model; updated only after a completed game."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
import json
from pathlib import Path


WINDOW = 10
DEFAULT_LEAGUE_TOTAL = 220.0
CONFIG_PATH = Path(__file__).resolve().parents[1] / "data" / "total_model_config.json"


@dataclass
class TeamForm:
    window: int = WINDOW
    points_for: deque[int] = field(init=False)
    points_against: deque[int] = field(init=False)

    def __post_init__(self) -> None:
        self.points_for = deque(maxlen=self.window)
        self.points_against = deque(maxlen=self.window)

    @property
    def games(self) -> int:
        return len(self.points_for)

    @property
    def recent_total(self) -> float:
        if not self.games:
            return DEFAULT_LEAGUE_TOTAL
        return (sum(self.points_for) + sum(self.points_against)) / self.games


class RollingTotalModel:
    """Projects score totals from the two teams' recent offensive/defensive pace."""

    def __init__(self, window: int | None = None, bias_alpha: float | None = None, edge_threshold: float | None = None) -> None:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8")) if CONFIG_PATH.exists() else {}
        self.window = window if window is not None else int(config.get("window", WINDOW))
        self.bias_alpha = bias_alpha if bias_alpha is not None else float(config.get("bias_alpha", 0.02))
        self.edge_threshold = edge_threshold if edge_threshold is not None else float(config.get("edge_threshold", 0))
        self.enabled = bool(config.get("enabled", True))
        self.forms: defaultdict[str, TeamForm] = defaultdict(lambda: TeamForm(self.window))
        self.league_total_sum = 0
        self.league_games = 0
        self.bias = 0.0

    @property
    def league_average(self) -> float:
        return self.league_total_sum / self.league_games if self.league_games else DEFAULT_LEAGUE_TOTAL

    def project(self, home: str, away: str) -> dict[str, float | int | str]:
        home_form, away_form = self.forms[home], self.forms[away]
        raw_projection = (home_form.recent_total + away_form.recent_total) / 2
        evidence = min(home_form.games, away_form.games) / self.window
        projection = evidence * raw_projection + (1 - evidence) * self.league_average + self.bias
        confidence = "élevée" if evidence >= 0.8 else "moyenne" if evidence >= 0.5 else "faible"
        return {
            "projection": round(projection * 2) / 2,
            "home_recent_total": round(home_form.recent_total, 1),
            "away_recent_total": round(away_form.recent_total, 1),
            "home_games": home_form.games,
            "away_games": away_form.games,
            "confidence": confidence,
            "league_average": round(self.league_average, 1),
        }

    def learn(self, home: str, away: str, home_points: int, away_points: int, prediction: float | None = None) -> None:
        """Ingest a final result only after it has occurred."""
        total = home_points + away_points
        if prediction is not None:
            # Slow correction: a single outlier cannot overturn the model.
            self.bias = (1 - self.bias_alpha) * self.bias + self.bias_alpha * (total - prediction)
        self.forms[home].points_for.append(home_points)
        self.forms[home].points_against.append(away_points)
        self.forms[away].points_for.append(away_points)
        self.forms[away].points_against.append(home_points)
        self.league_total_sum += total
        self.league_games += 1
