"""One daily, fault-tolerant refresh for the local NBA Picks dashboard."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def refresh(module, *arguments):
    try:
        subprocess.run([sys.executable, "-m", module, *arguments], cwd=ROOT, check=True)
        return True
    except subprocess.CalledProcessError as error:
        print(f"{module} : mise à jour indisponible (code {error.returncode}).")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Met à jour les données et les picks NBA.")
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument("--skip-odds", action="store_true")
    args = parser.parse_args()
    refresh("scripts.generate_picks")
    if not args.skip_download and refresh("scripts.download_hoopr_schedules", "2027"):
        refresh("scripts.import_hoopr_schedules")
    refresh("scripts.init_db")
    refresh("scripts.sync_injuries")
    if not args.skip_odds and os.environ.get("HOOPS_API_KEY"):
        refresh("scripts.sync_hoopsapi_odds")
    refresh("scripts.sync_live_scores")
    refresh("scripts.generate_picks")
    refresh("scripts.analyze_line_movement")
    refresh("scripts.build_live_analysis")
    print("\nDaily update complete.")


if __name__ == "__main__":
    main()
