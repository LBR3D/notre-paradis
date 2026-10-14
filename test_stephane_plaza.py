import json
from pathlib import Path

import httpx
import pytest
import respx

from app.connectors.sitemap import SitemapConnector
from app.core.http import PoliteClient, RobotsDisallowed

BASE = "https://www.stephaneplazaimmobilier.com"


def test_source_is_disabled_with_reason():
    d = json.loads((Path(__file__).parent.parent / "app/connectors/sources/stephane-plaza.json").read_text(encoding="utf8"))
    assert d["key"] == "stephane-plaza" and d["enabled"] is False
    assert "403" in d["note"] and "Cloudflare" in d["note"]


@respx.mock
def test_robots_403_means_no_access(tmp_path):
    """Un 403 sur robots.txt = on s'abstient : aucune page du site n'est demandée."""
    respx.get(f"{BASE}/robots.txt").mock(return_value=httpx.Response(403, text="Access Denied"))
    page = respx.get(f"{BASE}/sitemap.xml").mock(return_value=httpx.Response(200, text="<urlset/>"))
    client = PoliteClient(min_delay=0, cache_dir=tmp_path)
    assert client.allowed(f"{BASE}/") is False
    c = SitemapConnector({"base_url": BASE}, client)
    with pytest.raises(RobotsDisallowed):
        list(c.discover())
    assert not page.called
