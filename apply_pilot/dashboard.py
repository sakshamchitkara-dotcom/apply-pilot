"""Tiny stdlib web dashboard for the tracker (localhost only)."""
from __future__ import annotations

import html
import http.server
import json
import secrets
from urllib.parse import parse_qs, urlsplit

from . import db, tracker

TOKEN = secrets.token_urlsafe(16)  # per-process form token: other sites can't POST status changes

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>apply-pilot</title>
<style>body{{font-family:system-ui;margin:1.5rem}}table{{border-collapse:collapse;width:100%}}
td,th{{border-bottom:1px solid #ddd;padding:.35rem;text-align:left;font-size:14px;vertical-align:top}}
.s{{font-weight:600}}nav a{{margin-right:.8rem}}small{{color:#666}}</style></head><body>
<h1>apply-pilot</h1><nav>{nav}</nav><p><small>{counts}</small></p>
<table><tr><th>Score</th><th>Status</th><th>Company</th><th>Role</th><th>Location</th><th>Follow-up</th><th>Move to</th></tr>
{rows}</table></body></html>"""


def render(conn, status: str | None) -> str:
    counts = dict(conn.execute("SELECT status, count(*) FROM applications GROUP BY status").fetchall())
    nav = '<a href="/">all</a>' + "".join(f'<a href="/?status={s}">{s} ({counts.get(s, 0)})</a>'
                                           for s in tracker.STATUSES)
    out = []
    for r in tracker.rows(conn, status, 500):
        e = lambda v: html.escape(str(v or ""))
        why = "; ".join(json.loads(r["reasons"]))
        opts = "".join(f"<option>{s}</option>" for s in sorted(tracker.TRANSITIONS[r["status"]]))
        form = (f'<form method="post" action="/status"><input type="hidden" name="token" value="{TOKEN}">'
                f'<input type="hidden" name="id" value="{e(r["posting_id"])}"><select name="status">{opts}</select>'
                f'<button>set</button></form>') if opts else ""
        out.append(f'<tr><td title="{e(why)}">{r["score"]}</td><td class="s">{e(r["status"])}</td>'
                   f'<td>{e(r["company"])}</td><td><a href="{e(r["url"])}" rel="noopener" target="_blank">'
                   f'{e(r["title"])}</a></td><td>{e(r["location"])}</td><td>{e(r["follow_up_at"][:10])}</td>'
                   f"<td>{form}</td></tr>")
    return PAGE.format(nav=nav, counts=html.escape(json.dumps(counts)), rows="\n".join(out))


class Handler(http.server.BaseHTTPRequestHandler):
    db_path = None

    def _conn(self):
        return tracker.init(db.connect(self.db_path))

    def _send(self, code: int, body: str, ctype="text/html; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(body.encode())

    def do_GET(self):
        q = parse_qs(urlsplit(self.path).query)
        status = q.get("status", [None])[0]
        self._send(200, render(self._conn(), status if status in tracker.STATUSES else None))

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        form = {k: v[0] for k, v in parse_qs(self.rfile.read(n).decode()).items()}
        if form.get("token") != TOKEN:
            return self._send(403, "bad token")
        try:
            tracker.set_status(self._conn(), form["id"], form["status"], "via dashboard")
        except (tracker.BadTransition, KeyError) as e:
            return self._send(400, html.escape(str(e)))
        self.send_response(303)
        self.send_header("Location", "/")
        self.end_headers()

    def log_message(self, *a):
        pass


def serve(port: int = 8765, db_path=None) -> http.server.ThreadingHTTPServer:
    Handler.db_path = db_path
    return http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
