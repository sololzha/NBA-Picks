"""Fetch ESPN's public NBA injury report into a small local snapshot."""

from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from app.pick_journal import write_json


URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"
OUTPUT_PATH = Path("data/injuries.json")


def bucket(status: str, comment: str) -> str:
    text = f"{status} {comment}".casefold()
    if any(word in text for word in ("out", "doubtful", "suspend")):
        return "out"
    if any(word in text for word in ("questionable", "day-to-day", "game-time")):
        return "uncertain"
    return "other"


def main() -> None:
    request = urllib.request.Request(URL, headers={"User-Agent": "NBA-Picks/1.0"})
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.load(response)
    teams = {}
    for group in payload.get("injuries", []):
        players = []
        counts = {"out": 0, "uncertain": 0, "other": 0}
        for entry in group.get("injuries", []):
            status = str(entry.get("status") or "unknown")
            comment = str(entry.get("shortComment") or entry.get("longComment") or "")
            kind = bucket(status, comment)
            counts[kind] += 1
            players.append({"name": entry.get("athlete", {}).get("displayName", "Joueur inconnu"), "status": status, "kind": kind})
        teams[group.get("displayName", "")] = {**counts, "players": players}
    write_json(OUTPUT_PATH, {"updated_at": datetime.now(timezone.utc).isoformat(), "teams": teams})
    print(f"Rapport blessures synchronisé : {len(teams)} équipes")


if __name__ == "__main__":
    main()
