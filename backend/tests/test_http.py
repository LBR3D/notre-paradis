import time

import httpx
import pytest

from app.core.http import PoliteClient, RobotsDisallowed

ROBOTS = "User-agent: *\nDisallow: /prive/\n"


def _client(tmp_path, handler, delay=0.3):
    return PoliteClient(min_delay=delay, cache_ttl_hours=1, cache_dir=tmp_path, transport=httpx.MockTransport(handler))


def test_robots_and_cache(tmp_path):
    calls = []

    def handler(req: httpx.Request):
        calls.append(req.url.path)
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS)
        return httpx.Response(200, text=f"page {req.url.path}")

    c = _client(tmp_path, handler)
    assert c.get("https://agence.example/annonces").text == "page /annonces"
    assert c.get("https://agence.example/annonces").from_cache
    with pytest.raises(RobotsDisallowed):
        c.get("https://agence.example/prive/x")
    assert calls.count("/annonces") == 1
    assert "User-Agent" in c._client.headers and "NotreParadisBot" in c._client.headers["User-Agent"]


def test_throttle(tmp_path):
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text="ok")

    c = _client(tmp_path, handler, delay=0.4)
    t0 = time.time()
    for i in range(3):
        c.get(f"https://agence.example/p{i}", use_cache=False)
    assert time.time() - t0 >= 0.8


def test_forbidden_robots_blocks_everything(tmp_path):
    def handler(req):
        return httpx.Response(403)

    c = _client(tmp_path, handler)
    assert not c.allowed("https://portail.example/annonces")
