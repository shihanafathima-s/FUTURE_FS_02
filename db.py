

import sqlite3
from pathlib import Path
from flask import g

BASE_DIR = Path(__file__).resolve().parent
DATABASE_DIR = BASE_DIR / "database"
DATABASE_PATH = DATABASE_DIR / "leadflow.db"
SCHEMA_PATH = DATABASE_DIR / "schema.sql"


def get_db():
    if "db" not in g:
        DATABASE_DIR.mkdir(exist_ok=True)

        g.db = sqlite3.connect(DATABASE_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")

    return g.db


def close_db(error=None):
    db = g.pop("db", None)

    if db is not None:
        db.close()


def init_db():
    DATABASE_DIR.mkdir(exist_ok=True)

    connection = sqlite3.connect(DATABASE_PATH)
    connection.execute("PRAGMA foreign_keys = ON")

    with open(SCHEMA_PATH, "r", encoding="utf-8") as file:
        schema = file.read()

    # Create the users table first.
    connection.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Check whether the existing leads table has user_id.
    tables = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='leads'"
    ).fetchone()

    if tables:
        columns = [
            row[1]
            for row in connection.execute(
                "PRAGMA table_info(leads)"
            ).fetchall()
        ]

        if "user_id" not in columns:
            connection.execute(
                "ALTER TABLE leads ADD COLUMN user_id INTEGER REFERENCES users(id)"
            )

    # Create missing tables and indexes.
    connection.executescript(schema)

    connection.commit()
    connection.close()
