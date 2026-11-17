"""Local NBA Picks web application with built-in live data refresh."""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
from contextlib import asynccontextmanager, closing, suppress
from pathlib import Path
import json

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Body
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.database import DATABASE_PATH
from app.pick_journal import PICK_PUBLICATION_WINDOW, active_pick, instant
from app.strategy import load_strategy, total_reference_options
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
LOG = logging.getLogger("nba_picks.refresh")
LIVE_REFRESH_SECONDS = 30
# Rebuild schedules and model picks while the dashboard is open. The
# live scoreboard itself is refreshed much more frequently below.
FULL_REFRESH_SECONDS = 6 * 60 * 60
PREGAME_SOURCES_REFRESH_SECONDS = 15 * 60


def run_script(module: str, *arguments: str) -> None:
    """Run an existing project updater without blocking FastAPI's event loop."""
    command = [sys.executable, "-m", module, *arguments]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=15 * 60,
        check=False,
    )
    if completed.returncode:
        message = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"{module} a échoué ({completed.returncode}) : {message[-600:]}")
    if completed.stdout.strip():
        LOG.info("%s : %s", module, completed.stdout.strip().splitlines()[-1])


async def refresh_loop() -> None:
    """Keep local files current for as long as this local server is running.

    No Windows/ChatGPT scheduled task is needed: closing the app stops the
    worker, and opening it starts an immediate refresh again.
    """
    last_full_refresh = 0.0
    last_pregame_refresh = 0.0
    loop = asyncio.get_running_loop()
    while True:
        now = loop.time()
        is_full_refresh = now - last_full_refresh >= FULL_REFRESH_SECONDS
        try:
            if is_full_refresh:
                # The daily updater also fetches the current season, rebuilds
                # picks, and takes a first live snapshot.
                # Mark the attempt before the request: an offline provider must
                # not cause a new expensive full refresh every 30 seconds.
                last_full_refresh = now
                last_pregame_refresh = now
                await asyncio.to_thread(run_script, "scripts.daily_update")
            else:
                refresh_sources = now - last_pregame_refresh >= PREGAME_SOURCES_REFRESH_SECONDS
                if refresh_sources:
                    last_pregame_refresh = now
                arguments = ("--pregame-sources",) if refresh_sources else ()
                await asyncio.to_thread(run_script, "scripts.live_refresh", *arguments)
        except Exception as error:  # A temporary provider outage must not stop the site.
            LOG.warning("Actualisation automatique indisponible : %s", error)
            # Scores can still become fresh when only the full schedule source
            # is unavailable.
            if is_full_refresh:
                with suppress(Exception):
                    await asyncio.to_thread(run_script, "scripts.live_refresh")
        await asyncio.sleep(LIVE_REFRESH_SECONDS)


@asynccontextmanager
async def lifespan(_: FastAPI):
    worker = asyncio.create_task(refresh_loop(), name="nba-picks-auto-refresh")
    try:
        yield
    finally:
        worker.cancel()
        with suppress(asyncio.CancelledError):
            await worker


app = FastAPI(title="NBA Picks 2026-2027", version="0.3.0", lifespan=lifespan)
TEMPLATE_PATH = Path(__file__).parent / "templates" / "index.html"
STATIC_PATH = Path(__file__).parent / "static"
PICKS_PATH = Path(__file__).resolve().parents[1] / "data" / "picks.json"
LINES_PATH = Path(__file__).resolve().parents[1] / "data" / "line_movement.json"
LIVE_PATH = Path(__file__).resolve().parents[1] / "data" / "live.json"

app.mount("/static", StaticFiles(directory=STATIC_PATH), name="static")


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    """Serve the daily NBA dashboard."""
    return TEMPLATE_PATH.read_text(encoding="utf-8")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "stage": "nba-daily-board-v4"}


