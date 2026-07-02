"""Daily digest: new shortlisted roles + due follow-ups. Dry-run (print) unless send=True."""
from __future__ import annotations

import json
import os
import smtplib
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from . import tracker


def build(conn, since_hours: int = 24, top: int = 15) -> str:
    since = (datetime.now(timezone.utc) - timedelta(hours=since_hours)).isoformat(timespec="seconds")
    new = [r for r in tracker.rows(conn, "shortlisted", 500) if r["updated_at"] >= since][:top]
    lines = [f"apply-pilot digest - {len(new)} new shortlisted role(s)"]
    lines += [f"[{r['score']}] {r['company']} - {r['title']} ({r['location'] or 'n/a'})\n    {r['url']}" for r in new]
    due = tracker.due_follow_ups(conn)
    if due:
        lines.append(f"\n{len(due)} follow-up(s) due:")
        lines += [f"- {r['company']} - {r['title']} ({r['status']})" for r in due]
    lines.append("\nNothing was applied to. Run `apply-pilot review` to approve or skip.")
    return "\n".join(lines)


def send(text: str) -> list[str]:
    sent = []
    env = os.environ.get
    if env("SMTP_HOST") and env("DIGEST_TO"):
        msg = EmailMessage()
        msg["Subject"], msg["From"], msg["To"] = "apply-pilot digest", env("SMTP_USER") or env("DIGEST_TO"), env("DIGEST_TO")
        msg.set_content(text)
        with smtplib.SMTP(env("SMTP_HOST"), int(env("SMTP_PORT") or 587)) as s:
            s.starttls()
            if env("SMTP_USER"):
                s.login(env("SMTP_USER"), env("SMTP_PASSWORD") or "")
            s.send_message(msg)
        sent.append("email")
    if env("TELEGRAM_BOT_TOKEN") and env("TELEGRAM_CHAT_ID"):
        data = urllib.parse.urlencode({"chat_id": env("TELEGRAM_CHAT_ID"), "text": text[:4000]}).encode()
        urllib.request.urlopen(f"https://api.telegram.org/bot{env('TELEGRAM_BOT_TOKEN')}/sendMessage", data, timeout=30)
        sent.append("telegram")
    return sent
