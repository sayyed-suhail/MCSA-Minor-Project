
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "event_db.sqlite3"


def get_connection():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database():
    connection = get_connection()

    try:
        cursor = connection.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS venues (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                location TEXT NOT NULL,
                capacity INTEGER NOT NULL CHECK (capacity > 0)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                sport TEXT NOT NULL,
                description TEXT DEFAULT '',
                event_date TEXT NOT NULL,
                venue_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'scheduled'
                    CHECK (status IN (
                        'scheduled', 'ongoing', 'completed', 'cancelled'
                    )),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (venue_id) REFERENCES venues(id)
                    ON DELETE RESTRICT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS teams (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                sport TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS event_teams (
                event_id INTEGER NOT NULL,
                team_id INTEGER NOT NULL,
                PRIMARY KEY (event_id, team_id),
                FOREIGN KEY (event_id) REFERENCES events(id)
                    ON DELETE CASCADE,
                FOREIGN KEY (team_id) REFERENCES teams(id)
                    ON DELETE CASCADE
            )
        """)

        connection.commit()
        print("Event Service database initialized successfully.")

    except sqlite3.Error:
        connection.rollback()
        raise

    finally:
        connection.close()


if __name__ == "__main__":
    initialize_database()
