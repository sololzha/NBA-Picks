"""Small, dependency-free SQLite foundation for the first data import."""

import sqlite3
from pathlib import Path


DATABASE_PATH = Path(__file__).resolve().parents[1] / "data" / "nba_picks.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    game_id TEXT PRIMARY KEY,
    game_date TEXT NOT NULL,
    start_time TEXT,
    season TEXT NOT NULL,
    season_type TEXT NOT NULL CHECK (season_type IN ('regular', 'playoffs')),
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    home_points INTEGER,
    away_points INTEGER,
    source_name TEXT NOT NULL,
    source_game_id TEXT,
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (home_team <> away_team),
    CHECK ((home_points IS NULL AND away_points IS NULL) OR
           (home_points IS NOT NULL AND away_points IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS idx_games_date ON games(game_date);
CREATE INDEX IF NOT EXISTS idx_games_season ON games(season, season_type);

CREATE TABLE IF NOT EXISTS model_runs (
    run_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    training_cutoff TEXT NOT NULL,
    model_name TEXT NOT NULL,
    feature_version TEXT NOT NULL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS predictions (
    prediction_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES model_runs(run_id),
    game_id TEXT NOT NULL REFERENCES games(game_id),
    home_win_probability REAL NOT NULL CHECK (home_win_probability >= 0 AND home_win_probability <= 1),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(run_id, game_id)
);

CREATE TABLE IF NOT EXISTS odds_snapshots (
    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id TEXT NOT NULL REFERENCES games(game_id),
    bookmaker TEXT NOT NULL,
    market TEXT NOT NULL DEFAULT 'total',
    line REAL NOT NULL,
    over_price REAL,
    under_price REAL,
    captured_at TEXT NOT NULL,
    UNIQUE(game_id, bookmaker, market, captured_at)
);

CREATE INDEX IF NOT EXISTS idx_odds_snapshots_game ON odds_snapshots(game_id, captured_at);

CREATE TABLE IF NOT EXISTS live_game_snapshots (
    game_id TEXT PRIMARY KEY REFERENCES games(game_id),
    status_name TEXT NOT NULL,
    status_state TEXT NOT NULL,
    period INTEGER,
    clock TEXT,
    home_score INTEGER,
    away_score INTEGER,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def initialise_database() -> Path:
    """Create the local database and the minimal auditable schema."""
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.executescript(SCHEMA)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(games)")}
        if "start_time" not in columns:
            connection.execute("ALTER TABLE games ADD COLUMN start_time TEXT")
    return DATABASE_PATH
