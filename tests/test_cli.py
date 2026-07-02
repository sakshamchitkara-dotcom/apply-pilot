from apply_pilot import cli, db, http as http_mod
from conftest import FIX


def fake_raw_get(self, url):
    routes = {"https://boards-api.greenhouse.io/v1/boards/stripe/": "greenhouse_stripe.json",
              "https://api.lever.co/v0/postings/palantir": "lever_palantir.json",
              "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/": "simplify_readme.md"}
    for k, v in routes.items():
        if url.startswith(k):
            return (FIX / v).read_text()
    raise AssertionError(url)


def test_fetch_command_is_idempotent(monkeypatch, capsys):
    monkeypatch.setattr(http_mod.Http, "_raw_get", fake_raw_get)
    args = ["fetch", "--only", "stripe,palantir", "--lists", "simplify-internships"]
    assert cli.main(args) == 0
    n = db.connect().execute("SELECT count(*) FROM postings").fetchone()[0]
    assert n == 4 + 4 + 12
    cli.main(args)
    assert "0 new" in capsys.readouterr().out.splitlines()[-1]


def test_pipeline_ingest_shortlist_tailor(monkeypatch, capsys, tmp_path):
    from pathlib import Path
    root = Path(__file__).parents[1]
    monkeypatch.setattr(http_mod.Http, "_raw_get", fake_raw_get)
    prof, prefs = str(tmp_path / "profile.json"), str(root / "examples" / "preferences.toml")
    cli.main(["ingest-resume", str(root / "examples" / "sample_resume.md"), "--profile", prof])
    cli.main(["fetch", "--only", "stripe,palantir", "--lists", "simplify-internships"])
    cli.main(["shortlist", "--profile", prof, "--prefs", prefs])
    out = capsys.readouterr().out
    assert "shortlisted" in out
    cli.main(["tailor", "--profile", prof, "--prefs", prefs, "--top", "1"])
    assert "packet (template, 0 flagged claims)" in capsys.readouterr().out


def test_review_gate(monkeypatch, capsys, tmp_path):
    from pathlib import Path
    import pytest
    from apply_pilot import tracker
    root = Path(__file__).parents[1]
    monkeypatch.setattr(http_mod.Http, "_raw_get", fake_raw_get)
    prof, prefs = str(tmp_path / "profile.json"), str(root / "examples" / "preferences.toml")
    cli.main(["ingest-resume", str(root / "examples" / "sample_resume.md"), "--profile", prof])
    cli.main(["fetch", "--only", "stripe", "--lists", "simplify-internships"])
    cli.main(["shortlist", "--profile", prof, "--prefs", prefs])
    conn = tracker.init(db.connect())
    ids = [r["posting_id"] for r in tracker.rows(conn, "shortlisted")]
    assert len(ids) >= 2
    with pytest.raises(tracker.BadTransition):  # cannot jump straight to applied
        cli.main(["mark", ids[0], "applied"])
    answers = iter(["a", "s", "q"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    cli.main(["review", "--profile", prof, "--prefs", prefs])
    st = {r["posting_id"]: r["status"] for r in tracker.rows(conn)}
    assert st[ids[0]] == "approved" and st[ids[1]] == "skipped"
    cli.main(["mark", ids[0], "applied", "--note", "submitted by hand"])
    assert tracker.rows(conn, "applied")[0]["follow_up_at"]


def test_apply_refuses_unapproved(monkeypatch, tmp_path):
    import pytest
    from apply_pilot import tracker
    monkeypatch.setattr(http_mod.Http, "_raw_get", fake_raw_get)
    cli.main(["fetch", "--only", "stripe"])
    conn = tracker.init(db.connect())
    pid = conn.execute("SELECT id FROM postings LIMIT 1").fetchone()[0]
    tracker.upsert_score(conn, pid, 90, [], "shortlisted")
    conn.commit()
    with pytest.raises(SystemExit) as e:
        cli.main(["apply", pid, "--browser"])
    assert "not approved" in str(e.value)


def test_remind_and_export(capsys, tmp_path):
    cli.main(["remind"])
    assert "no follow-ups due" in capsys.readouterr().out
    cli.main(["export", "--out", str(tmp_path / "a.csv")])
    assert (tmp_path / "a.csv").read_text().startswith("status,score")


def test_daily_never_applies(monkeypatch, capsys, tmp_path):
    from pathlib import Path
    from apply_pilot import tracker
    root = Path(__file__).parents[1]
    monkeypatch.setattr(http_mod.Http, "_raw_get", fake_raw_get)
    prof = str(tmp_path / "profile.json")
    cli.main(["ingest-resume", str(root / "examples" / "sample_resume.md"), "--profile", prof])
    cli.main(["daily", "--only", "stripe,palantir", "--lists", "simplify-internships", "--profile", prof,
              "--prefs", str(root / "examples" / "preferences.toml")])
    out = capsys.readouterr().out
    assert "new shortlisted role" in out and "dry run" in out
    statuses = {r["status"] for r in tracker.rows(tracker.init(db.connect()))}
    assert statuses <= {"found", "shortlisted"}
