"""Durable pregame picks and settlement from final scores."""

from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
import sqlite3
from pathlib import Path
from tempfile import NamedTemporaryFile

from app.database import DATABASE_PATH

PICK_PUBLICATION_WINDOW = timedelta(hours=24)


def instant(value):
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (TypeError, ValueError):
        return None


def write_json(path: Path, payload: dict) -> None:
    temporary = None
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as file:
            temporary = Path(file.name)
            json.dump(payload, file, ensure_ascii=False, indent=2)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def active_pick(pick, now):
    start = instant(pick.get("start_time"))
    return start is not None and now < start


def current_quote(quote, now):
    captured = instant(quote.get("captured_at"))
    return captured is not None and timedelta() <= now - captured <= timedelta(hours=4)


def journal_connection():
    connection = sqlite3.connect(DATABASE_PATH, timeout=15)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS published_picks (
            game_id TEXT NOT NULL REFERENCES games(game_id),
            market TEXT NOT NULL,
            captured_at TEXT NOT NULL,
            starts_at TEXT NOT NULL,
            payload TEXT NOT NULL,
            PRIMARY KEY (game_id, market)
        )
    """)
    return connection


def record_picks(picks, published_at):
    with closing(journal_connection()) as connection, connection:
        for pick in picks:
            if not active_pick(pick, published_at):
                continue
            game_id = pick["game_id"]
            variants = [("winner", pick)]
            if pick.get("model") == "daily_strategy":
                variants.append(("daily_board", pick))
            if pick["eligible"] and pick["tier"] != "no_bet":
                for market, quote in (("priced_winner", pick.get("moneyline_quote")),
                                      ("total", pick["total"].get("market_signal"))):
                    if (quote and current_quote(quote, published_at)
                            and (market != "total" or quote.get("margin_met", False))
                            and quote["expected_return"] >= pick["market_min_return"]):
                        variants.append((market, quote))
            for market, payload in variants:
                connection.execute("""
                    INSERT INTO published_picks
                    (game_id, market, captured_at, starts_at, payload)
                    SELECT game_id, ?, ?, ?, ? FROM games
                    WHERE game_id=? AND home_points IS NULL AND NOT EXISTS (
                        SELECT 1 FROM live_game_snapshots
                        WHERE game_id=games.game_id
                          AND lower(status_state) IN ('in', 'live', 'in_progress', 'post')
                    )
                    ON CONFLICT(game_id, market) DO UPDATE
                    SET captured_at=excluded.captured_at, starts_at=excluded.starts_at, payload=excluded.payload
                    WHERE excluded.market='daily_board'
                      AND julianday(excluded.captured_at) > julianday(published_picks.captured_at)
                """, (market, published_at.isoformat(), pick["start_time"], json.dumps(payload), game_id))


def journal_report():
    with closing(journal_connection()) as connection:
        rows = connection.execute("""
            SELECT p.market, p.captured_at, p.payload,
                   g.game_id, g.game_date, g.home_team, g.away_team, g.home_points, g.away_points
            FROM published_picks p JOIN games g USING (game_id)
            WHERE p.market IN ('winner', 'priced_winner', 'total')
            ORDER BY p.captured_at DESC, g.game_id
        """).fetchall()
    winners, strong, totals, priced_winners, favorites, brier, settled, pending = [], [], [], [], [], [], [], 0
    for market, captured, raw, game_id, date, home, away, home_score, away_score in rows:
        if home_score is None or away_score is None:
            pending += 1
            continue
        pick = json.loads(raw)
        result = dict(market=market, captured_at=captured, game_id=game_id, date=date, home_team=home, away_team=away)
        if market == "winner":
            win = pick["pick"] == (home if home_score > away_score else away)
            winners.append(win)
            brier.append((pick["pick_probability"] - win) ** 2)
            if pick.get("winner_tier") == "fort" and pick["eligible"] and pick["tier"] != "no_bet":
                strong.append(win)
            result.update(selection=pick["pick"], outcome="win" if win else "loss", probability=pick["pick_probability"])
            quote = pick.get("moneyline_quote")
            if quote and current_quote(quote, instant(captured)):
                side = quote["favorite_side"]
                if side:
                    favorites.append(((side == "home") == (home_score > away_score), win))
        elif market == "priced_winner":
            win = pick["selection"] == (home if home_score > away_score else away)
            profit = pick["price"] - 1 if win else -1
            priced_winners.append(profit)
            result.update(selection=pick["selection"], outcome="win" if win else "loss",
                          probability=pick["probability"], price=pick["price"], profit=profit)
        else:
            difference = home_score + away_score - pick["line"]
            if pick["direction"] == "Under":
                difference = -difference
            profit = pick["price"] - 1 if difference > 0 else -1 if difference < 0 else 0
            totals.append(profit)
            result.update(selection=pick["selection"], outcome="win" if difference > 0 else "loss" if difference < 0 else "push",
                          probability=pick["probability"], price=pick["price"], profit=profit)
        settled.append(result)
    return {
        "pending": pending,
        "winner_count": len(winners),
        "winner_accuracy": sum(winners) / len(winners) if winners else None,
        "strong_count": len(strong),
        "strong_accuracy": sum(strong) / len(strong) if strong else None,
        "winner_brier": sum(brier) / len(brier) if brier else None,
        "market_comparison_count": len(favorites),
        "market_favorite_accuracy": sum(item[0] for item in favorites) / len(favorites) if favorites else None,
        "model_accuracy_on_market_comparison": sum(item[1] for item in favorites) / len(favorites) if favorites else None,
        "priced_winner_count": len(priced_winners),
        "priced_winner_roi": sum(priced_winners) / len(priced_winners) if priced_winners else None,
        "priced_total_count": len(totals),
        "priced_total_roi": sum(totals) / len(totals) if totals else None,
        "games": settled[:30],
    }


def tracked_picks(game_ids):
    placeholders = ",".join("?" for _ in game_ids)
    with closing(journal_connection()) as connection:
        rows = connection.execute(f"""
            SELECT p.payload, g.home_points, g.away_points
            FROM published_picks p JOIN games g USING (game_id)
            WHERE p.market='winner' AND p.game_id IN ({placeholders})
        """, game_ids)
        return [dict(json.loads(payload), final_score=[away, home] if home is not None else None)
                for payload, home, away in rows]