@app.get("/api/picks")
def picks() -> dict:
    """Return the full NBA slate and the models' latest pregame picks."""
    from app.pick_journal import current_quote, journal_connection

    now = datetime.now(timezone.utc)
    today = now.astimezone(ZoneInfo("America/New_York")).date()
    yesterday = (today - timedelta(days=1)).isoformat()
    dates = [(today + timedelta(days=offset)).isoformat() for offset in range(8)]
    payload = json.loads(PICKS_PATH.read_text(encoding="utf-8")) if PICKS_PATH.exists() else {}
    latest = {p["game_id"]: p for p in payload.get("picks", []) if p.get("model") == "daily_strategy"}
    with closing(journal_connection()) as connection:
        rows = connection.execute("""
            SELECT g.game_id, g.game_date, g.start_time, g.home_team, g.away_team,
                   g.home_points, g.away_points, l.status_state, p.payload
            FROM games g
            LEFT JOIN live_game_snapshots l ON l.game_id = g.game_id
            LEFT JOIN published_picks p ON p.game_id = g.game_id AND p.market = 'daily_board'
            WHERE g.season = '2027' AND g.season_type = 'regular'
              AND g.game_date BETWEEN ? AND ?
            ORDER BY g.game_date, g.start_time, g.game_id
        """, (yesterday, dates[-1])).fetchall()

    games = []
    for game_id, game_date, start, home_team, away_team, home_points, away_points, state, archived in rows:
        state = (state or "").lower()
        final = home_points is not None and away_points is not None
        if final:
            status = "Terminé"
        elif state == "post":
            status = "Score final en attente"
        elif state in {"live", "in", "in_progress"}:
            status = "En cours"
        elif start and not active_pick({"start_time": start}, now):
            status = "Coup d’envoi passé"
        else:
            status = None

        starts_at = instant(start)
        outside_window = status is None and starts_at is not None and starts_at > now + PICK_PUBLICATION_WINDOW
        is_history = game_date == yesterday
        prediction = latest.get(game_id) if not is_history and status is None and not outside_window else None
        if (status or is_history) and archived:
            candidate = json.loads(archived)
            if candidate.get("model") == "daily_strategy":
                prediction = candidate
        game = {**(prediction or {}), "game_id": game_id, "date": game_date,
                "start_time": start, "home_team": home_team, "away_team": away_team, "status": status,
                "outside_window": outside_window}
        if is_history and final:
            game["final_score"] = {"home": home_points, "away": away_points}
        if prediction:
            total = dict(game["total"])
            reference = total.get("reference") or {}
            if not total.get("references") and "line" in reference and "residual_std" in total:
                base_line = reference.get("base_line", reference["line"])
                total["references"] = total_reference_options(total["projection"], total["residual_std"], base_line)
            quote = total.get("market_signal")
            if status is None and quote and not current_quote(quote, now):
                reference = total["reference"]
                total.update(market_signal=None, display_pick=reference["selection"], is_book_line=False,
                             pick_line=reference["line"], pick_probability=reference["probability"])
            if status is None and not current_quote(game.get("moneyline_quote") or {}, now):
                game["moneyline_quote"] = None
            game["total"] = total
        games.append(game)

    games.sort(key=lambda game: (game["date"], -game.get("pick_probability", -1)))
    strategy = load_strategy()
    return {
        "today": dates[0], "yesterday": yesterday, "dates": [yesterday, *dates],
        "games": games, "generated_at": payload.get("generated_at"),
        "backtest": {"winner": strategy["winner"].get("baseline"),
                     "total": strategy["total"].get("adjusted_test") or strategy["total"].get("test"),
                     "totals_by_margin": strategy["total"].get("tests_by_margin")},
    }


@app.get("/api/calendar")
def calendar() -> dict:
    """Return every scheduled regular-season game kept in the local database."""
    import sqlite3

    with sqlite3.connect(DATABASE_PATH) as connection:
        rows = connection.execute(
            """SELECT game_id, game_date, start_time, home_team, away_team, home_points, away_points
               FROM games WHERE season = '2027' AND season_type = 'regular'
               ORDER BY game_date, start_time, game_id"""
        ).fetchall()
    return {"games": [{"game_id": row[0], "date": row[1], "start_time": row[2], "home_team": row[3], "away_team": row[4], "home_points": row[5], "away_points": row[6]} for row in rows]}


@app.get("/api/lines")
def lines() -> dict:
    """Return the opening-to-latest movement of locally archived market lines."""
    if not LINES_PATH.exists():
        raise HTTPException(status_code=404, detail="Aucune ligne archivée pour le moment.")
    import json

    return json.loads(LINES_PATH.read_text(encoding="utf-8"))


@app.get("/api/live")
def live() -> dict:
    """Return pace-based notes for active games when fresh snapshots exist."""
    if not LIVE_PATH.exists():
        return {"games": []}
    import json

    payload = json.loads(LIVE_PATH.read_text(encoding="utf-8"))
    updated = instant(payload.get("updated_at"))
    if updated is None or not 0 <= (datetime.now(timezone.utc) - updated).total_seconds() <= 180:
        payload["games"] = []
    return payload


@app.get("/api/markets")
def markets() -> dict:
    """Return only markets that pass the project's data-quality policy."""
    if not PICKS_PATH.exists():
        raise HTTPException(status_code=404, detail="Le rapport Marché est en cours de préparation.")
    import json

    from scripts.build_market_report import main as market_report
    return market_report(persist=False)


@app.get("/api/upcoming")
def upcoming() -> dict:
    """Return selectable unfinished games from the next two calendar days."""
    import sqlite3
    from datetime import date, timedelta

    start, end = date.today().isoformat(), (date.today() + timedelta(days=2)).isoformat()
    with sqlite3.connect(DATABASE_PATH) as connection:
        rows = connection.execute(
            """SELECT game_id, game_date, start_time, away_team, home_team FROM games
               WHERE season_type='regular' AND home_points IS NULL AND game_date >= ? AND game_date <= ?
               ORDER BY game_date, start_time, game_id""", (start, end)
        ).fetchall()
    return {"games": [{"game_id": r[0], "date": r[1], "start_time": r[2], "away_team": r[3], "home_team": r[4]} for r in rows if active_pick({"start_time": r[2]}, datetime.now(timezone.utc))]}


@app.post("/api/submitted-picks")
def submitted_picks(game_ids: list[str] = Body(..., embed=True)) -> dict:
    """Generate isolated model picks for explicitly selected future games."""
    if not game_ids or len(game_ids) > 20:
        raise HTTPException(status_code=400, detail="Choisis entre 1 et 20 matchs.")
    from datetime import date
    from scripts.generate_picks import main as generate

    return generate(date.today().isoformat(), len(game_ids), game_ids, None)
