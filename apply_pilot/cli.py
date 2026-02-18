"""apply-pilot command line."""
from __future__ import annotations

import argparse
import sys

from . import db, sources
from .http import Http


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

    p = sub.add_parser("verify-companies", help="check every board token is live (bypasses cache)")
    company_opts(p)
    p.set_defaults(fn=cmd_verify_companies)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args) or 0


if __name__ == "__main__":
    sys.exit(main())
