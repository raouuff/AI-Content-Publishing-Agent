"""SQLite storage layer for the Part 2 agent.

ALL SQL lives in this single module so the storage backend can be swapped
later — the rest of the app only calls these functions. Data goes to ONE file
(content.db), separate from Part 1's expenses database so the two agents stay
independent. Tables are created automatically on first use.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DB_PATH = Path(os.getenv("CONTENT_DB_PATH", "content.db"))
if not DB_PATH.is_absolute():
    DB_PATH = ROOT / DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS content (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    source_text TEXT NOT NULL,
    linkedin_post TEXT DEFAULT '',
    newsletter_summary TEXT DEFAULT '',
    website_announcement TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'DRAFT',
    approved_at TEXT,
    approved_content_hash TEXT,
    selected_channels TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS publications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_id INTEGER NOT NULL REFERENCES content(id),
    channel TEXT NOT NULL,
    status TEXT NOT NULL,
    published_url TEXT,
    published_at TEXT NOT NULL,
    error_message TEXT,
    content_hash TEXT
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- #
# Low-level helpers (single short-lived connection per call keeps it simple)  #
# --------------------------------------------------------------------------- #

def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = get_conn()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def _write(sql: str, params: tuple) -> int:
    conn = get_conn()
    try:
        cur = conn.execute(sql, params)
        conn.commit()
        return cur.lastrowid or 0
    finally:
        conn.close()


def _read_all(sql: str, params: tuple = ()) -> list[dict]:
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _read_one(sql: str, params: tuple = ()) -> dict | None:
    rows = _read_all(sql, params)
    return rows[0] if rows else None


# --------------------------------------------------------------------------- #
# Content table                                                                 #
# --------------------------------------------------------------------------- #

def insert_content(title: str, source_text: str, linkedin_post: str,
                   newsletter_summary: str, website_announcement: str) -> int:
    """Insert one row per input; starts in DRAFT. Returns the new content id."""
    return _write(
        "INSERT INTO content (title, source_text, linkedin_post, newsletter_summary, "
        "website_announcement, status, created_at) VALUES (?, ?, ?, ?, ?, 'DRAFT', ?)",
        (title.strip() or None, source_text, linkedin_post, newsletter_summary,
         website_announcement, now_iso()),
    )


def get_content(content_id: int) -> dict | None:
    return _read_one("SELECT * FROM content WHERE id = ?", (content_id,))


def list_contents(status: str | None = None, created_since: str | None = None) -> list[dict]:
    """All rows, newest first. Optional filters: exact status, created date >=."""
    conditions, params = [], []
    if status:
        conditions.append("status = ?")
        params.append(status)
    if created_since:
        conditions.append("created_at >= ?")
        params.append(f"{created_since}T00:00:00")
    sql = "SELECT * FROM content"
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    return _read_all(sql + " ORDER BY id DESC", tuple(params))


def update_drafts(content_id: int, drafts: dict) -> None:
    """Overwrite the three draft texts (human edits)."""
    _write(
        "UPDATE content SET linkedin_post = ?, newsletter_summary = ?, "
        "website_announcement = ? WHERE id = ?",
        (drafts["linkedin_post"], drafts["newsletter_summary"],
         drafts["website_announcement"], content_id),
    )


def set_status(content_id: int, status: str, approved_at: str | None = None,
               approved_content_hash: str | None = None,
               selected_channels: list | None = None) -> None:
    """Set the workflow status; optionally refresh the approval bookkeeping."""
    _write("UPDATE content SET status = ? WHERE id = ?", (status, content_id))
    if approved_at is not None:
        _write("UPDATE content SET approved_at = ? WHERE id = ?", (approved_at, content_id))
    if approved_content_hash is not None:
        _write("UPDATE content SET approved_content_hash = ? WHERE id = ?",
               (approved_content_hash, content_id))
    if selected_channels is not None:
        _write("UPDATE content SET selected_channels = ? WHERE id = ?",
               (json.dumps(selected_channels), content_id))


# --------------------------------------------------------------------------- #
# Publications table                                                            #
# --------------------------------------------------------------------------- #

def record_publication(content_id: int, channel: str, status: str,
                       published_url: str | None = None,
                       error_message: str | None = None,
                       content_hash: str | None = None) -> int:
    """One row per publication attempt (SUCCEEDED or FAILED)."""
    return _write(
        "INSERT INTO publications (content_id, channel, status, published_url, "
        "published_at, error_message, content_hash) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (content_id, channel, status, published_url, now_iso(), error_message, content_hash),
    )


def get_published(content_id: int, channel: str) -> dict | None:
    """Latest SUCCEEDED publication for this content + channel (idempotency check)."""
    return _read_one(
        "SELECT * FROM publications WHERE content_id = ? AND channel = ? "
        "AND status = 'SUCCEEDED' ORDER BY id DESC LIMIT 1",
        (content_id, channel),
    )


def list_publications(status: str | None = None, created_since: str | None = None,
                      content_id: int | None = None) -> list[dict]:
    """Every publication attempt, newest first. Filters for the log tab."""
    conditions, params = [], []
    if status:
        conditions.append("status = ?")
        params.append(status)
    if created_since:
        conditions.append("published_at >= ?")
        params.append(f"{created_since}T00:00:00")
    if content_id is not None:
        conditions.append("content_id = ?")
        params.append(content_id)
    sql = "SELECT * FROM publications"
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    return _read_all(sql + " ORDER BY id DESC", tuple(params))
