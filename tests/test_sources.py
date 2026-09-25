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
