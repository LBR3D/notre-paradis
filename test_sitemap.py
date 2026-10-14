import gzip
from pathlib import Path

import httpx
import respx

from app.connectors.base import ListingRef
from app.connectors.sitemap import SitemapConnector, parse_sitemap
from app.core.http import PoliteClient
from app.extract.html import extract_listing
from app.services.zone import ZoneIndex

PAGES = Path(__file__).parent / "pages"
ZONE = ZoneIndex([("14514", "Pont-l'Évêque", "14"), ("14366", "Lisieux", "14")])

INDEX = b"""<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<sitemap><loc>https://ex.fr/sm-1.xml.gz</loc></sitemap></sitemapindex>"""
URLSET = b"""<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://ex.fr/annonce-vente-maison-t7-pont-l-eveque-14130-abc/</loc></url>
<url><loc>https://ex.fr/annonce-vente-maison-t4-villers-55220-def/</loc></url>
<url><loc>https://ex.fr/annonce-location-maison-lisieux-14100-ghi/</loc></url>
<url><loc>https://ex.fr/annonce-vente-maison-lisieux-14100-jkl/</loc></url></urlset>"""


def test_parse_sitemap_index_and_urlset():
    assert parse_sitemap(INDEX) == (["https://ex.fr/sm-1.xml.gz"], [])
    subs, pages = parse_sitemap(gzip.compress(URLSET))
    assert subs == [] and len(pages) == 4


def test_extract_orpi_page():
    d = extract_listing((PAGES / "orpi_detail.html").read_text(encoding="utf8"), "https://www.orpi.com/annonce-vente-maison-t7-pont-l-eveque-14130-x/")
    assert d.price == 410000 and d.surface == 142 and d.land == 329 and d.rooms == 7 and d.bedrooms == 5
    assert d.property_type == "maison"
    assert d.photos and len({p.split("?")[0] for p in d.photos}) == len(d.photos)
    assert "maison de maître" in d.description and "consentement" not in d.description.lower()


@respx.mock
def test_discover_filters_zone_and_type(tmp_path):
    respx.get("https://ex.fr/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://ex.fr/sitemap.xml").mock(return_value=httpx.Response(200, content=INDEX))
    respx.get("https://ex.fr/sm-1.xml.gz").mock(return_value=httpx.Response(200, content=gzip.compress(URLSET)))
    client = PoliteClient(min_delay=0, cache_dir=tmp_path)
    c = SitemapConnector({"base_url": "https://ex.fr", "url_regex": r"annonce-vente", "max_listings": 10}, client)
    c.zone = ZONE
    refs = list(c.discover())
    assert [r.url for r in refs] == [
        "https://ex.fr/annonce-vente-maison-t7-pont-l-eveque-14130-abc/",
        "https://ex.fr/annonce-vente-maison-lisieux-14100-jkl/",
    ]
    assert refs[0].hint["commune_code"] == "14514"


@respx.mock
def test_fetch_uses_hint(tmp_path):
    page = (PAGES / "orpi_detail.html").read_text(encoding="utf8")
    url = "https://ex.fr/annonce-vente-maison-t7-pont-l-eveque-14130-abc/"
    respx.get("https://ex.fr/robots.txt").mock(return_value=httpx.Response(404))
    respx.get(url).mock(return_value=httpx.Response(200, text=page))
    client = PoliteClient(min_delay=0, cache_dir=tmp_path)
    c = SitemapConnector({"base_url": "https://ex.fr"}, client)
    c.zone = ZONE
    ref = ListingRef(url=url, hint={"commune_code": "14514", "commune_name": "Pont-l'Évêque", "postal_code": "14130"})
    d = c.fetch(ref)
    assert d.commune_name == "Pont-l'Évêque" and d.postal_code == "14130" and d.price == 410000


@respx.mock
def test_photo_filter_uuid(tmp_path):
    page = (PAGES / "orpi_detail.html").read_text(encoding="utf8")
    url = "https://ex.fr/annonce-vente-maison-t7-pont-l-eveque-14130-d5e5f1c6-7f98-4857-8e88-5443d8fccd18/"
    respx.get("https://ex.fr/robots.txt").mock(return_value=httpx.Response(404))
    respx.get(url).mock(return_value=httpx.Response(200, text=page))
    c = SitemapConnector({"base_url": "https://ex.fr", "photo_filter_uuid": True}, PoliteClient(min_delay=0, cache_dir=tmp_path))
    d = c.fetch(ListingRef(url=url))
    assert d.photos and all("d5e5f1c6-7f98-4857-8e88-5443d8fccd18" in p for p in d.photos)
    assert d.external_id == "d5e5f1c6-7f98-4857-8e88-5443d8fccd18"


def test_catalog_files_are_valid():
    from app.connectors import load_all
    from app.connectors.base import REGISTRY
    from app.connectors.catalog import load_catalog

    load_all()

    cat = load_catalog()
    assert cat and len({e["key"] for e in cat}) == len(cat)
    for e in cat:
        assert e["connector"] in REGISTRY, e["key"]
