"""Thin Claude wrapper. Every caller has a non-LLM fallback, so this returns None on any failure."""
from __future__ import annotations

import json
import os
import sys

MODEL = os.environ.get("APPLY_PILOT_MODEL", "claude-opus-5-5")


def available() -> bool:
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def structured(system: str, user: str, schema: dict, effort: str = "medium", max_tokens: int = 16000) -> dict | None:
    """One Messages call constrained to `schema`. None if unavailable, refused or failed."""
    if not available():
        return None
    import anthropic
    try:
        resp = anthropic.Anthropic().messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            # Opus 5.5: thinking is always adaptive; effort is the only depth control.
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        )
    except anthropic.APIConnectionError as e:
        print(f"claude: connection error, falling back ({e})", file=sys.stderr)
        return None
    except anthropic.RateLimitError:
        print("claude: rate limited, falling back", file=sys.stderr)
        return None
    except anthropic.APIStatusError as e:
        print(f"claude: API error {e.status_code}, falling back", file=sys.stderr)
        return None
    if resp.stop_reason in ("refusal", "max_tokens"):
        print(f"claude: stop_reason={resp.stop_reason}, falling back", file=sys.stderr)
        return None
    text = next((b.text for b in resp.content if b.type == "text"), "")
    try:
        return json.loads(text)
    except ValueError:
        return None
