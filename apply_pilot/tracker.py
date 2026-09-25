"""Application tracker: status machine, event log, follow-up reminders, CSV export."""
from __future__ import annotations

import csv
import json
import sqlite3
from datetime import datetime, timedelta, timezone

from .db import now

SCHEMA = """
CREATE TABLE IF NOT EXISTS applications (
    posting_id TEXT PRIMARY KEY REFERENCES postings(id),
    status TEXT NOT NULL,
    score INTEGER NOT NULL DEFAULT 0,
    reasons TEXT NOT NULL DEFAULT '[]',
    packet_dir TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    follow_up_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    posting_id TEXT NOT NULL,
    status TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    at TEXT NOT NULL
);
"""

# found -> shortlisted -> approved -> applied -> interviewing -> offer/rejected
TRANSITIONS = {
    "found": {"shortlisted", "skipped"},
    "shortlisted": {"approved", "skipped", "found"},
    "approved": {"applied", "skipped", "shortlisted"},
    "applied": {"interviewing", "rejected", "offer"},
    "interviewing": {"offer", "rejected"},
    "skipped": {"shortlisted"},
    "offer": set(),
    "rejected": set(),
}
STATUSES = list(TRANSITIONS)
FOLLOW_UP_DAYS = {"applied": 7, "interviewing": 3}


class BadTransition(ValueError):
    pass


def init(conn: sqlite3.Connection) -> sqlite3.Connection:
    conn.executescript(SCHEMA)
    return conn


def upsert_score(conn, posting_id: str, score: int, reasons: list[str], status: str) -> None:
    """Record a match score; never downgrades an application a human has already acted on."""
    row = conn.execute("SELECT status FROM applications WHERE posting_id=?", (posting_id,)).fetchone()
    if row and row["status"] not in ("found", "shortlisted"):
        return
    conn.execute(
        "INSERT INTO applications (posting_id, status, score, reasons, updated_at) VALUES (?,?,?,?,?) "
        "ON CONFLICT(posting_id) DO UPDATE SET status=excluded.status, score=excluded.score, "
        "reasons=excluded.reasons, updated_at=excluded.updated_at",
        (posting_id, status, score, json.dumps(reasons), now()))
    if not row or row["status"] != status:
        conn.execute("INSERT INTO events (posting_id, status, note, at) VALUES (?,?,?,?)",
                     (posting_id, status, f"score {score}", now()))


def set_status(conn, posting_id: str, status: str, note: str = "") -> None:
    row = conn.execute("SELECT status FROM applications WHERE posting_id=?", (posting_id,)).fetchone()
    if not row:
        raise BadTransition(f"{posting_id} is not tracked; run shortlist first")
    if status not in TRANSITIONS[row["status"]]:
        raise BadTransition(f"{row['status']} -> {status} not allowed")
    days = FOLLOW_UP_DAYS.get(status)
    follow = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(timespec="seconds") if days else ""
    conn.execute("UPDATE applications SET status=?, follow_up_at=?, updated_at=?, "
                 "notes=CASE WHEN ?='' THEN notes ELSE ? END WHERE posting_id=?",
                 (status, follow, now(), note, note, posting_id))
    conn.execute("INSERT INTO events (posting_id, status, note, at) VALUES (?,?,?,?)",
                 (posting_id, status, note, now()))
    conn.commit()


def rows(conn, status: str | None = None, limit: int = 1000):
    q = ("SELECT a.*, p.company, p.title, p.location, p.url, p.apply_url, p.source, p.description, "
         "p.remote, p.flags, p.salary_min FROM applications a JOIN postings p ON p.id=a.posting_id")
    args: tuple = ()
    if status:
        q += " WHERE a.status=?"
        args = (status,)
    return conn.execute(q + " ORDER BY a.score DESC, a.updated_at DESC LIMIT ?", args + (limit,)).fetchall()


def due_follow_ups(conn, at: datetime | None = None):
    at = (at or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    return conn.execute(
        "SELECT a.*, p.company, p.title FROM applications a JOIN postings p ON p.id=a.posting_id "
        "WHERE a.follow_up_at != '' AND a.follow_up_at <= ? ORDER BY a.follow_up_at", (at,)).fetchall()


def export_csv(conn, path) -> int:
    cols = ["status", "score", "company", "title", "location", "url", "follow_up_at", "updated_at", "notes", "packet_dir"]
    rs = rows(conn)
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rs:
            w.writerow([r[c] for c in cols])
    return len(rs)
