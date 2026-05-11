"""Playwright fill against the local fictional fixture form; asserts nothing is submitted."""
import http.server
import json
import threading
from pathlib import Path

import pytest

playwright = pytest.importorskip("playwright.sync_api")

from apply_pilot import fill, resume, tailor  # noqa: E402

ROOT = Path(__file__).parents[1]


@pytest.fixture
def server():
    posts = []

    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(ROOT / "examples"), **k)

        def do_POST(self):
            posts.append(self.path)
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}", posts
    srv.shutdown()


def test_fill_stops_before_submit(server, tmp_path):
    base, posts = server
    prof = resume.ingest(ROOT / "examples" / "sample_resume.md")
    post = {"id": "x", "company": "Example Corp", "title": "Backend Engineer Intern", "url": base,
            "apply_url": base, "description": "Python PostgreSQL"}
    pdir = tailor.write_packet(prof, post, tailor.draft(prof, post, use_claude=False),
                               str(ROOT / "examples" / "sample_resume.md"), root=tmp_path)
    try:
        report = fill.fill(f"{base}/fixture_form.html", pdir, headless=True, wait_for_human=False)
    except Exception as e:  # browser binary not installed
        pytest.skip(f"chromium unavailable: {e}")
    assert set(report["filled"]) >= {"first_name", "last_name", "email", "phone", "github",
                                     "cover_letter", "why_company", "resume (file)"}
    assert any("authorized" in s for s in report["needs_human"])
    assert report["submit_button_found"] and report["submitted"] is False
    assert posts == []  # the form was never submitted
