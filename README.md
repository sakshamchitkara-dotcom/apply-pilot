# apply-pilot

[![CI](https://github.com/sakshamchitkara-dotcom/apply-pilot/actions/workflows/ci.yml/badge.svg)](https://github.com/sakshamchitkara-dotcom/apply-pilot/actions/workflows/ci.yml)

apply-pilot finds job and internship postings, matches them to your resume, drafts tailored applications, and helps you apply. It never submits anything by itself: you approve each application, and you click submit.

```
fetch (public ATS APIs + GitHub lists) -> dedupe (sqlite) -> filter (preferences) -> score (heuristic | Claude rubric)
  -> shortlist -> tailor (grounded packet) -> review (YOU approve/skip/edit) -> apply (pre-fill, YOU submit) -> track
```

## Ground rules (built into the code)

| Rule | How it's enforced |
|---|---|
| Only sources that allow programmatic access | Official public job-board APIs, community GitHub lists, and career pages that pass a robots.txt check (`sources.py`) |
| No LinkedIn / Indeed / Handshake | Not implemented, on purpose. Their terms of service prohibit scraping and automated access, and automated applying there can get your account banned. |
| Polite fetching | Every request goes through `Http.get`: on-disk cache (6h TTL), at least 1s between requests to the same host, robots.txt `Crawl-delay` honoured |
| Nothing is submitted without you | Only `review` can move an application to `approved`. `apply` refuses anything that isn't approved. The browser helper never clicks submit. |
| No made-up experience | Drafts can only select or rephrase facts from your resume. Every draft is checked, and any sentence with a number or skill that isn't in your resume is flagged in `REVIEW.md`. Approval is blocked while `[EDIT ME]` placeholders remain. |
| Eligibility questions stay with you | Form fill skips work authorization, sponsorship, visa, citizenship and demographic fields |
| Unattended runs never apply | `daily` (for cron or Actions) only fetches, shortlists and sends a digest. The digest is a dry run unless you pass `--send`. |

### Submission paths, and why there's no "auto-apply API"

Greenhouse (`POST /v1/boards/{token}/jobs/{id}`), Lever (`POST /v0/postings/{site}/{id}`) and Ashby (`applicationForm.submit`) all have application-submit endpoints. All three need the **employer's** API key, because they exist so companies can build their own career sites. None of them is meant for candidates, so apply-pilot doesn't use them. Instead it offers:

1. **Application packet** (always): `cover_letter.md`, `answers.md`, `REVIEW.md` (flagged claims plus the resume facts used), `packet.json`, and a copy of your resume.
2. **Browser pre-fill** (`apply --browser`): opens a visible Chromium window, fills name, email, phone, links, resume, cover letter and "why us", outlines the submit button in red, then **stops**. You check every field and click submit yourself.

## Sources

| Source | Endpoint | Notes |
|---|---|---|
| Greenhouse | `boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true` | public Job Board API |
| Lever | `api.lever.co/v0/postings/{site}?mode=json` | public Postings API |
| Ashby | `api.ashbyhq.com/posting-api/job-board/{name}?includeCompensation=true` | public job board API, includes salary ranges |
| SmartRecruiters | `api.smartrecruiters.com/v1/companies/{id}/postings` | public Posting API (list view only; capped at 5 pages) |
| GitHub lists | `SimplifyJobs/Summer2027-Internships`, `SimplifyJobs/New-Grad-Positions`, `vanshb03/Summer2027-Internships` | README tables (HTML and pipe). Closed (🔒) rows are dropped; 🛂/🇺🇸/🎓 become flags |
| Career pages | any URL, `{"ats": "careers", "url": ...}` | reads schema.org `JobPosting` JSON-LD, only when robots.txt allows |

Workable is left out: its public widget endpoint isn't documented for third-party use.

The bundled seed list (`apply_pilot/data/companies.json`) has **67 companies**: 33 Greenhouse, 12 Lever, 20 Ashby and 2 SmartRecruiters. All 67 board tokens were checked live on 2026-09-25 with `apply-pilot verify-companies`. You can point `--companies` at your own JSON file.

## Install

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[all]"            # anthropic, pypdf, python-docx, playwright
python -m playwright install chromium   # only needed for `apply --browser`
cp examples/preferences.toml preferences.toml   # edit it
cp .env.example .env                            # optional: ANTHROPIC_API_KEY, digest settings
```

The core only uses the standard library. The extras are optional: `claude`, `pdf`, `docx`, `browser`.

## Usage

```bash
apply-pilot ingest-resume my_resume.pdf            # -> profile.json (PDF, DOCX, MD or TXT)
apply-pilot fetch --lists all                      # all seed companies + GitHub lists
apply-pilot shortlist [--claude --claude-top 15]   # filter + score; Claude re-scores the top N
apply-pilot tailor --top 3 --resume my_resume.pdf  # packets for the top 3 (Claude, or templates without a key)
apply-pilot review --resume my_resume.pdf          # approve / skip / edit, one at a time
apply-pilot apply <posting-id> --browser           # pre-fill in a visible browser; you submit
apply-pilot mark <posting-id> interviewing         # applied -> interviewing -> offer/rejected
apply-pilot remind                                 # follow-ups due (7 days after applied, 3 after interviewing)
apply-pilot export --out applications.csv
apply-pilot dashboard                              # http://127.0.0.1:8765
apply-pilot daily --lists all [--send]             # cron-safe: fetch + shortlist + digest
```

Statuses: `found -> shortlisted -> approved -> applied -> interviewing -> offer | rejected` (plus `skipped`). Illegal jumps, such as `shortlisted -> applied`, raise an error, and re-scoring never overwrites a decision you've made.

State lives in `./.apply-pilot/` (sqlite db, HTTP cache, packets). Set `APPLY_PILOT_HOME` to move it.

### Preferences (`preferences.toml`)

`roles`, `exclude_title_keywords`, `locations`, `remote_ok`, `seniority` (`internship` / `new_grad` / `any`), `needs_sponsorship`, `salary_floor`, `exclude_companies`, `min_score`. See `examples/preferences.toml`.

### Claude (optional)

With `ANTHROPIC_API_KEY` set and `anthropic` installed, the match rubric and drafting use `claude-opus-5-5` (override with `APPLY_PILOT_MODEL`), with structured JSON outputs. The drafting prompt allows only the numbered resume facts. Claude's output still goes through the same unsupported-claim check as the templates. If there's no key, or on any API error, refusal or truncation, apply-pilot falls back to the heuristic scorer and templates.

### Scheduling

- `examples/daily-shortlist.yml`: a GitHub Actions workflow for a private repo holding your profile. It runs fetch, shortlist and digest, and never applies.
- `examples/crontab.txt`: the same thing as a local cron job.

## Development

```bash
pip install -e ".[all,dev]" && python -m playwright install chromium
pytest -q                          # no network: recorded fixtures in tests/fixtures
python scripts/record_fixtures.py  # re-record fixtures from the live public APIs
```

CI runs the suite on Python 3.10 and 3.13, including the Playwright test against `examples/fixture_form.html` (a fictional company). That test asserts the form is never POSTed.

The sample resume (`examples/sample_resume.md`, "Riley Quinn") is a made-up person.

## Observed output (2026-09-25, live)

Fetched 12 real boards plus 2 GitHub lists (cold cache: 18 requests; the same fetch again from cache: 0):

```
  Stripe                         692 postings  (+685 new, 7 seen)
  Figma                          161 postings  (+161 new, 0 seen)
  Databricks                     885 postings  (+868 new, 17 seen)
  Cloudflare                     388 postings  (+373 new, 15 seen)
  Spotify                         81 postings  (+81 new, 0 seen)
  Palantir                       322 postings  (+322 new, 0 seen)
  Zoox                           240 postings  (+240 new, 0 seen)
  Ramp                           155 postings  (+155 new, 0 seen)
  OpenAI                         828 postings  (+825 new, 3 seen)
  Notion                         129 postings  (+129 new, 0 seen)
  Plaid                          122 postings  (+122 new, 0 seen)
  ServiceNow                     500 postings  (+474 new, 26 seen)
  github:simplify-internships   2093 postings  (+1935 new, 158 seen)
  github:vanshb03-internships    214 postings  (+175 new, 39 seen)
fetched: 6545 new, 265 already known; network requests: 18
```

Matched against the fictional sample resume with `examples/preferences.toml` (heuristic scorer, no API key):

```
6545 candidates, 215 pass filters, 214 shortlisted (score >= 55)
  [ 92] shortlisted  Notion    Software Engineer Intern (Winter 2027)       San Francisco, California; N ...
  [ 92] shortlisted  Notion    Software Engineer Intern (Summer 2027)       San Francisco, California; N ...
  [ 90] shortlisted  Palantir  Forward Deployed Software Engineer, Internship - France  New York, NY ...
```

Packet, review gate and browser pre-fill on the local fixture form:

```
packet (template, 0 flagged claims) -> .apply-pilot/packets/notion--software-engineer-intern-winter-2027
[a]pprove  [s]kip  [e]dit  [n]ext  [q]uit > cannot approve: remove the [EDIT ME] placeholders first ([e]dit).
[a]pprove  [s]kip  [e]dit  [n]ext  [q]uit > approved. Next: apply-pilot apply ashby:notion:e66c6658-...
apply at: http://127.0.0.1:8799/fixture_form.html
filled: first_name, last_name, email, phone, github, resume (file), cover_letter, why_company
needs you: Are you legally authorized to work in the US? * (left for human: eligibility/legal)
STOPPED before submit. Review every field; YOU click the red-outlined submit button.
--- fixture server log:
"GET /fixture_form.html HTTP/1.1" 200 -        # no POST: nothing was submitted
```

## Limitations

- The heuristic scorer is keyword-based (`apply_pilot/data/skills.json`). GitHub-list rows have no description, so those scores rely on the title and are damped; a row whose title names no skill scores 52 and stays below the example threshold. `shortlist` prints the score histogram so you can pick `min_score` (or pass `--min-score`).
- SmartRecruiters boards are capped at 5 pages (500 postings) unless you pass `--sr-max-pages 0`. Their full descriptions are fetched per posting, only for postings that pass your filters.
- Résumé parsing is heuristic. Check `profile.json` after ingesting.
- Form pre-fill matches fields by label, name and id. Custom widgets (React selects, multi-step ATS flows) will need manual input, and the helper reports which fields it skipped.

## License

MIT
