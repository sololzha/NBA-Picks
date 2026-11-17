"""Download selected historical NBA schedule files from hoopR's public release.

The source repository publishes its data under CC BY 4.0. Files are kept raw so
that every model result can be traced back to an unchanged source file.
"""

from __future__ import annotations

import argparse
import hashlib
import urllib.request
from pathlib import Path


BASE_URL = (
    "https://github.com/sportsdataverse/sportsdataverse-data/releases/download/"
    "espn_nba_schedules/nba_schedule_{season}.csv"
)
RAW_DIRECTORY = Path(__file__).resolve().parents[1] / "data" / "raw" / "hoopr"


def download(season: int) -> Path:
    """Download one season atomically and return the resulting file path."""
    RAW_DIRECTORY.mkdir(parents=True, exist_ok=True)
    destination = RAW_DIRECTORY / f"nba_schedule_{season}.csv"
    temporary = destination.with_suffix(".csv.part")
    request = urllib.request.Request(
        BASE_URL.format(season=season),
        headers={"User-Agent": "nba-picks-local-mvp/0.1"},
    )
    with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
    temporary.replace(destination)
    checksum = hashlib.sha256(destination.read_bytes()).hexdigest()
    print(f"Téléchargé : {destination.name}  sha256={checksum}")
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Télécharge les calendriers NBA historiques hoopR.")
    parser.add_argument(
        "seasons",
        nargs="*",
        type=int,
        default=[2022, 2023, 2024, 2025, 2026],
        help="Années de fin de saison ; ex. 2026 pour la saison 2025-26.",
    )
    arguments = parser.parse_args()
    for ending_year in arguments.seasons:
        download(ending_year)
