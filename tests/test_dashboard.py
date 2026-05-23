import threading
import urllib.error
import urllib.parse
import urllib.request

from apply_pilot import dashboard, db, tracker


def test_dashboard_lists_and_updates(tmp_path):
    path = tmp_path / "d.db"
    conn = tracker.init(db.connect(path))
    db.upsert(conn, [db.Posting(source="ashby", board="a", external_id="1", company="<Acme>",
                                title="Intern", url="https://x.test")])
    tracker.upsert_score(conn, "ashby:a:1", 60, ["skills 2/3"], "shortlisted")
    conn.commit()
    srv = dashboard.serve(0, path)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"
    page = urllib.request.urlopen(base + "/").read().decode()
    assert "&lt;Acme&gt;" in page and "<Acme>" not in page  # escaped
    post = lambda d: urllib.request.urlopen(base + "/status", urllib.parse.urlencode(d).encode())
    try:
        post({"id": "ashby:a:1", "status": "approved", "token": "wrong"})
        raise AssertionError("expected 403")
    except urllib.error.HTTPError as e:
        assert e.code == 403
    post({"id": "ashby:a:1", "status": "approved", "token": dashboard.TOKEN})
    assert tracker.rows(conn)[0]["status"] == "approved"
    srv.shutdown()
