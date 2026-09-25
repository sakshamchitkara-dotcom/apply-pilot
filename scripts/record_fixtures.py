"""Re-record the small test fixtures from live public endpoints.

Keeps a handful of postings per source and truncates descriptions so the
fixtures stay small. Run manually; tests never touch the network.
"""
import json
import re
import sys
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures"
UA = {"User-Agent": "apply-pilot-fixture-recorder"}


def get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read().decode()


def pick(jobs, title_of, n=4):
    """Prefer a couple of intern/new-grad roles plus a couple of regular ones."""
    intern = [j for j in jobs if re.search(r"intern|new grad|university", title_of(j), re.I)]
    rest = [j for j in jobs if j not in intern]
    return (intern[:2] + rest)[:n]


def trim(s, n=1500):
    return s[:n] if isinstance(s, str) else s


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    gh = json.loads(get("https://boards-api.greenhouse.io/v1/boards/stripe/jobs?content=true"))
    jobs = pick(gh["jobs"], lambda j: j["title"])
    for j in jobs:
        j["content"] = trim(j["content"])
    (OUT / "greenhouse_stripe.json").write_text(json.dumps({"jobs": jobs, "meta": {"total": len(jobs)}}, indent=1))

    lv = json.loads(get("https://api.lever.co/v0/postings/palantir?mode=json"))
    jobs = pick(lv, lambda j: j["text"])
    for j in jobs:
        for k in ("description", "descriptionPlain", "descriptionBody", "descriptionBodyPlain", "additional", "additionalPlain"):
            j[k] = trim(j.get(k, ""))
        j["lists"] = j.get("lists", [])[:2]
    (OUT / "lever_palantir.json").write_text(json.dumps(jobs, indent=1))

    ab = json.loads(get("https://api.ashbyhq.com/posting-api/job-board/ramp?includeCompensation=true"))
    jobs = pick(ab["jobs"], lambda j: j["title"])
    for j in jobs:
        j["descriptionHtml"] = trim(j["descriptionHtml"])
        j["descriptionPlain"] = trim(j["descriptionPlain"])
    (OUT / "ashby_ramp.json").write_text(json.dumps({"jobs": jobs, "apiVersion": ab.get("apiVersion")}, indent=1))

    sr = json.loads(get("https://api.smartrecruiters.com/v1/companies/ServiceNow/postings?limit=100"))
    sr["content"] = pick(sr["content"], lambda j: j["name"], 3)
    (OUT / "smartrecruiters_servicenow.json").write_text(json.dumps(sr, indent=1))

    md = get("https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/README.md")
    start = md.index("## 💻 Software Engineering Internship Roles")
    rows = md[start:].split("</tr>")
    # header + first 12 rows, then the closing of the table
    snippet = "</tr>".join(rows[:13]) + "</tr>\n</tbody>\n</table>\n"
    (OUT / "simplify_readme.md").write_text(snippet)
    print("recorded to", OUT, file=sys.stderr)


if __name__ == "__main__":
    main()
