"""Test helpers: a fake Http that serves recorded fixtures and forbids the network."""
import json
from pathlib import Path

import pytest

from apply_pilot.http import Http

FIX = Path(__file__).parent / "fixtures"


class FixtureHttp(Http):
    def __init__(self, routes, tmp):
        super().__init__(cache_dir=tmp, min_interval=0)
        self.routes = routes

    def _raw_get(self, url):
        for prefix, name in self.routes.items():
            if url.startswith(prefix):
                return (FIX / name).read_text() if not name.startswith("=") else name[1:]
        raise AssertionError(f"unexpected network access in tests: {url}")


@pytest.fixture
def fixture_http(tmp_path):
    return lambda routes: FixtureHttp(routes, tmp_path / "cache")


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("APPLY_PILOT_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def load(name):
    return json.loads((FIX / name).read_text())
