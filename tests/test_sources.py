from apply_pilot import sources


def test_greenhouse_normalizes(fixture_http):
    http = fixture_http({"https://boards-api.greenhouse.io/v1/boards/stripe/": "greenhouse_stripe.json"})
    ps = sources.greenhouse(http, "stripe", "Stripe")
    assert len(ps) == 4
    p = ps[0]
    assert p.id.startswith("greenhouse:stripe:")
    assert "Intern" in p.title and p.company == "Stripe"
    assert p.url.startswith("https://") and p.description
    assert "<" not in p.description and "&lt;" not in p.description


def test_lever_normalizes(fixture_http):
    http = fixture_http({"https://api.lever.co/v0/postings/palantir": "lever_palantir.json"})
    ps = sources.lever(http, "palantir", "Palantir")
    assert len(ps) == 4
    intern = ps[0]
    assert intern.employment_type == "Internship"
    assert intern.apply_url.endswith("/apply")
    assert "Paris" in intern.location
    assert len(intern.description) > 100


def test_ashby_normalizes_with_salary(fixture_http):
    http = fixture_http({"https://api.ashbyhq.com/posting-api/job-board/ramp": "ashby_ramp.json"})
    ps = sources.ashby(http, "ramp", "Ramp")
    assert len(ps) == 4
    sec = next(p for p in ps if "Security Engineer" in p.title)
    assert sec.title == "Security Engineer, Cloud"  # whitespace stripped
    assert sec.salary_min == 211400 and sec.remote
    assert "Remote (US)" in sec.location


def test_smartrecruiters_normalizes(fixture_http):
    http = fixture_http({"https://api.smartrecruiters.com/v1/companies/ServiceNow/": "smartrecruiters_servicenow.json"})
    ps = sources.smartrecruiters(http, "ServiceNow")
    assert len(ps) == 3
    assert all(p.url.startswith("https://jobs.smartrecruiters.com/ServiceNow/") for p in ps)
    assert ps[0].company == "ServiceNow" and ", ," not in ps[0].location


def test_simplify_html_table(fixture_http):
    url = "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/README.md"
    http = fixture_http({url: "simplify_readme.md"})
    ps = sources.github_list(http, "simplify-internships")
    assert len(ps) == 12
    assert all(p.company and p.company != "↳" and p.title for p in ps)
    assert all("utm_source" not in p.url for p in ps)
    assert not any("<" in p.location for p in ps)


MD_TABLE = """
| Company | Role | Location | Application/Link | Date Posted |
| ------- | ---- | -------- | ---------------- | ----------- |
| Acme Robotics | Software Intern 🛂 | Remote | <a href="https://job-boards.greenhouse.io/acme/jobs/1?utm_source=x"><img alt="Apply"></a> | Aug 21 |
| ↳ | Data Intern | Austin, TX | <a href="https://job-boards.greenhouse.io/acme/jobs/2"><img alt="Apply"></a> | Aug 21 |
| **[Globex](https://globex.test)** | ML Intern 🔒 | NYC | <a href="https://globex.test/3">Apply</a> | Aug 20 |
"""


def test_markdown_pipe_table_flags_and_continuation(fixture_http):
    http = fixture_http({"https://lists.test/": "=" + MD_TABLE})
    ps = sources.github_list(http, "custom-internships", url="https://lists.test/README.md")
    assert [(p.company, p.title) for p in ps] == [("Acme Robotics", "Software Intern"), ("Acme Robotics", "Data Intern")]
    assert ps[0].flags == ["no_sponsorship"] and ps[0].remote
    assert ps[0].url == "https://job-boards.greenhouse.io/acme/jobs/1"


def test_careers_page_jsonld(fixture_http):
    http = fixture_http({"https://careers.example.test/robots.txt": "=User-agent: *\nAllow: /\n",
                         "https://careers.example.test/": "careers_jsonld.html"})
    ps = sources.careers_page(http, "https://careers.example.test/jobs", "Example Widgets")
    assert [p.title for p in ps] == ["Backend Engineer Intern", "Staff Data Engineer"]
    assert ps[0].external_id == "EW-101" and ps[0].location == "Austin, TX, US"
    assert ps[1].remote and ps[1].salary_min == 180000 and ps[1].employment_type == "FULL_TIME"


def test_careers_page_respects_robots(fixture_http):
    import pytest
    from apply_pilot.http import RobotsDisallowed
    http = fixture_http({"https://careers.example.test/robots.txt": "=User-agent: *\nDisallow: /jobs\n",
                         "https://careers.example.test/": "careers_jsonld.html"})
    with pytest.raises(RobotsDisallowed):
        sources.careers_page(http, "https://careers.example.test/jobs", "Example Widgets")


def test_seed_companies_well_formed():
    cs = sources.load_companies()
    assert len(cs) >= 50
    assert {c["ats"] for c in cs} <= set(sources.FETCHERS) | {"careers"}
    assert len({(c["ats"], c["token"]) for c in cs}) == len(cs)
