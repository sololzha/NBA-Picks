"""Minute-level refresh for current scores and live pick analysis."""

import argparse
import os

from scripts.daily_update import refresh
from scripts.sync_live_scores import main as sync_scores


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pregame-sources", action="store_true")
    if parser.parse_args().pregame_sources:
        refresh("scripts.sync_injuries")
        if os.environ.get("HOOPS_API_KEY"):
            refresh("scripts.sync_hoopsapi_odds")
    sync_scores()
    refresh("scripts.generate_picks")
    refresh("scripts.build_live_analysis")
    print("Live refresh complete.")
