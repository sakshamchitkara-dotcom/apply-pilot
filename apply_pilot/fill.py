"""Playwright-assisted form fill that STOPS BEFORE SUBMIT.

The bot fills what it can from the approved packet, highlights the submit
button, and hands control to the human. It never clicks submit, never presses
Enter in a field, and never answers legal/eligibility questions (work
authorization, sponsorship, demographics) - those are left for the human.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

# (packet key, regex matched against the field's label/name/id/placeholder)
FIELD_RULES = [
    ("first_name", r"first[\s_-]*name|given"),
    ("last_name", r"last[\s_-]*name|surname|family"),
    ("name", r"^(full[\s_-]*)?name$|full[\s_-]*name"),
    ("email", r"e-?mail"),
    ("phone", r"phone|mobile|tel"),
    ("github", r"github|portfolio|website|urls?\["),
    ("cover_letter", r"cover[\s_-]*letter"),
    ("why_company", r"why .*(work|join|interested)|why do you want|question_why"),
]
NEVER_ANSWER = re.compile(r"authori[sz]ed|sponsor|visa|citizen|gender|race|ethnic|veteran|disab|pronoun", re.I)
SUBMIT_SELECTOR = "button[type=submit], input[type=submit], button:has-text('Submit')"


def _values(packet: dict) -> dict:
    a = packet["applicant"]
    first, _, last = (a.get("name") or "").partition(" ")
    links = a.get("links") or []
    gh = next((l for l in links if "github" in l), links[0] if links else "")
    return {"first_name": first, "last_name": last, "name": a.get("name", ""), "email": a.get("email", ""),
            "phone": a.get("phone", ""), "github": ("https://" + gh) if gh and not gh.startswith("http") else gh,
            "cover_letter": packet["cover_letter"], "why_company": packet["why_company"]}


def _describe(page, el) -> str:
    """Label text + name + id + placeholder for one form control."""
    return el.evaluate("""e => {
        const lab = (e.id && document.querySelector(`label[for="${e.id}"]`)) || e.closest('label');
        return [lab ? lab.innerText : '', e.name || '', e.id || '', e.placeholder || '',
                e.getAttribute('aria-label') || ''].join(' | ');
    }""")


def fill_page(page, packet: dict, packet_dir: Path | None = None) -> dict:
    vals = _values(packet)
    filled, skipped = [], []
    for el in page.query_selector_all("input, textarea, select"):
        typ = (el.get_attribute("type") or "").lower()
        if typ in ("hidden", "submit", "button", "checkbox", "radio") or not el.is_visible():
            continue
        desc = _describe(page, el)
        if NEVER_ANSWER.search(desc):
            skipped.append(f"{desc.split(' | ')[0].strip()} (left for human: eligibility/legal)")
            continue
        if typ == "file":
            resume = packet_dir / packet["resume_file"] if packet_dir and packet.get("resume_file") else None
            if resume and resume.exists():
                el.set_input_files(str(resume))
                filled.append("resume (file)")
            else:
                skipped.append("resume upload (no file in packet)")
            continue
        for key, pat in FIELD_RULES:
            if re.search(pat, desc, re.I) and vals.get(key):
                el.fill(vals[key])  # fill() never presses Enter, so it cannot submit the form
                filled.append(key)
                break
        else:
            if el.evaluate("e => e.required"):
                skipped.append(f"{desc.split(' | ')[0].strip()} (required, no grounded answer)")
    submit = page.query_selector(SUBMIT_SELECTOR)
    if submit:
        submit.evaluate("b => { b.style.outline = '4px solid red'; b.scrollIntoView(); }")
    return {"filled": filled, "needs_human": skipped, "submit_button_found": bool(submit), "submitted": False}


def fill(url: str, packet_dir: str | Path, headless: bool = False, screenshot: str | None = None,
         wait_for_human: bool = True) -> dict:
    from playwright.sync_api import sync_playwright  # optional extra: apply-pilot[browser]
    packet_dir = Path(packet_dir)
    packet = json.loads((packet_dir / "packet.json").read_text())
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        page = browser.new_page()
        page.goto(url)
        report = fill_page(page, packet, packet_dir)
        if screenshot:
            page.screenshot(path=screenshot, full_page=True)
        print(f"filled: {', '.join(report['filled']) or 'nothing'}")
        for s in report["needs_human"]:
            print(f"needs you: {s}")
        print("STOPPED before submit. Review every field; YOU click the red-outlined submit button.")
        if wait_for_human and not headless:
            # The human owns the browser from here; we just wait for them to close it.
            page.wait_for_event("close", timeout=0)
        browser.close()
    return report
