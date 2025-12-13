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
