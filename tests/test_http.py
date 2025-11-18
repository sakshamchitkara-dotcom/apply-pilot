import time

from apply_pilot.http import Http, RobotsDisallowed


class CountingHttp(Http):
    def __init__(self, pages, **kw):
        super().__init__(**kw)
        self.pages = pages
        self.hits = []

    def _raw_get(self, url):
        self.hits.append(url)
        if url not in self.pages:
            raise OSError("404")
        return self.pages[url]


def test_cache_serves_second_read(tmp_path):
    h = CountingHttp({"https://x.test/a": "hello"}, cache_dir=tmp_path, min_interval=0)
    assert h.get("https://x.test/a") == "hello"
    assert h.get("https://x.test/a") == "hello"
    assert h.hits == ["https://x.test/a"]


def test_ttl_zero_refetches(tmp_path):
    h = CountingHttp({"https://x.test/a": "hello"}, cache_dir=tmp_path, min_interval=0)
    h.get("https://x.test/a")
    h.get("https://x.test/a", ttl=0)
    assert len(h.hits) == 2


def test_rate_limit_spaces_same_host(tmp_path):
    h = Http(cache_dir=tmp_path, min_interval=0.2)
    t0 = time.monotonic()
    h._throttle("x.test", 0.2)
    h._throttle("x.test", 0.2)
    assert time.monotonic() - t0 >= 0.19


def test_robots_disallow_blocks(tmp_path):
    pages = {"https://c.test/robots.txt": "User-agent: *\nDisallow: /private/\n",
             "https://c.test/jobs": "ok"}
    h = CountingHttp(pages, cache_dir=tmp_path, min_interval=0)
    assert h.get("https://c.test/jobs", respect_robots=True) == "ok"
    try:
        h.get("https://c.test/private/x", respect_robots=True)
        raise AssertionError("expected RobotsDisallowed")
    except RobotsDisallowed:
        pass


def test_missing_robots_allows(tmp_path):
    h = CountingHttp({"https://d.test/jobs": "ok"}, cache_dir=tmp_path, min_interval=0)
    assert h.get("https://d.test/jobs", respect_robots=True) == "ok"
