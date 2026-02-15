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


GITHUB_LISTS = {
    # Community-maintained internship/new-grad lists (public READMEs; raw.githubusercontent.com).
    "simplify-internships": "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/README.md",
    "simplify-newgrad": "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/README.md",
    "vanshb03-internships": "https://raw.githubusercontent.com/vanshb03/Summer2027-Internships/dev/README.md",
}
FLAG_EMOJI = {"🛂": "no_sponsorship", "🇺🇸": "us_citizen_only", "🎓": "advanced_degree", "🔒": "closed"}


def _clean_url(url: str) -> str:
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
    p = urlsplit(html.unescape(url))
    q = [(k, v) for k, v in parse_qsl(p.query) if not k.startswith("utm_") and k != "ref"]
    return urlunsplit(p._replace(query=urlencode(q)))


def _table_rows(md: str):
    """Yield raw cell lists from HTML <tr> rows and markdown pipe rows."""
    for tr in re.findall(r"<tr>(.*?)</tr>", md, re.S):
        cells = re.findall(r"<td>(.*?)</td>", tr, re.S)
        if cells:
            yield cells
    for line in md.splitlines():
        if line.startswith("|") and not re.match(r"^\|\s*-", line):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if cells and cells[0].lower() != "company":
                yield cells


def github_list(http: Http, name: str, url: str | None = None) -> list[Posting]:
    import hashlib
    md = http.get(url or GITHUB_LISTS[name])
    out, company = [], ""
    for cells in _table_rows(md):
        if len(cells) < 4:
            continue
        link = re.search(r'href="([^"]+)"', cells[3]) or re.search(r"\]\((http[^)]+)\)", cells[3])
        text = [strip_html(c.replace("<br>", "; ")) for c in cells]
        # Collapsed multi-location cells look like "<summary>4 locations</summary>A<br>B"
        text[2] = re.sub(r"^\*{0,2}\d+ locations\*{0,2}\s*", "", text[2]).replace("\n", "; ")
        name_cell = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text[0]).strip("* ")
        company = company if name_cell in ("↳", "") else name_cell
        raw = " ".join(text)
        flags = [f for e, f in FLAG_EMOJI.items() if e in raw]
        if "closed" in flags or not link:
            continue
        title = text[1]
        for e in FLAG_EMOJI:
            title = title.replace(e, "")
        apply_url = _clean_url(link.group(1))
        out.append(Posting(
            source="github", board=name, external_id=hashlib.sha1(apply_url.encode()).hexdigest()[:12],
            company=company, title=title.strip(), location=text[2],
            remote=bool(REMOTE_RE.search(text[2])), url=apply_url, apply_url=apply_url,
            employment_type="Internship" if "intern" in name else "",
            posted_at=text[4] if len(text) > 4 else "", flags=flags,
        ))
    return out


def _jsonld_jobs(page: str):
    import json
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', page, re.S | re.I):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            node = stack.pop(0)
            if isinstance(node, dict):
                if node.get("@type") == "JobPosting":
                    yield node
                stack.extend(node.get("@graph", []) if isinstance(node.get("@graph"), list) else [])
            elif isinstance(node, list):
                stack.extend(node)


def careers_page(http: Http, url: str, company: str) -> list[Posting]:
    """Company career page exposing schema.org JobPosting JSON-LD. robots.txt is enforced."""
    import hashlib
    page = http.get(url, respect_robots=True)
    out = []
    for j in _jsonld_jobs(page):
        locs = j.get("jobLocation") or []
        locs = locs if isinstance(locs, list) else [locs]
        where = []
        for l in locs:
            a = (l or {}).get("address") or {}
            where.append(", ".join(filter(None, [a.get("addressLocality"), a.get("addressRegion"), a.get("addressCountry")])))
        job_url = j.get("url") or url
        ident = j.get("identifier")
        ext = str(ident.get("value")) if isinstance(ident, dict) and ident.get("value") else \
            hashlib.sha1(f"{job_url}|{j.get('title')}".encode()).hexdigest()[:12]
        sal = ((j.get("baseSalary") or {}).get("value") or {})
        et = j.get("employmentType", "")
        out.append(Posting(
            source="careers", board=company.lower().replace(" ", "-"), external_id=ext,
            company=(j.get("hiringOrganization") or {}).get("name") or company,
            title=j.get("title", "").strip(), location="; ".join(w for w in where if w),
            remote=j.get("jobLocationType") == "TELECOMMUTE", url=job_url, apply_url=job_url,
            description=strip_html(j.get("description", "")),
            employment_type=", ".join(et) if isinstance(et, list) else et,
            salary_min=sal.get("minValue") if sal.get("unitText", "YEAR") == "YEAR" else None,
            posted_at=j.get("datePosted", ""),
        ))
    return out


FETCHERS = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby, "smartrecruiters": smartrecruiters}


def load_companies(path=None) -> list[dict]:
    """Seed list (board tokens verified live 2026-09-25) or a user-supplied JSON file."""
    import json
    from pathlib import Path
    p = Path(path) if path else Path(__file__).parent / "data" / "companies.json"
    return json.loads(p.read_text())


def fetch_company(http: Http, c: dict) -> list[Posting]:
    if c["ats"] == "careers":
        return careers_page(http, c["url"], c["name"])
    return FETCHERS[c["ats"]](http, c["token"], c["name"])
