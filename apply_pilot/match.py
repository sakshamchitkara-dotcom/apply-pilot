"""Preferences, hard filters and match scoring (heuristic, optionally Claude)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

from .resume import find_skills

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

DEFAULT_PREFS = {
    "roles": [], "exclude_title_keywords": [], "locations": [], "remote_ok": True,
    "seniority": "any", "needs_sponsorship": False, "salary_floor": 0,
    "exclude_companies": [], "min_score": 35,
}
INTERN_RE = re.compile(r"\b(intern|internship|co-?op|summer analyst)\b", re.I)
NEWGRAD_RE = re.compile(r"\b(new grad|graduate|university|entry[- ]level|junior|early career|associate)\b", re.I)


def load_prefs(path: str | Path | None) -> dict:
    prefs = dict(DEFAULT_PREFS)
    if path and Path(path).exists():
        prefs.update(tomllib.loads(Path(path).read_text()))
    return prefs


def _any_in(needles, hay: str) -> bool:
    hay = hay.lower()
    return any(n.lower() in hay for n in needles)


def check_filters(p: dict, prefs: dict) -> str | None:
    """Return a rejection reason, or None if the posting passes every hard filter."""
    title, loc = p["title"], p.get("location") or ""
    if _any_in(prefs["exclude_companies"], p["company"]) and prefs["exclude_companies"]:
        return "excluded company"
    if prefs["exclude_title_keywords"] and re.search(
            r"\b(" + "|".join(map(re.escape, prefs["exclude_title_keywords"])) + r")\b", title, re.I):
        return "excluded title keyword"
    if prefs["roles"] and not _any_in(prefs["roles"], title):
        return "role not wanted"
    is_intern = bool(INTERN_RE.search(title)) or "intern" in (p.get("employment_type") or "").lower()
    if prefs["seniority"] == "internship" and not is_intern:
        return "not an internship"
    if prefs["seniority"] == "new_grad" and (is_intern or not NEWGRAD_RE.search(title)):
        return "not new-grad"
    if prefs["locations"] and loc and not (_any_in(prefs["locations"], loc)
                                           or (prefs["remote_ok"] and p.get("remote"))):
        return "location"
    flags = (p.get("flags") or "")
    if prefs["needs_sponsorship"] and ("no_sponsorship" in flags or "us_citizen_only" in flags):
        return "no visa sponsorship"
    if prefs["salary_floor"] and p.get("salary_min") and p["salary_min"] < prefs["salary_floor"]:
        return "below salary floor"
    return None


def heuristic_score(p: dict, profile: dict, prefs: dict) -> tuple[int, list[str]]:
    """0-100 score from skill overlap, role/seniority/location fit. Deterministic, offline."""
    text = f"{p['title']}\n{p.get('description') or ''}"
    job_skills = find_skills(text)
    have = set(profile.get("skills", []))
    hit = [s for s in job_skills if s in have]
    miss = [s for s in job_skills if s not in have]
    reasons = []
    if job_skills:
        # A title-only listing naming one skill shouldn't count as a perfect match:
        # blend towards a neutral 20 until the posting names ~4 skills.
        conf = min(1.0, len(job_skills) / 4)
        skill_pts = conf * 50 * len(hit) / len(job_skills) + (1 - conf) * 20
        reasons.append(f"skills {len(hit)}/{len(job_skills)}: {', '.join(hit) or '-'}"
                       + (f"; missing {', '.join(miss[:6])}" if miss else ""))
    else:
        skill_pts = 20
        reasons.append("no recognisable skills in posting text")
    role_pts = 25 if prefs["roles"] and _any_in(prefs["roles"], p["title"]) else (10 if not prefs["roles"] else 0)
    if role_pts == 25:
        reasons.append("title matches preferred role")
    sen_pts = 0
    if prefs["seniority"] == "internship" and INTERN_RE.search(p["title"]):
        sen_pts = 15
    elif prefs["seniority"] == "new_grad" and NEWGRAD_RE.search(p["title"]):
        sen_pts = 15
    elif prefs["seniority"] == "any":
        sen_pts = 8
    loc_pts = 10 if (p.get("remote") and prefs["remote_ok"]) or _any_in(prefs["locations"], p.get("location") or "") else 0
    if loc_pts:
        reasons.append("location fits")
    return round(min(100, skill_pts + role_pts + sen_pts + loc_pts)), reasons


RUBRIC_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer", "description": "0-100 overall fit"},
        "reasons": {"type": "array", "items": {"type": "string"}},
        "gaps": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["score", "reasons", "gaps"],
    "additionalProperties": False,
}
RUBRIC_SYSTEM = """You score how well a candidate fits a job posting. Use only the candidate facts given.
Rubric (100 total): required skills/technologies present in facts (40), relevant experience or projects (30),
seniority/level fit (15), stated constraints such as location, visa, degree (15).
Reasons must cite specific candidate facts. List missing requirements under gaps. Never assume unstated skills."""


def claude_score(p: dict, profile: dict) -> tuple[int, list[str]] | None:
    from . import llm
    user = (f"CANDIDATE SKILLS: {', '.join(profile.get('skills', []))}\n"
            "CANDIDATE FACTS:\n" + "\n".join(f"- {f}" for f in profile.get("facts", [])) +
            f"\n\nJOB: {p['title']} at {p['company']} ({p.get('location') or 'n/a'})\n"
            f"{(p.get('description') or '')[:8000]}")
    out = llm.structured(RUBRIC_SYSTEM, user, RUBRIC_SCHEMA, effort="low", max_tokens=4000)
    if not out:
        return None
    reasons = [f"claude: {r}" for r in out["reasons"]] + [f"gap: {g}" for g in out["gaps"]]
    return max(0, min(100, int(out["score"]))), reasons


def score(p: dict, profile: dict, prefs: dict, use_claude: bool = False) -> tuple[int, list[str]]:
    """Claude rubric when requested and available, else the heuristic."""
    if use_claude:
        got = claude_score(p, profile)
        if got:
            return got
    return heuristic_score(p, profile, prefs)


if __name__ == "__main__":  # quick self-check
    prefs = dict(DEFAULT_PREFS, roles=["software"], seniority="internship", locations=["NYC"])
    p = {"title": "Software Engineer Intern", "company": "X", "location": "NYC", "description": "Python, Go"}
    assert check_filters(p, prefs) is None
    assert heuristic_score(p, {"skills": ["Python", "Go"]}, prefs)[0] == 100
