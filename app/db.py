"""SQLite storage for tokens.

Columns: issued_at = token issued, served_at = service started (wait ends),
finished_at = service finished (optional). source = token | manual | sample | upload.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime

import pandas as pd

from . import analytics, config

SCHEMA = """
CREATE TABLE IF NOT EXISTS tokens (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    counter      TEXT NOT NULL,
    token_no     INTEGER NOT NULL,
    service_type TEXT DEFAULT 'general',
    issued_at    TEXT NOT NULL,
    served_at    TEXT,
    finished_at  TEXT,
    source       TEXT DEFAULT 'token'
);
CREATE INDEX IF NOT EXISTS idx_tokens_counter_issued ON tokens(counter, issued_at);
"""


def _path(path: str | None) -> str:
    return path or config.DB_PATH


@contextmanager
def connect(path: str | None = None):
    conn = sqlite3.connect(_path(path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(path: str | None = None) -> None:
    with connect(path) as c:
        c.executescript(SCHEMA)


def _ts(value) -> str | None:
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).strftime("%Y-%m-%d %H:%M:%S")


def issue_token(counter: str, service_type: str = "general", issued_at=None,
                source: str = "token", path: str | None = None) -> dict:
    """Issue the next token number for a counter (numbering restarts every day)."""
    issued = _ts(issued_at or datetime.now())
    with connect(path) as c:
        n = c.execute(
            "SELECT COALESCE(MAX(token_no), 0) + 1 FROM tokens "
            "WHERE counter = ? AND date(issued_at) = date(?)", (counter, issued)).fetchone()[0]
        cur = c.execute(
            "INSERT INTO tokens (counter, token_no, service_type, issued_at, source) "
            "VALUES (?, ?, ?, ?, ?)", (counter, n, service_type, issued, source))
        return {"id": cur.lastrowid, "counter": counter, "token_no": n, "issued_at": issued}


def serve_token(token_id: int, served_at=None, path: str | None = None) -> bool:
    """Mark that service started for a token. Returns False if unknown or already served."""
    with connect(path) as c:
        cur = c.execute("UPDATE tokens SET served_at = ? WHERE id = ? AND served_at IS NULL",
                        (_ts(served_at or datetime.now()), token_id))
        return cur.rowcount > 0


def finish_token(token_id: int, finished_at=None, path: str | None = None) -> bool:
    """Mark that service finished. Only valid after the token has been served."""
    with connect(path) as c:
        cur = c.execute(
            "UPDATE tokens SET finished_at = ? "
            "WHERE id = ? AND served_at IS NOT NULL AND finished_at IS NULL",
            (_ts(finished_at or datetime.now()), token_id))
        return cur.rowcount > 0


def load_tokens(path: str | None = None) -> pd.DataFrame:
    """All stored tokens as a DataFrame with parsed timestamps."""
    with connect(path) as c:
        df = pd.read_sql_query("SELECT * FROM tokens ORDER BY issued_at", c)
    for col in ("issued_at", "served_at", "finished_at"):
        df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


def insert_dataframe(df: pd.DataFrame, source: str = "upload", path: str | None = None) -> int:
    """Bulk insert tokens. Requires counter, issued_at, served_at columns."""
    analytics.require_columns(df)
    d = df.copy()
    for col in ("issued_at", "served_at", "finished_at"):
        d[col] = pd.to_datetime(d[col], errors="coerce") if col in d else pd.NaT
    d = d.dropna(subset=["counter", "issued_at"])
    if "token_no" not in d:
        d = d.sort_values("issued_at")
        d["token_no"] = d.groupby(["counter", d["issued_at"].dt.date]).cumcount() + 1
    if "service_type" not in d:
        d["service_type"] = "general"
    if "source" not in d:
        d["source"] = source
    rows = [(str(r.counter), int(r.token_no), str(r.service_type), _ts(r.issued_at),
             _ts(r.served_at), _ts(r.finished_at), str(r.source)) for r in d.itertuples()]
    with connect(path) as c:
        c.executemany(
            "INSERT INTO tokens (counter, token_no, service_type, issued_at, served_at, "
            "finished_at, source) VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
    return len(rows)


def clear_tokens(path: str | None = None) -> None:
    with connect(path) as c:
        c.execute("DELETE FROM tokens")
