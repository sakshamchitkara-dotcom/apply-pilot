"""Tailored application drafts, strictly grounded in the user's resume facts.

Drafts may only select and rephrase facts from the profile. Every draft is run
through `flag_unsupported`, which marks sentences containing numbers or skills
that do not appear in the resume so a human checks them before anything is sent.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from . import home, llm
from .resume import find_skills

WORD = re.compile(r"[a-z][a-z+#.]{2,}")
STOP = set("the and for with that this from your you our are was were will have has into their they them its "
           "about more work team role job using used build built across able who what how all can new".split())


def _words(s: str) -> set[str]:
    return {w.strip(".") for w in WORD.findall(s.lower())} - STOP


def rank_facts(profile: dict, posting: dict, k: int = 4) -> list[str]:
    """Resume facts most relevant to the posting (skill hits weigh more than word overlap)."""
    job_text = f"{posting['title']} {posting.get('description') or ''}"
    job_skills, job_words = set(find_skills(job_text)), _words(job_text)
    bullets = [b for sec in ("experience", "projects") for e in profile.get(sec, []) for b in e["bullets"]]
    scored = sorted(bullets, key=lambda b: (-(3 * len(set(find_skills(b)) & job_skills)
                                              + len(_words(b) & job_words)), bullets.index(b)))
    return scored[:k]


def _lower_first(s: str) -> str:
    return s[:1].lower() + s[1:] if s[:2] != s[:2].upper() else s


def template_draft(profile: dict, posting: dict) -> dict:
    facts = rank_facts(profile, posting)
    overlap = [s for s in find_skills(f"{posting['title']} {posting.get('description') or ''}")
               if s in profile.get("skills", [])][:5]
    edu = profile.get("education", [{}])[0].get("heading", "") if profile.get("education") else ""
    bullet_lines = "\n".join(f"- I {_lower_first(f)}." if not f.endswith(".") else f"- I {_lower_first(f)}"
                             for f in facts)
    letter = (
        f"Dear {posting['company']} hiring team,\n\n"
        f"I am applying for the {posting['title']} role. "
        + (f"My background is in {', '.join(overlap)}, which this role calls for. " if overlap else "")
        + "A few things from my resume that are relevant:\n\n"
        f"{bullet_lines}\n\n"
        + (f"I am currently studying at {edu}.\n\n" if edu else "")
        + f"Thank you for considering my application.\n\n{profile.get('name', '')}\n"
    )
    why_company = (f"[EDIT ME: add one specific, true reason you want to work at {posting['company']}. "
                   f"The template will not invent one.] The {posting['title']} role lines up with my experience in "
                   f"{', '.join(overlap) or 'the areas listed in my resume'}.")
    return {"cover_letter": letter, "why_company": why_company,
            "why_role": f"The role uses {', '.join(overlap) or 'skills'} I have applied before: {facts[0] if facts else ''}",
            "used_facts": facts, "engine": "template"}


DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "cover_letter": {"type": "string"},
        "why_company": {"type": "string"},
        "why_role": {"type": "string"},
        "used_facts": {"type": "array", "items": {"type": "string"},
                       "description": "verbatim resume facts the drafts rely on"},
    },
    "required": ["cover_letter", "why_company", "why_role", "used_facts"],
    "additionalProperties": False,
}
DRAFT_SYSTEM = """You draft job application materials for a candidate.
Hard rules:
- Use ONLY the numbered candidate facts and skills provided. You may select, reorder and rephrase them.
- Never invent employers, titles, dates, metrics, technologies, degrees or outcomes. Do not round or inflate numbers.
- Statements about the company may use only information in the job posting text. If there is nothing specific,
  write a short honest line and mark it with [EDIT ME].
