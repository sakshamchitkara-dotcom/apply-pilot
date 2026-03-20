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
