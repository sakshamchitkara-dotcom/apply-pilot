"""Job sources that permit programmatic access, normalized to `Posting`.

Only official public job-board APIs, the community GitHub internship lists and
company career pages (robots.txt respected) are supported. LinkedIn, Indeed and
Handshake are deliberately absent: their terms prohibit scraping/automation.
"""
from __future__ import annotations

import html
import re

from .db import Posting
from .http import Http

REMOTE_RE = re.compile(r"\bremote\b", re.I)


def strip_html(s: str) -> str:
    s = re.sub(r"<(br|/p|/li|/h\d|/div)[^>]*>", "\n", s or "", flags=re.I)
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    return re.sub(r"[ \t\xa0]+", " ", re.sub(r"\n\s*\n+", "\n\n", s)).strip()


def greenhouse(http: Http, token: str, company: str | None = None) -> list[Posting]:
    data = http.get_json(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true")
    out = []
    for j in data.get("jobs", []):
        loc = (j.get("location") or {}).get("name", "")
        out.append(Posting(
            source="greenhouse", board=token, external_id=str(j["id"]),
            company=company or j.get("company_name") or token, title=j["title"].strip(),
            location=loc, remote=bool(REMOTE_RE.search(loc)),
            url=j["absolute_url"], apply_url=j["absolute_url"],
            # Greenhouse double-encodes: content is HTML-escaped HTML.
            description=strip_html(html.unescape(j.get("content", ""))),
            posted_at=j.get("first_published") or j.get("updated_at") or "",
        ))
    return out


def lever(http: Http, token: str, company: str | None = None) -> list[Posting]:
    data = http.get_json(f"https://api.lever.co/v0/postings/{token}?mode=json")
    out = []
    for j in data:
        cat = j.get("categories") or {}
        locs = cat.get("allLocations") or [cat.get("location", "")]
        body = [j.get("descriptionPlain", "")]
        body += [f"{li.get('text', '')}\n{strip_html(li.get('content', ''))}" for li in j.get("lists", [])]
        body.append(j.get("additionalPlain", ""))
        sal = j.get("salaryRange") or {}
        out.append(Posting(
            source="lever", board=token, external_id=j["id"], company=company or token,
            title=j["text"].strip(), location="; ".join(l for l in locs if l),
            remote=j.get("workplaceType") == "remote" or any(REMOTE_RE.search(l or "") for l in locs),
            url=j["hostedUrl"], apply_url=j.get("applyUrl", j["hostedUrl"]),
            description="\n\n".join(b for b in body if b).strip(),
            employment_type=cat.get("commitment", ""),
            salary_min=sal.get("min") if sal.get("interval", "per-year-salary") == "per-year-salary" else None,
            posted_at=str(j.get("createdAt", "")),
        ))
    return out


def _ashby_salary_min(comp: dict | None) -> int | None:
    for c in (comp or {}).get("summaryComponents", []):
        if c.get("compensationType") == "Salary" and c.get("interval") == "1 YEAR" and c.get("minValue"):
            return int(c["minValue"])
    return None


def ashby(http: Http, token: str, company: str | None = None) -> list[Posting]:
    data = http.get_json(f"https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true")
    out = []
    for j in data.get("jobs", []):
        if j.get("isListed") is False:
            continue
        locs = [j.get("location", "")] + [s.get("location", "") for s in j.get("secondaryLocations", [])]
        out.append(Posting(
            source="ashby", board=token, external_id=j["id"], company=company or token,
            title=j["title"].strip(), location="; ".join(l for l in locs if l),
            remote=bool(j.get("isRemote")) or j.get("workplaceType") == "Remote",
            url=j["jobUrl"], apply_url=j.get("applyUrl", j["jobUrl"]),
            description=j.get("descriptionPlain") or strip_html(j.get("descriptionHtml", "")),
            employment_type=j.get("employmentType", ""),
            salary_min=_ashby_salary_min(j.get("compensation")),
            posted_at=j.get("publishedAt", ""),
        ))
    return out


def smartrecruiters(http: Http, token: str, company: str | None = None, max_pages: int = 5) -> list[Posting]:
    """SmartRecruiters public Posting API. List endpoint has no description body;
    we keep the listing fields and let matching work from title/department."""
    out = []
    for page in range(max_pages):  # ponytail: page cap keeps huge boards (Bosch: ~5k) cheap
        data = http.get_json(f"https://api.smartrecruiters.com/v1/companies/{token}/postings"
                             f"?limit=100&offset={page * 100}")
        for j in data.get("content", []):
            loc = j.get("location") or {}
            desc = " / ".join(filter(None, [(j.get("department") or {}).get("label"),
                                            (j.get("function") or {}).get("label"),
                                            (j.get("experienceLevel") or {}).get("label")]))
            out.append(Posting(
                source="smartrecruiters", board=token, external_id=str(j["id"]),
                company=company or (j.get("company") or {}).get("name") or token,
                title=j["name"].strip(),
                location=loc.get("fullLocation", "").replace(", ,", ","),
                remote=bool(loc.get("remote")),
                url=f"https://jobs.smartrecruiters.com/{token}/{j['id']}",
                apply_url=f"https://jobs.smartrecruiters.com/{token}/{j['id']}",
                description=desc,
                employment_type=(j.get("typeOfEmployment") or {}).get("label", ""),
                posted_at=j.get("releasedDate", ""),
            ))
        if (page + 1) * 100 >= data.get("totalFound", 0):
            break
    return out
