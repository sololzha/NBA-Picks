"""Build a cautious, auditable report of the NBA betting markets covered."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.pick_journal import PICK_PUBLICATION_WINDOW, current_quote, instant, write_json
from app.market import MIN_EXPECTED_RETURN
from app.database import DATABASE_PATH


PICKS_PATH = Path("data/picks.json")
HISTORY_PATH = Path("data/history.json")
OUTPUT_PATH = Path("data/market_report.json")


def main(persist: bool = True) -> dict:
    now = datetime.now(timezone.utc)
    picks_payload = json.loads(PICKS_PATH.read_text(encoding="utf-8")) if PICKS_PATH.exists() else {"picks": []}
    history = json.loads(HISTORY_PATH.read_text(encoding="utf-8")) if HISTORY_PATH.exists() else {}
    recommendations = []
    watchlist = []
    with sqlite3.connect(DATABASE_PATH) as connection:
        unavailable = {row[0] for row in connection.execute("""
            SELECT game_id FROM games WHERE home_points IS NOT NULL
            UNION SELECT game_id FROM live_game_snapshots
            WHERE lower(status_state) IN ('in', 'live', 'in_progress', 'post')
        """)}
    for pick in picks_payload.get("picks", []):
        start = instant(pick.get("start_time"))
        if pick["game_id"] in unavailable or not start or not now < start <= now + PICK_PUBLICATION_WINDOW:
            continue
        match = f"{pick['away_team']} - {pick['home_team']}"
        for market, quote in (("Vainqueur", pick.get("moneyline_quote")),
                              ("Total match", pick.get("total", {}).get("market_signal"))):
            if not quote or not current_quote(quote, now):
                continue
            row = {**quote, "game_id": pick["game_id"], "match": match, "market": market,
                   "reason": "Estimation expérimentale à la cote relevée."}
            if (pick["eligible"] and pick["tier"] != "no_bet"
                    and (market != "Total match" or quote.get("margin_met", False))
                    and quote["expected_return"] >= MIN_EXPECTED_RETURN):
                recommendations.append(row)
            else:
                watchlist.append(row)

    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "policy": "Cotes relevées depuis moins de 4 h. Signal si rendement estimé ≥ 5 %. Suivi expérimental à mise fixe.",
        "quality": history.get("summary", {}),
        "catalog": [
            {"market": "Vainqueur", "status": "analyse", "source": "Elo, écart au score et transition de saison", "rule": "cote bookmaker requise pour comparer au marché"},
            {"market": "Total match", "status": "analyse", "source": "projection de total + lignes Pinnacle/FanDuel si disponibles", "rule": "cote et ligne exactes requises"},
            {"market": "1re mi-temps", "status": "en attente", "source": "ligne 1re mi-temps vérifiée requise", "rule": "pas de pick sans source"},
            {"market": "Handicap / total équipe", "status": "en attente", "source": "lignes dédiées et modèle par équipe requis", "rule": "pas de pick sans source"},
            {"market": "Stats joueurs", "status": "en attente", "source": "minutes, blessures, statuts et lignes props vérifiés requis", "rule": "pas de pick sans source"},
        ],
        "recommendations": recommendations,
        "watchlist": watchlist,
    }
    if persist:
        write_json(OUTPUT_PATH, payload)
        print(f"Rapport marchés : {len(recommendations)} signal(aux) - {OUTPUT_PATH}")
    return payload


if __name__ == "__main__":
    main()
