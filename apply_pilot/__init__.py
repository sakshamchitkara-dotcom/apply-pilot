"""apply-pilot: human-in-the-loop job application assistant."""
import os
from pathlib import Path

__version__ = "0.2.0"


def home() -> Path:
    """State directory (db, cache, packets). Override with APPLY_PILOT_HOME."""
    p = Path(os.environ.get("APPLY_PILOT_HOME") or ".apply-pilot")
    p.mkdir(parents=True, exist_ok=True)
    return p
