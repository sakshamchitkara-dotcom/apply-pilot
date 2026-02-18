from apply_pilot import cli, db, http as http_mod
from conftest import FIX


def fake_raw_get(self, url):
    routes = {"https://boards-api.greenhouse.io/v1/boards/stripe/": "greenhouse_stripe.json",
              "https://api.lever.co/v0/postings/palantir": "lever_palantir.json",
              "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/": "simplify_readme.md"}
    for k, v in routes.items():
        if url.startswith(k):
            return (FIX / v).read_text()
    raise AssertionError(url)


def test_fetch_command_is_idempotent(monkeypatch, capsys):
    monkeypatch.setattr(http_mod.Http, "_raw_get", fake_raw_get)
    args = ["fetch", "--only", "stripe,palantir", "--lists", "simplify-internships"]
    assert cli.main(args) == 0
    n = db.connect().execute("SELECT count(*) FROM postings").fetchone()[0]
    assert n == 4 + 4 + 12
    cli.main(args)
    assert "0 new" in capsys.readouterr().out.splitlines()[-1]
