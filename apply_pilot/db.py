"""SQLite store for normalized postings (deduplicated across sources)."""
from __future__ import annotations

import re
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import home

SCHEMA = """
CREATE TABLE IF NOT EXISTS postings (
    id TEXT PRIMARY KEY,            -- source:board:external id
    source TEXT NOT NULL,
    company TEXT NOT NULL,
    title TEXT NOT NULL,
    location TEXT NOT NULL DEFAULT '',
    remote INTEGER NOT NULL DEFAULT 0,
    url TEXT NOT NULL,
    apply_url TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    employment_type TEXT NOT NULL DEFAULT '',
    salary_min INTEGER,
    posted_at TEXT NOT NULL DEFAULT '',
    flags TEXT NOT NULL DEFAULT '',
    dedupe_key TEXT NOT NULL UNIQUE,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Posting:
    source: str
    board: str
    external_id: str
    company: str
    title: str
    url: str
    location: str = ""
    remote: bool = False
    apply_url: str = ""
    description: str = ""
    employment_type: str = ""
    salary_min: int | None = None
    posted_at: str = ""
    flags: list[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        return f"{self.source}:{self.board}:{self.external_id}"

    @property
    def dedupe_key(self) -> str:
        """Same company + title + location = same job, whichever list we saw it on."""
        norm = lambda s: re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()
        return "|".join([norm(self.company), norm(self.title), norm(self.location)])


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path or home() / "apply-pilot.db"))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def upsert(conn: sqlite3.Connection, postings) -> tuple[int, int]:
    """Insert new postings, refresh last_seen on known ones. Returns (new, duplicates)."""
    new = dup = 0
    ts = now()
    for p in postings:
        row = conn.execute("SELECT id FROM postings WHERE id=? OR dedupe_key=?",
                           (p.id, p.dedupe_key)).fetchone()
        if row:
            conn.execute("UPDATE postings SET last_seen=? WHERE id=?", (ts, row["id"]))
            dup += 1
            continue
        d = asdict(p)
        d.pop("board"), d.pop("external_id")
        d.update(id=p.id, dedupe_key=p.dedupe_key, flags=",".join(p.flags),
                 remote=int(p.remote), first_seen=ts, last_seen=ts)
        cols = ",".join(d)
        conn.execute(f"INSERT INTO postings ({cols}) VALUES ({','.join('?' * len(d))})",
                     tuple(d.values()))
        new += 1
    conn.commit()
    return new, dup
