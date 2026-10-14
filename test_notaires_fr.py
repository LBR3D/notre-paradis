import httpx
import pytest
import respx

from app.connectors.catalog import load_catalog
from app.core.http import PoliteClient, RobotsDisallowed

INCAPSULA = '<html><head><META NAME="ROBOTS" CONTENT="NOINDEX, NOFOLLOW"></head><body><iframe src="/_Incapsula_Resource?CWUDNSAI=23"></iframe></body></html>'


def test_notaires_fr_source_is_disabled_with_reason():
    entry = next(e for e in load_catalog() if e["key"] == "notaires_fr")
    assert entry["enabled"] is False
    assert "403" in entry["note"] and "robots.txt" in entry["note"]


@respx.mock
def test_robots_403_means_no_request_to_the_site(tmp_path):
    robots = respx.get("https://www.notaires.fr/robots.txt").mock(return_value=httpx.Response(403, text=INCAPSULA))
    page = respx.get("https://www.notaires.fr/fr/immobilier-fixe/annonce").mock(return_value=httpx.Response(200, text="x"))
    client = PoliteClient(min_delay=0, cache_dir=tmp_path)
    assert client.allowed("https://www.notaires.fr/") is False
    with pytest.raises(RobotsDisallowed):
        client.get("https://www.notaires.fr/fr/immobilier-fixe/annonce")
    assert robots.called and not page.called