- Cover letter: under 250 words, plain text, no placeholders except [EDIT ME].
- why_company and why_role: 2-4 sentences each.
- used_facts: copy verbatim every candidate fact you relied on."""


def claude_draft(profile: dict, posting: dict) -> dict | None:
    facts = profile.get("facts", [])
    user = ("CANDIDATE: " + profile.get("name", "") +
            "\nSKILLS: " + ", ".join(profile.get("skills", [])) +
            "\nFACTS:\n" + "\n".join(f"{i + 1}. {f}" for i, f in enumerate(facts)) +
            f"\n\nJOB POSTING: {posting['title']} at {posting['company']} ({posting.get('location') or 'n/a'})\n"
            + (posting.get("description") or "")[:10000])
    out = llm.structured(DRAFT_SYSTEM, user, DRAFT_SCHEMA, effort="medium")
    if out:
        out["engine"] = llm.MODEL
    return out


def flag_unsupported(text: str, profile: dict, posting: dict) -> list[str]:
    """Sentences that assert numbers or skills not found in the resume (posting numbers are allowed)."""
    resume_text = profile.get("raw_text", "") + "\n" + "\n".join(profile.get("facts", []))
    posting_text = f"{posting['title']} {posting['company']} {posting.get('description') or ''}"
    allowed_nums = {n.rstrip(".,") for n in re.findall(r"\d[\d,.]*", resume_text + "\n" + posting_text)}
    have = set(profile.get("skills", []))
    flags = []
    for sent in re.split(r"(?<=[.!?])\s+|\n+", text):
        sent = sent.strip()
        if not sent or "[EDIT ME" in sent:
            continue
        nums = [n.rstrip(".,") for n in re.findall(r"\d[\d,.]*", sent)]
        bad_nums = [n for n in nums if n and n not in allowed_nums and n.rstrip(".,") not in allowed_nums]
        bad_skills = [s for s in find_skills(sent) if s not in have]
        if bad_nums or bad_skills:
            what = ", ".join([f"number {n}" for n in bad_nums] + [f"skill {s}" for s in bad_skills])
            flags.append(f"{sent}  <-- not in resume: {what}")
    return flags


def draft(profile: dict, posting: dict, use_claude: bool = True) -> dict:
    d = (claude_draft(profile, posting) if use_claude else None) or template_draft(profile, posting)
    d["flags"] = [f for key in ("cover_letter", "why_company", "why_role")
                  for f in flag_unsupported(d[key], profile, posting)]
    return d


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60]


def write_packet(profile: dict, posting: dict, d: dict, resume_file: str | None = None,
                 root: Path | None = None) -> Path:
    """A ready-to-send application packet the human reviews and submits themselves."""
    out = (root or home() / "packets") / f"{slug(posting['company'])}--{slug(posting['title'])}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "cover_letter.md").write_text(d["cover_letter"])
    (out / "answers.md").write_text(f"## Why {posting['company']}?\n\n{d['why_company']}\n\n"
                                    f"## Why this role?\n\n{d['why_role']}\n")
    flags = "\n".join(f"- {f}" for f in d["flags"]) or "- none"
    (out / "REVIEW.md").write_text(
        f"# Review before sending\n\n**{posting['title']}** at **{posting['company']}**\n\n"
        f"Apply here (you submit, not the bot): {posting.get('apply_url') or posting['url']}\n\n"
        f"Drafted by: {d['engine']}\n\n## Claims to verify (not found in your resume)\n\n{flags}\n\n"
        "## Resume facts used\n\n" + "\n".join(f"- {f}" for f in d["used_facts"]) + "\n")
    resume_name = ""
    if resume_file and Path(resume_file).exists():
        resume_name = Path(resume_file).name
        shutil.copy(resume_file, out / resume_name)
    (out / "packet.json").write_text(json.dumps({
        "posting": {k: posting.get(k) for k in ("id", "company", "title", "location", "url", "apply_url")},
        "applicant": {k: profile.get(k) for k in ("name", "email", "phone", "links")},
        "resume_file": resume_name,
        "cover_letter": d["cover_letter"], "why_company": d["why_company"], "why_role": d["why_role"],
        "flags": d["flags"], "engine": d["engine"],
    }, indent=2))
    return out
