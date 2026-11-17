"""Generate transparent Elo moneyline probabilities for scheduled games."""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from datetime import date
from itertools import groupby
from pathlib import Path
from zoneinfo import ZoneInfo

from app.database import DATABASE_PATH
from app.market import MIN_EXPECTED_RETURN, market_signals
from app.pick_journal import PICK_PUBLICATION_WINDOW, active_pick, instant, record_picks, write_json
from app.strategy import (DEFAULT_WINNER, TotalStrategy, WinnerStrategy, completed_games as load_games,
                          TOTAL_MARGIN_POINTS, load_strategy, replay, total_reference_options)


OUTPUT_PATH = Path("data/picks.json")
INJURIES_PATH = Path("data/injuries.json")
GUARD_PATH = Path("data/model_guard.json")
SAFETY_MARGIN = 8
SAFE_STRATEGY_PATH = Path("data/safe_total_strategy.json")


def selected_safety_margin() -> int:
    if not SAFE_STRATEGY_PATH.exists():
        return SAFETY_MARGIN
    try:
        return int(json.loads(SAFE_STRATEGY_PATH.read_text(encoding="utf-8"))["selected"]["margin"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return SAFETY_MARGIN


def load_injuries(now) -> tuple[dict, bool]:
    if not INJURIES_PATH.exists():
        return {}, False
    report = json.loads(INJURIES_PATH.read_text(encoding="utf-8"))
    updated = instant(report.get("updated_at"))
    fresh = updated is not None and 0 <= (now - updated).total_seconds() <= 8 * 3600
    return report.get("teams", {}) if fresh else {}, fresh


def load_guard() -> dict[str, object]:
    if not GUARD_PATH.exists():
        return {"state": "normal", "confidence_floor": .75, "reason": "modèle en initialisation"}
    return json.loads(GUARD_PATH.read_text(encoding="utf-8"))


def model_total_pick(projection: float, league_average: float, safety_margin: int | None = None) -> dict[str, object]:
    """Always provide a model threshold while clearly separating it from a bookmaker price."""
    direction = "Over" if projection >= league_average else "Under"
    margin = safety_margin if safety_margin is not None else selected_safety_margin()
    safe_line = round((projection - margin if direction == "Over" else projection + margin) * 2) / 2
    return {"pick": f"{direction} {safe_line:.1f}", "safe_line": safe_line, "basis": f"marge de sécurité de {margin} points"}


def confidence_band(probability: float) -> str:
    return str(min(95, int(probability * 20) * 5))


def calibrated_confidence(raw_probability: float, calibration: dict[str, tuple[int, int]]) -> float:
    """Shrink a confidence score toward observed, out-of-sample results.

    A small neutral prior prevents a short hot streak from turning into an
    aggressive recommendation.  This deliberately makes the published score
    more conservative than the raw Elo output.
    """
    games, wins = calibration.get(confidence_band(raw_probability), (0, 0))
    observed = (wins + 40 * raw_probability) / (games + 40)
    return max(0.50, min(raw_probability, observed))


def main(as_of: str, limit: int | None = None, game_ids: list[str] | None = None,
         output_path: Path | None = OUTPUT_PATH) -> dict:
    now = datetime.now(timezone.utc)
    reference = date.fromisoformat(as_of)
    first = (reference - timedelta(days=1)).isoformat()
    last = (reference + timedelta(days=7)).isoformat()
    with sqlite3.connect(DATABASE_PATH) as connection:
        completed = load_games(connection, min(as_of, date.today().isoformat()))
        criteria, params = "g.game_date BETWEEN ? AND ?", [first, last]
        if game_ids:
            criteria, params = f"g.game_id IN ({','.join('?' for _ in game_ids)})", game_ids
        scheduled = connection.execute(f"""
            SELECT g.game_id, g.game_date, g.start_time, g.home_team, g.away_team, g.season
            FROM games g LEFT JOIN live_game_snapshots l ON g.game_id = l.game_id
            WHERE g.season_type = 'regular' AND g.home_points IS NULL AND {criteria}
              AND lower(coalesce(l.status_state, 'pre')) NOT IN ('in', 'live', 'in_progress', 'post')
            ORDER BY g.game_date, g.start_time, g.game_id
        """, params).fetchall()
        quotes = defaultdict(list)
        for game_id, *quote in connection.execute("""
            SELECT game_id, market, bookmaker, line, over_price, under_price, captured_at
            FROM odds_snapshots WHERE market IN ('total', 'moneyline')
            ORDER BY julianday(captured_at) DESC, bookmaker
        """):
            quotes[game_id].append(quote)

    strategy = load_strategy()
    winner = WinnerStrategy(DEFAULT_WINNER)
    totals = TotalStrategy(**strategy["total"]["selected"])
    # Do not apply a result from the same NBA slate to another game in that slate.
    slates = iter(groupby(completed, key=lambda game: game[1]))
    prior = next(slates, None)
    injuries, injuries_fresh = load_injuries(now)
    guard = load_guard()
    picks = []
    future_games = [row for row in scheduled if active_pick({"start_time": row[2]}, now)]
    for game_id, game_day, start_time, home, away, season in future_games[:limit]:
        while prior and prior[0] < game_day:
            past_games = list(prior[1])
            for _ in replay(past_games, winner.predict, winner.learn):
                pass
            for _ in replay(past_games, totals.predict, totals.learn):
                pass
            prior = next(slates, None)
        game = (game_id, game_day, season, home, away, None, None)
        prediction = winner.predict(game)
        probability = prediction["home_win_probability"]
        team = home if probability >= .5 else away
        confidence = max(probability, 1 - probability)
        total = totals.predict(game)
        projection, spread = total["projection"], total["residual_std"]
        signals = market_signals(quotes[game_id], now, team, home, confidence, projection, spread)
        quote = signals.get("total")
        references = total_reference_options(projection, spread, total["reference_line"])
        reference_total = references[str(TOTAL_MARGIN_POINTS)]
        selected_total = quote or reference_total
        availability = max((int(injuries.get(t, {}).get("out", 0)) for t in (home, away)), default=0)
        uncertain = max((int(injuries.get(t, {}).get("uncertain", 0)) for t in (home, away)), default=0)
        eligible = availability < 4 and uncertain < 3 and guard.get("state") != "paused"
        tier = "fort" if confidence >= float(guard.get("confidence_floor", .75)) else "observation"
        picks.append({
            "game_id": game_id, "date": game_day, "start_time": start_time,
            "home_team": home, "away_team": away, "pick": team,
            "home_win_probability": probability, "pick_probability": confidence,
            "model": "daily_strategy", "tier": tier if eligible else "no_bet", "winner_tier": tier,
            "moneyline_quote": signals.get("moneyline"), "eligible": eligible,
            "market_min_return": MIN_EXPECTED_RETURN,
            "no_bet_reason": "Effectif incertain" if not eligible and injuries_fresh else None,
            "diagnostic_context": {
                "rest_days": {side: prediction.get(f"{side}_rest_days") for side in ("home", "away")},
                "recent_totals": {side: total.get(f"{side}_recent_total") for side in ("home", "away")},
                "injuries": {
                    side: {key: injuries.get(team_name, {}).get(key, default)
                           for key, default in (("out", 0), ("uncertain", 0), ("players", []))}
                    for side, team_name in (("home", home), ("away", away))
                } if injuries_fresh else None,
            },
            "total": {
                "projection": round(projection, 1), "residual_std": spread, "market_signal": quote,
                "display_pick": selected_total["selection"], "pick_line": selected_total["line"],
                "pick_probability": selected_total["probability"], "is_book_line": quote is not None,
                "reference": reference_total,
                "references": references,
            },
        })

    published_at = datetime.now(timezone.utc)
    picks = sorted((p for p in picks if active_pick(p, published_at)),
                   key=lambda p: (-p["pick_probability"], p["start_time"], p["game_id"]))
    payload = {"generated_at": published_at.isoformat(), "generated_for": as_of,
               "completed_games_used": len(completed), "picks": picks, "model_guard": guard}
    if output_path is not None:
        write_json(output_path, payload)
        record_picks([p for p in picks if instant(p["start_time"]) <= published_at + PICK_PUBLICATION_WINDOW], published_at)
        print(f"Picks générés : {len(picks)} - {output_path}")
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyse tous les matchs NBA à venir sur huit dates.")
    today = datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    parser.add_argument("--as-of", default=today, help="Date de référence YYYY-MM-DD.")
    parser.add_argument("--limit", type=int, help="Plafond facultatif, absent lors de l'actualisation du site.")
    parser.add_argument("--game-id", action="append", dest="game_ids")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    arguments = parser.parse_args()
    main(arguments.as_of, arguments.limit, arguments.game_ids, arguments.output)
