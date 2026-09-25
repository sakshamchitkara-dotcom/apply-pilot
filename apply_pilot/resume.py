"""Resume ingestion: PDF / DOCX / Markdown / text -> structured profile JSON.

The profile's `facts` list is the grounding corpus: every sentence a draft may
use must be traceable to one of these lines.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

SECTION_ALIASES = {
    "summary": ["summary", "profile", "about", "objective"],
    "experience": ["experience", "work experience", "professional experience", "employment"],
    "education": ["education"],
    "skills": ["skills", "technical skills", "technologies", "tools"],
    "projects": ["projects", "personal projects", "selected projects"],
    "awards": ["awards", "honors", "achievements", "certifications", "leadership", "activities"],
}
BULLET = re.compile(r"^\s*(?:[-*•▪◦]|\d+\.)\s+")


@lru_cache(maxsize=1)
def skill_vocab() -> dict[str, list[str]]:
    return json.loads((Path(__file__).parent / "data" / "skills.json").read_text())


@lru_cache(maxsize=None)
def _skill_patterns():
    pats = []
    for canon, aliases in skill_vocab().items():
        for a in aliases:
            cs = a.startswith("=")
            a = a.lstrip("=")
            pats.append((canon, re.compile(rf"(?<![\w+#.]){re.escape(a)}(?![\w+#])", 0 if cs else re.I)))
    return pats


def find_skills(text: str) -> list[str]:
    """Canonical skills mentioned in `text`, in vocabulary order."""
    found = []
    for canon, pat in _skill_patterns():
        if canon not in found and pat.search(text):
            found.append(canon)
    return found


def _heading(line: str) -> str | None:
    s = re.sub(r"^#+\s*|[*_:]+", "", line).strip().lower()
    for key, names in SECTION_ALIASES.items():
        if s in names:
            return key
    return None


def parse_text(text: str) -> dict:
    lines = [l.rstrip() for l in text.splitlines()]
    nonempty = [l for l in lines if l.strip()]
    name = re.sub(r"^#+\s*", "", nonempty[0]).strip() if nonempty else ""
    email = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text)
    phone = re.search(r"\+?\(?\d[\d\s().-]{7,}\d", text)
    links = re.findall(r"(?:https?://)?(?:www\.)?(?:github\.com|linkedin\.com/in|[\w-]+\.(?:dev|io|me))/?[\w./-]*", text)

    sections: dict[str, list[str]] = {"header": []}
    cur = "header"
    for l in lines[1:] if nonempty and lines and lines[0].strip() == nonempty[0].strip() else lines:
        h = _heading(l) if len(l) < 40 else None
        if h:
            cur = h
            sections.setdefault(cur, [])
        elif l.strip():
            sections.setdefault(cur, []).append(l.strip())

    def entries(sec):
        """Group a section into entries: a non-bullet line starts one, bullets attach."""
        out = []
        for l in sections.get(sec, []):
            if BULLET.match(l) and out:
                out[-1]["bullets"].append(BULLET.sub("", l))
            else:
                out.append({"heading": re.sub(r"^#+\s*|\*\*", "", l).strip(), "bullets": []})
        return out

    skills_lines = " ".join(sections.get("skills", []))
    listed = [s.strip(" .") for s in re.split(r"[,|;•]|\s{2,}", re.sub(r"^[\w ]+:\s*", "", skills_lines)) if s.strip()]
    listed = [re.sub(r"^\*\*[^*]+\*\*:?\s*|^[A-Za-z ]+:\s*", "", s) for s in listed]
    skills = find_skills(text)
    extra = [s for s in listed if s and len(s) < 30 and s not in skills and not find_skills(s)]

    facts = []
    for sec in ("summary", "experience", "projects", "education", "awards"):
        for e in entries(sec):
            facts.append(e["heading"])
            facts.extend(e["bullets"])
    return {
        "name": name,
        "email": email.group(0) if email else "",
        "phone": phone.group(0).strip() if phone else "",
        "links": sorted(set(links)),
        "summary": " ".join(sections.get("summary", [])),
        "skills": skills + extra,
        "experience": entries("experience"),
        "projects": entries("projects"),
        "education": entries("education"),
        "facts": [f for f in facts if f],
        "raw_text": text,
    }


def read_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader  # optional extra: apply-pilot[pdf]
        return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
    if suffix == ".docx":
        import docx  # optional extra: apply-pilot[docx]
        out = []
        for para in docx.Document(str(path)).paragraphs:
            style = (para.style.name or "").lower() if para.style is not None else ""
            prefix = "# " if style.startswith("heading") or style == "title" else \
                "- " if "list" in style else ""
            out.append(prefix + para.text)
        return "\n".join(out)
    return path.read_text()


def ingest(path: str | Path) -> dict:
    path = Path(path)
    profile = parse_text(read_text(path))
    profile["source_file"] = path.name
    return profile
