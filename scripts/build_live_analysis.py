"""Create pace-based status notes for games currently reported as in progress."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.database import DATABASE_PATH
from app.pick_journal import instant, write_json


OUTPUT_PATH = Path("data/live.json")


def elapsed_minutes(period: int | None, clock: str | None) -> float | None:
    if not period or not clock:
        return None
    match = re.match(r"^(\d+):(\d+)", clock)
    if match:
        remaining = int(match.group(1)) + int(match.group(2)) / 60
    else:
        # ESPN reports the final tenth of a second as e.g. "0.1".
        tenths = re.match(r"^(\d+)\.(\d+)$", clock)
        if not tenths:
            return None
        remaining = int(tenths.group(1)) + int(tenths.group(2)) / 600
    if period > 4:
        return 48 + (period - 5) * 5 + (5 - remaining)
    return max(0.1, (period - 1) * 12 + (12 - remaining))


def sigmoid(value: float) -> float:
    return 1 / (1 + pow(2.718281828, -value))


def logit(probability: float) -> float:
    clipped = min(0.995, max(0.005, probability))
    return __import__("math").log(clipped / (1 - clipped))


def normal_cdf(value: float) -> float:
    math = __import__("math")
    return (1 + math.erf(value / math.sqrt(2))) / 2


def main() -> None:
    with sqlite3.connect(DATABASE_PATH) as connection:
        rows = connection.execute(
            """SELECT g.game_id, g.home_team, g.away_team, l.period, l.clock, l.home_score, l.away_score, l.updated_at
               FROM live_game_snapshots l JOIN games g ON g.game_id=l.game_id
               WHERE g.home_points IS NULL AND lower(l.status_state) IN ('in', 'in_progress', 'live')"""
        ).fetchall()
        archived = {
            game_id: json.loads(payload)
            for game_id, payload in connection.execute("""
                SELECT p.game_id, p.payload FROM published_picks p
                JOIN live_game_snapshots l USING (game_id)
                WHERE p.market='winner'
            """)
        } if connection.execute("SELECT 1 FROM sqlite_master WHERE name='published_picks'").fetchone() else {}
    picks = {item["game_id"]: item for item in json.loads(Path("data/picks.json").read_text(encoding="utf-8")).get("picks", [])} if Path("data/picks.json").exists() else {}
    games = []
    now = datetime.now(timezone.utc)
    for game_id, home, away, period, clock, home_score, away_score, updated_at in rows:
        updated = instant(updated_at)
        if updated is None or not 0 <= (now - updated).total_seconds() <= 180:
            continue
        elapsed = elapsed_minutes(period, clock)
        if elapsed is None or home_score is None or away_score is None:
            continue
        live_total = home_score + away_score
        pace_total = round(live_total * 48 / elapsed, 1)
        pick = archived.get(game_id) or picks.get(game_id, {})
        projection = float(pick.get("total", {}).get("projection", 225.0))
        delta = pace_total - projection
        verdict = "au-dessus du rythme prévu" if delta > 5 else "en dessous du rythme prévu" if delta < -5 else "dans le rythme prévu"
        selected_team = pick.get("pick")
        selected_score = home_score if selected_team == home else away_score
        opponent_score = away_score if selected_team == home else home_score
        duration = 48 + max(0, (period or 0) - 4) * 5
        remaining_fraction = max(0.0, (duration - elapsed) / 48)
        pregame_team_probability = float(pick.get("pick_probability", 0.5))
        lead = selected_score - opponent_score
        team_live_probability = sigmoid(logit(pregame_team_probability) * remaining_fraction + lead / (12 * max(.01, remaining_fraction) ** 0.5))
        team_verdict = "vainqueur bien parti" if selected_score > opponent_score else "vainqueur à surveiller" if selected_score < opponent_score else "vainqueur à égalité"
        total_pick = str(pick.get("total", {}).get("display_pick", ""))
        total_direction = total_pick.split()[0] if total_pick else None
        safe_line = float(pick.get("total", {}).get("pick_line", projection))
        # The score already on the board is fixed; only the remaining minutes
        # are estimated from the pre-game total projection.
        expected_final_total = live_total + projection * remaining_fraction
        residual_std = float(pick.get("total", {}).get("residual_std", 19.6))
        total_uncertainty = max(4.0, residual_std * remaining_fraction ** 0.5)
        total_live_probability = (
            normal_cdf((expected_final_total - safe_line) / total_uncertainty)
            if total_direction == "Over"
            else normal_cdf((safe_line - expected_final_total) / total_uncertainty)
            if total_direction == "Under"
            else 0.5
        )
        total_verdict = (
            "Over bien parti" if total_direction == "Over" and pace_total >= safe_line else
            "Over à surveiller" if total_direction == "Over" else
            "Under bien parti" if total_direction == "Under" and pace_total <= safe_line else
            "Under à surveiller" if total_direction == "Under" else "total à suivre"
        )
        games.append({"game_id": game_id, "home_team": home, "away_team": away, "period": period, "clock": clock, "score": f"{away_score}–{home_score}", "pace_total": pace_total, "projection": projection, "verdict": verdict, "team_verdict": team_verdict, "total_verdict": total_verdict, "team_live_probability": round(team_live_probability, 3), "total_live_probability": round(total_live_probability, 3), "expected_final_total": round(expected_final_total, 1)})
    write_json(OUTPUT_PATH, {"updated_at": now.isoformat(), "games": games})
    print(f"Analyses live : {len(games)} — {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
