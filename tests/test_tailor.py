import json
from pathlib import Path

from apply_pilot import llm, resume, tailor

ROOT = Path(__file__).parents[1]
PROFILE = resume.ingest(ROOT / "examples" / "sample_resume.md")
POST = {"id": "greenhouse:acme:1", "company": "Acme", "title": "Backend Software Engineer Intern",
        "location": "New York, NY", "url": "https://x.test/1", "apply_url": "https://x.test/1/apply",
        "description": "You will build Python services on PostgreSQL and Kubernetes serving 10,000 merchants."}


def test_template_draft_only_uses_resume_facts():
    d = tailor.draft(PROFILE, POST, use_claude=False)
    assert d["engine"] == "template"
    assert any("PostgreSQL" in f for f in d["used_facts"])
    for f in d["used_facts"]:
        assert f in PROFILE["facts"]
    assert d["flags"] == []  # template never introduces unsupported claims
    assert "[EDIT ME" in d["why_company"]


def test_flags_fabricated_numbers_and_skills():
    text = "I cut latency from 900ms to 120ms. I led a team of 12 engineers. I ran Kubernetes clusters."
    flags = tailor.flag_unsupported(text, PROFILE, POST)
    assert len(flags) == 2
    assert "number 12" in flags[0] and "skill Kubernetes" in flags[1]


def test_claude_draft_is_still_checked(monkeypatch):
    monkeypatch.setattr(llm, "structured", lambda *a, **k: {
        "cover_letter": "I scaled Kubernetes to 99 nodes.", "why_company": "Acme serves 10,000 merchants.",
        "why_role": "I built a REST API in Python.", "used_facts": []})
    d = tailor.draft(PROFILE, POST)
    assert d["engine"] == llm.MODEL
    assert len(d["flags"]) == 1 and "Kubernetes" in d["flags"][0]


def test_write_packet(tmp_path):
    d = tailor.draft(PROFILE, POST, use_claude=False)
    out = tailor.write_packet(PROFILE, POST, d, str(ROOT / "examples" / "sample_resume.md"), root=tmp_path)
    assert {p.name for p in out.iterdir()} == {"cover_letter.md", "answers.md", "REVIEW.md", "packet.json", "sample_resume.md"}
    pk = json.loads((out / "packet.json").read_text())
    assert pk["applicant"]["email"] == "riley.quinn@example.com"
