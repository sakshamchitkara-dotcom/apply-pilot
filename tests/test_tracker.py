from datetime import datetime, timedelta, timezone

import pytest

from apply_pilot import db, tracker


@pytest.fixture
def conn(tmp_path):
    c = tracker.init(db.connect(tmp_path / "t.db"))
    db.upsert(c, [db.Posting(source="lever", board="acme", external_id="1", company="Acme",
                             title="SWE Intern", url="https://x.test/1")])
    return c


def test_status_machine_and_follow_up(conn):
    pid = "lever:acme:1"
    tracker.upsert_score(conn, pid, 72, ["skills"], "shortlisted")
    with pytest.raises(tracker.BadTransition):
        tracker.set_status(conn, pid, "applied")  # must be approved first
    tracker.set_status(conn, pid, "approved")
    tracker.set_status(conn, pid, "applied", "submitted by hand")
    assert not tracker.due_follow_ups(conn)
    assert tracker.due_follow_ups(conn, datetime.now(timezone.utc) + timedelta(days=8))
    # re-scoring never clobbers a human decision
    tracker.upsert_score(conn, pid, 10, [], "found")
    assert tracker.rows(conn)[0]["status"] == "applied"
    events = [r["status"] for r in conn.execute("SELECT status FROM events ORDER BY id")]
    assert events == ["shortlisted", "approved", "applied"]


def test_csv_export(conn, tmp_path):
    tracker.upsert_score(conn, "lever:acme:1", 50, [], "shortlisted")
    assert tracker.export_csv(conn, tmp_path / "out.csv") == 1
    text = (tmp_path / "out.csv").read_text()
    assert text.startswith("status,score,company") and "Acme" in text
