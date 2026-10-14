from pathlib import Path

import httpx
import pytest
import respx

from app.connectors.base import ListingRef
from app.connectors.guyhoquet import GuyHoquetConnector, detail_links
from app.core.http import PoliteClient, RobotsDisallowed
from app.services.zone import ZoneIndex

PAGES = Path(__file__).parent / "pages"
BASE = "https://www.guy-hoquet.com"
URL = f"{BASE}/achat-vente/maison-5-pieces-touques-14800-1896690"
ZONE = ZoneIndex([("14742", "Touques", "14"), ("14220", "Deauville", "14")])
CFG = {
    "base_url": BASE,
    "sitemaps": [f"{BASE}/sitemap-index"],
    "sitemap_regex": r"/sitemap/sitemap-\d+$",
    "max_pages": 3,
}
INDEX = f"""<?xml version="1.0"?><sitemapindex xmlns="https://www.sitemaps.org/schemas/sitemap/0.9">
<sitemap><loc>{BASE}/sitemap/sitemap</loc></sitemap><sitemap><loc>{BASE}/sitemap/sitemap-requetes-metiers-1</loc></sitemap>
<sitemap><loc>{BASE}/sitemap/sitemap-1</loc></sitemap></sitemapindex>""".encode()
SM1 = f"""<?xml version="1.0"?><urlset xmlns="https://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>{BASE}/achat-vente/annonces-agen-47000</loc></url>
<url><loc>{BASE}/achat-vente/annonces-deauville-14800</loc></url>
<url><loc>{BASE}/location-meublee/annonces-deauville-14800</loc></url></urlset>""".encode()


def _card(slug: str) -> str:
    return f'<a class="x" href="{BASE}/achat-vente/{slug}">voir</a>'


LIST1 = "<html>" + "".join(_card(s) for s in [
    "appartement-2-pieces-deauville-14800-1894461",
    "maison-4-pieces-deauville-14800-1743368",
    "maison-5-pieces-touques-14800-1896690",
    "maison-3-pieces-agen-47000-1111111",
]) + f'<a rel="next" href="{BASE}/achat-vente/annonces-deauville-14800?page=2">2</a></html>'
LIST2 = "<html>" + "".join(_card(s) for s in [
    "maison-4-pieces-deauville-14800-1743368",  # doublon
    "propriete-9-pieces-touques-14800-1800000",
    "terrain-canapville-14800-1559336",
]) + "</html>"


def _conn(tmp_path):
    c = GuyHoquetConnector(dict(CFG), PoliteClient(min_delay=0, cache_dir=tmp_path))
    c.zone = ZONE
    return c


def test_detail_links():
    assert detail_links(LIST1) == [
        "/achat-vente/appartement-2-pieces-deauville-14800-1894461",
        "/achat-vente/maison-4-pieces-deauville-14800-1743368",
        "/achat-vente/maison-5-pieces-touques-14800-1896690",
        "/achat-vente/maison-3-pieces-agen-47000-1111111",
    ]


@respx.mock
def test_discover_respects_robots(tmp_path):
    respx.get(f"{BASE}/robots.txt").mock(return_value=httpx.Response(200, text="User-agent: *\nDisallow: /achat-vente/\n"))
    respx.get(f"{BASE}/sitemap-index").mock(return_value=httpx.Response(200, content=INDEX))
    respx.get(f"{BASE}/sitemap/sitemap-1").mock(return_value=httpx.Response(200, content=SM1))
    page = respx.get(f"{BASE}/achat-vente/annonces-deauville-14800").mock(return_value=httpx.Response(200, text=LIST1))
    with pytest.raises(RobotsDisallowed):
        list(_conn(tmp_path).discover())
    assert not page.called


@respx.mock
def test_discover_follows_page_2(tmp_path):
    respx.get(f"{BASE}/robots.txt").mock(return_value=httpx.Response(404))
    respx.get(f"{BASE}/sitemap-index").mock(return_value=httpx.Response(200, content=INDEX))
    respx.get(f"{BASE}/sitemap/sitemap-1").mock(return_value=httpx.Response(200, content=SM1))

    def page(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=LIST2 if request.url.params.get("page") == "2" else LIST1)

    respx.get(f"{BASE}/achat-vente/annonces-deauville-14800").mock(side_effect=page)
    refs = list(_conn(tmp_path).discover())
    assert [r.external_id for r in refs] == ["1743368", "1896690", "1800000"]  # ni appartement, ni Agen, ni terrain, sans doublon
    assert refs[1].hint["commune_name"] == "Touques" and refs[1].hint["postal_code"] == "14800"
    assert refs[0].url == f"{BASE}/achat-vente/maison-4-pieces-deauville-14800-1743368"


@respx.mock
def test_fetch_real_page(tmp_path):
    respx.get(f"{BASE}/robots.txt").mock(return_value=httpx.Response(404))
    respx.get(URL).mock(return_value=httpx.Response(200, text=(PAGES / "guyhoquet_detail.html").read_text(encoding="utf8")))
    d = _conn(tmp_path).fetch(ListingRef(url=URL, external_id="1896690", hint={"commune_code": "14742", "commune_name": "Touques", "postal_code": "14800"}))
    assert d.price == 595000 and d.surface == 136.22 and d.land == 4142 and d.rooms == 5 and d.bedrooms == 4
    assert d.commune_name == "Touques" and d.postal_code == "14800" and d.extra["commune_code"] == "14742"
    assert d.dpe == "B" and d.ges == "A" and d.sewage == "Tout à l'égout" and d.condition == "Excellent"
    assert d.heating == "Individuel - Climatisation réversible" and d.year_built is None
    assert len(d.photos) == 18 and all("7749463" in p for p in d.photos)
    assert d.description.startswith("À quelques minutes de Deauville") and "Voir plus" not in d.description
    assert d.description.count("À quelques minutes de Deauville") == 1
    assert "565000" in d.fees and d.contact["agence"] == "Guy Hoquet DEAUVILLE"
    assert d.lat and d.lon
