"""Initialise the local database without requiring third-party packages."""

from app.database import initialise_database


if __name__ == "__main__":
    database_path = initialise_database()
    print(f"Base initialisée : {database_path}")
