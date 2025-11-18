"""Polite HTTP: on-disk cache, per-host rate limiting, optional robots.txt checks.

Every network read in apply-pilot goes through `Http.get`, so caching and
rate limiting cannot be bypassed by a new source.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
import urllib.request
import urllib.robotparser
from pathlib import Path
from urllib.parse import urlsplit

from . import __version__, home

USER_AGENT = f"apply-pilot/{__version__} (+https://github.com/sakshamchitkara-dotcom/apply-pilot)"


class RobotsDisallowed(Exception):
    pass


class Http:
    def __init__(self, cache_dir: Path | None = None, ttl: float = 6 * 3600,
                 min_interval: float = 1.0, timeout: float = 30.0):
        self.cache_dir = Path(cache_dir or home() / "cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.ttl = ttl
        self.min_interval = min_interval
        self.timeout = timeout
        self._last: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser] = {}
        # ponytail: one global lock serialises the wait bookkeeping; per-host locks if we ever fetch concurrently
        self._lock = threading.Lock()
        self.network_calls = 0

    def _cache_path(self, url: str) -> Path:
        return self.cache_dir / (hashlib.sha256(url.encode()).hexdigest()[:32] + ".cache")

    def _throttle(self, host: str, interval: float) -> None:
        with self._lock:
            wait = self._last.get(host, 0) + interval - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last[host] = time.monotonic()

    def _raw_get(self, url: str) -> str:
        host = urlsplit(url).netloc
        interval = self.min_interval
        rp = self._robots.get(f"{urlsplit(url).scheme}://{host}")
        if rp is not None and rp.crawl_delay(USER_AGENT):
            interval = max(interval, float(rp.crawl_delay(USER_AGENT)))
        self._throttle(host, interval)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
        self.network_calls += 1
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return resp.read().decode(resp.headers.get_content_charset() or "utf-8", "replace")

    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        if base not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                rp.parse(self.get(base + "/robots.txt").splitlines())
            except Exception:
                # No readable robots.txt: robotparser semantics are "allow all".
                rp.parse([])
            self._robots[base] = rp
        return self._robots[base].can_fetch(USER_AGENT, url)

    def get(self, url: str, *, respect_robots: bool = False, ttl: float | None = None) -> str:
        if respect_robots and not self.allowed(url):
            raise RobotsDisallowed(url)
        path = self._cache_path(url)
        ttl = self.ttl if ttl is None else ttl
        if path.exists() and time.time() - path.stat().st_mtime < ttl:
            return path.read_text()
        body = self._raw_get(url)
        path.write_text(body)
        return body

    def get_json(self, url: str, **kw):
        return json.loads(self.get(url, **kw))
