"""apply-pilot command line."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import db, match, resume, sources, tailor, tracker
from .http import Http


def _conn():
    return tracker.init(db.connect())


def _profile(args) -> dict:
    p = Path(args.profile)
    if not p.exists():
        sys.exit(f"no profile at {p}; run: apply-pilot ingest-resume <resume file>")
    return json.loads(p.read_text())


def _companies(args):
    cs = sources.load_companies(args.companies)
    if args.only:
        want = {x.lower() for x in args.only.split(",")}
        cs = [c for c in cs if c["name"].lower() in want or c.get("token", "").lower() in want]
    return cs


def cmd_fetch(args):
    http, conn = Http(), db.connect()
    total_new = total_dup = 0
    jobs = [(c["name"], lambda c=c: sources.fetch_company(http, c)) for c in _companies(args)]
    lists = sources.GITHUB_LISTS if args.lists == "all" else \
        {k: sources.GITHUB_LISTS[k] for k in (args.lists.split(",") if args.lists else [])}
    jobs += [(f"github:{k}", lambda k=k: sources.github_list(http, k)) for k in lists]
    for name, fn in jobs:
        try:
            ps = fn()
        except Exception as e:  # one dead board must not sink the run
            print(f"  ! {name}: {e}", file=sys.stderr)
            continue
        new, dup = db.upsert(conn, ps)
        total_new += new
        total_dup += dup
        print(f"  {name:28} {len(ps):5} postings  (+{new} new, {dup} seen)")
    print(f"fetched: {total_new} new, {total_dup} already known; network requests: {http.network_calls}")


def cmd_verify_companies(args):
    http = Http(ttl=0)
    bad = 0
    for c in _companies(args):
        try:
            n = len(sources.fetch_company(http, c))
            print(f"  ok   {c['ats']:15} {c.get('token', c.get('url')):20} {n} postings")
        except Exception as e:
            bad += 1
            print(f"  DEAD {c['ats']:15} {c.get('token', c.get('url')):20} {e}")
    return 1 if bad else 0


def cmd_ingest_resume(args):
    prof = resume.ingest(args.file)
    Path(args.profile).write_text(json.dumps(prof, indent=2))
    print(f"profile -> {args.profile}: {prof['name']} | {len(prof['skills'])} skills | "
          f"{len(prof['experience'])} roles | {len(prof['facts'])} facts")
    print("skills:", ", ".join(prof["skills"]))


def cmd_shortlist(args):
    """Filter + score every posting that no human has acted on yet."""
    conn, prefs, prof = _conn(), match.load_prefs(args.prefs), _profile(args)
    todo = conn.execute(
        "SELECT p.* FROM postings p LEFT JOIN applications a ON a.posting_id=p.id "
        "WHERE a.status IS NULL OR a.status IN ('found','shortlisted')").fetchall()
    passed = [dict(r) for r in todo if not match.check_filters(dict(r), prefs)]
    # Heuristic ranks everything; the (paid) Claude rubric only re-scores the top candidates.
    scored = sorted(((match.heuristic_score(p, prof, prefs), p) for p in passed), key=lambda t: -t[0][0])
    for i, ((s, why), p) in enumerate(scored):
        if args.claude and i < args.claude_top:
            s, why = match.score(p, prof, prefs, use_claude=True)
        tracker.upsert_score(conn, p["id"], s, why, "shortlisted" if s >= prefs["min_score"] else "found")
    conn.commit()
    n = conn.execute("SELECT count(*) FROM applications WHERE status='shortlisted'").fetchone()[0]
    print(f"{len(todo)} candidates, {len(passed)} pass filters, {n} shortlisted (score >= {prefs['min_score']})")
    _print_rows(tracker.rows(conn, "shortlisted", args.top))


def _print_rows(rows):
    for r in rows:
        print(f"  [{r['score']:3}] {r['status']:12} {r['company'][:22]:22} {r['title'][:55]:55} "
              f"{(r['location'] or '')[:28]:28} {r['posting_id']}")


def cmd_list(args):
    _print_rows(tracker.rows(_conn(), args.status, args.top))


def _posting(conn, pid: str) -> dict:
    r = conn.execute("SELECT * FROM postings WHERE id=?", (pid,)).fetchone()
    if not r:
        sys.exit(f"unknown posting id {pid}")
    return dict(r)


def cmd_tailor(args):
    conn, prof = _conn(), _profile(args)
    ids = args.ids or [r["posting_id"] for r in tracker.rows(conn, "shortlisted", args.top)]
    for pid in ids:
        post = _posting(conn, pid)
        d = tailor.draft(prof, post, use_claude=args.claude)
        out = tailor.write_packet(prof, post, d, args.resume)
        conn.execute("UPDATE applications SET packet_dir=? WHERE posting_id=?", (str(out), pid))
        conn.commit()
        print(f"packet ({d['engine']}, {len(d['flags'])} flagged claims) -> {out}")


def cmd_review(args):
    """The human approval gate: nothing moves to 'approved' except through here."""
    import os
    import subprocess
    conn, prof = _conn(), _profile(args)
    for r in tracker.rows(conn, "shortlisted", args.top):
        post = _posting(conn, r["posting_id"])
        pdir = Path(r["packet_dir"]) if r["packet_dir"] else None
        if not pdir or not pdir.exists():
            d = tailor.draft(prof, post, use_claude=args.claude)
            pdir = tailor.write_packet(prof, post, d, args.resume)
            conn.execute("UPDATE applications SET packet_dir=? WHERE posting_id=?", (str(pdir), post["id"]))
            conn.commit()
        while True:
            pk = json.loads((pdir / "packet.json").read_text())
            print("\n" + "=" * 78)
            print(f"[{r['score']}] {post['title']} @ {post['company']} ({post['location'] or 'n/a'})")
            print(f"apply: {post['apply_url'] or post['url']}")
            for why in json.loads(r["reasons"]):
                print(f"  - {why}")
            print(f"packet: {pdir}\n--- cover letter ---\n{(pdir / 'cover_letter.md').read_text()}")
            if pk["flags"]:
                print("!!! claims not found in your resume (fix before approving):")
                for f in pk["flags"]:
                    print(f"  ! {f}")
            choice = input("[a]pprove  [s]kip  [e]dit  [n]ext  [q]uit > ").strip().lower()[:1]
            if choice == "e":
                subprocess.call([os.environ.get("EDITOR", "vi"), str(pdir / "cover_letter.md")])
                text = (pdir / "cover_letter.md").read_text()
                pk["cover_letter"], pk["flags"] = text, tailor.flag_unsupported(text, prof, post)
                (pdir / "packet.json").write_text(json.dumps(pk, indent=2))
                continue
            if choice == "a":
                tracker.set_status(conn, post["id"], "approved", "approved in review")
                print("approved. Next: apply-pilot apply", post["id"])
            elif choice == "s":
                tracker.set_status(conn, post["id"], "skipped", "skipped in review")
            elif choice == "q":
                return
            break


def cmd_mark(args):
    tracker.set_status(_conn(), args.id, args.status, args.note or "")
    print(f"{args.id} -> {args.status}")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="apply-pilot", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def company_opts(p):
        p.add_argument("--companies", help="JSON company list (default: bundled seed list)")
        p.add_argument("--only", help="comma-separated company names/tokens")

    p = sub.add_parser("fetch", help="fetch postings from company boards and GitHub lists")
    company_opts(p)
    p.add_argument("--lists", help="GitHub lists to include: 'all' or comma list of "
                                   + ",".join(sources.GITHUB_LISTS))
    p.set_defaults(fn=cmd_fetch)

    def profile_opts(p):
        p.add_argument("--profile", default="profile.json")
        p.add_argument("--prefs", default="preferences.toml")

    p = sub.add_parser("ingest-resume", help="parse a PDF/DOCX/MD resume into profile.json")
    p.add_argument("file")
    p.add_argument("--profile", default="profile.json")
    p.set_defaults(fn=cmd_ingest_resume)

    p = sub.add_parser("shortlist", help="filter and score postings against your profile")
    profile_opts(p)
    p.add_argument("--claude", action="store_true", help="re-score the top matches with the Claude rubric")
    p.add_argument("--claude-top", type=int, default=15)
    p.add_argument("--top", type=int, default=20)
    p.set_defaults(fn=cmd_shortlist)

    p = sub.add_parser("list", help="list tracked applications")
    p.add_argument("--status", choices=tracker.STATUSES)
    p.add_argument("--top", type=int, default=50)
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("tailor", help="draft grounded application packets")
    profile_opts(p)
    p.add_argument("ids", nargs="*", help="posting ids (default: top shortlisted)")
    p.add_argument("--top", type=int, default=3)
    p.add_argument("--resume", help="resume file to include in the packet")
    p.add_argument("--no-claude", dest="claude", action="store_false")
    p.set_defaults(fn=cmd_tailor)

    p = sub.add_parser("review", help="approve / skip / edit each shortlisted application")
    profile_opts(p)
    p.add_argument("--top", type=int, default=20)
    p.add_argument("--resume", help="resume file to include in packets")
    p.add_argument("--no-claude", dest="claude", action="store_false")
    p.set_defaults(fn=cmd_review)

    p = sub.add_parser("mark", help="record a status change (e.g. applied, interviewing, offer, rejected)")
    p.add_argument("id")
    p.add_argument("status", choices=tracker.STATUSES)
    p.add_argument("--note")
    p.set_defaults(fn=cmd_mark)

    p = sub.add_parser("verify-companies", help="check every board token is live (bypasses cache)")
    company_opts(p)
    p.set_defaults(fn=cmd_verify_companies)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args) or 0


if __name__ == "__main__":
    sys.exit(main())
