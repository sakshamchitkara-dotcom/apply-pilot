# Changelog

## 0.2.0 - 2026-09-25

### Changed
- Heuristic scoring recalibrated: role/seniority/location fit (implied by the hard filters) is capped at 40 points and skill evidence carries 60. A posting with no skill evidence now scores 52, below the example `min_score` of 55. On a live fetch of 16,938 postings, filter-passing postings that got shortlisted went from 235 of 238 to 47.

### Added
- `shortlist` prints a score histogram of filter-passing postings, marking the current cut; `--min-score` overrides preferences for one run (also on `daily`).
- `--sr-max-pages` on `fetch` / `daily` / `verify-companies`: SmartRecruiters page cap (100 postings per page, default 5, `0` = no cap). A capped board reports how many postings were skipped (previously a silent hard-coded limit).
- SmartRecruiters descriptions: `shortlist` fetches full job text from the per-posting endpoint for SmartRecruiters postings that pass the filters (`--details-max`, default 100; `--no-details` stays offline).

## 0.1.0 - 2026-09-25

- Initial release: public ATS + GitHub list sources, polite cached HTTP, filters and heuristic/Claude scoring, grounded tailoring, human approval gate, assisted apply that never submits, tracker, dashboard, digest.
