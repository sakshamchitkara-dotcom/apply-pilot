from pathlib import Path

from apply_pilot import match, resume

ROOT = Path(__file__).parents[1]
PREFS = match.load_prefs(ROOT / "examples" / "preferences.toml")
PROFILE = resume.ingest(ROOT / "examples" / "sample_resume.md")


def post(**kw):
    base = {"title": "Software Engineer Intern", "company": "Acme", "location": "New York, NY",
            "description": "Python, PostgreSQL, Docker, Kubernetes", "remote": 0, "flags": "", "salary_min": None}
    base.update(kw)
    return base


def test_filters():
    assert match.check_filters(post(), PREFS) is None
    assert match.check_filters(post(title="Senior Software Engineer"), PREFS) == "excluded title keyword"
    assert match.check_filters(post(title="Software Engineer"), PREFS) == "not an internship"
    assert match.check_filters(post(title="Account Executive Intern"), PREFS) == "role not wanted"
    assert match.check_filters(post(location="Berlin, Germany"), PREFS) == "location"
    assert match.check_filters(post(location="Berlin; Remote", remote=1), PREFS) is None
    assert match.check_filters(post(flags="no_sponsorship"), dict(PREFS, needs_sponsorship=True)) == "no visa sponsorship"
    assert match.check_filters(post(salary_min=50000), dict(PREFS, salary_floor=60000)) == "below salary floor"
    assert match.check_filters(post(company="Acme"), dict(PREFS, exclude_companies=["acme"])) == "excluded company"


def test_heuristic_prefers_overlap():
    good, why = match.heuristic_score(post(), PROFILE, PREFS)
    bad, _ = match.heuristic_score(post(description="Kotlin, Swift, iOS, Android"), PROFILE, PREFS)
    assert good > bad and 0 <= bad <= 100
    assert any("missing Kubernetes" in r for r in why)


def test_claude_score_used_when_available(monkeypatch):
    from apply_pilot import llm
    seen = {}

    def fake(system, user, schema, **kw):
        seen["user"] = user
        return {"score": 81, "reasons": ["FastAPI + PostgreSQL internship"], "gaps": ["Kubernetes"]}
    monkeypatch.setattr(llm, "structured", fake)
    s, why = match.score(post(), PROFILE, PREFS, use_claude=True)
    assert s == 81 and "gap: Kubernetes" in why
    assert "p95 query latency" in seen["user"]  # grounded on resume facts


def test_claude_unavailable_falls_back():
    s, why = match.score(post(), PROFILE, PREFS, use_claude=True)  # no API key in tests
    assert (s, why) == match.heuristic_score(post(), PROFILE, PREFS)


def test_thin_postings_do_not_score_perfect():
    thin, _ = match.heuristic_score(post(title="Python Software Engineer Intern", description=""), PROFILE, PREFS)
    rich, _ = match.heuristic_score(post(description="Python, PostgreSQL, Docker, FastAPI, Redis"), PROFILE, PREFS)
    assert thin < rich == 100


def test_passing_filters_alone_does_not_shortlist():
    """Calibration: role/seniority/location fit is implied by the filters, so it can't clear min_score alone."""
    no_evidence, _ = match.heuristic_score(post(title="Software Engineer Intern", description=""), PROFILE, PREFS)
    wrong_stack, _ = match.heuristic_score(post(description="Kotlin, Swift, iOS, Android"), PROFILE, PREFS)
    some_overlap, _ = match.heuristic_score(post(description="Python and Kubernetes"), PROFILE, PREFS)
    assert wrong_stack < no_evidence < PREFS["min_score"] <= some_overlap
