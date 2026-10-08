"""Database layer — Database per Service.

payment.db belongs ONLY to the Payment Service. No other service opens this
file; they must call the Payment REST API instead (Data Isolation).
Likewise, this service never opens another service's database — it only
stores booking_id / event_id / user_id as plain references.
"""
import sqlite3
from contextlib import contextmanager

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS payments (
    payment_id      TEXT PRIMARY KEY,
    booking_id      TEXT NOT NULL,          -- ticket / team registration id (Booking Service)
    event_id        TEXT NOT NULL,          -- sports event id (Event Service)
    user_id         TEXT NOT NULL,
    amount          REAL NOT NULL,
    currency        TEXT NOT NULL DEFAULT 'INR',
    method          TEXT NOT NULL,
    status          TEXT NOT NULL,          -- PENDING | SUCCESS | FAILED | REFUNDED
    failure_reason  TEXT,
    idempotency_key TEXT UNIQUE,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS refunds (
    refund_id   TEXT PRIMARY KEY,
    payment_id  TEXT NOT NULL REFERENCES payments(payment_id),
    amount      REAL NOT NULL,
    reason      TEXT,
    created_at  TEXT NOT NULL
);

-- Outbox: notifications that could not be delivered because the
-- Notification Service was down (Circuit Breaker fallback).
CREATE TABLE IF NOT EXISTS pending_notifications (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    payment_id  TEXT NOT NULL,
    event       TEXT NOT NULL,
    payload     TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
"""


def init_db(path=None):
    with get_conn(path) as conn:
        conn.executescript(SCHEMA)


@contextmanager
def get_conn(path=None):
    conn = sqlite3.connect(path or config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def row_to_dict(row):
    return dict(row) if row else None
