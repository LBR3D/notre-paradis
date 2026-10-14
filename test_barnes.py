from pathlib import Path

import httpx
import respx

from app.connectors.barnes import BarnesConnector
from app.connectors.base import ListingRef
from app.core.http import PoliteClient
from app.services.zone import ZoneIndex

PAGES = Path(__file__).parent / "pages"
BASE = "https://www.barnes-international.com"
ZONE = ZoneIndex([("14711", "Touques", "14"), ("14514", "Pont-l'Évêque", "14"), ("14333", "Honfleur", "14")])
ROBOTS = "User-agent: *\nAllow: /\nDisallow: /*search*\nDisallow: /*?search\nDisallow: /*/map.html*\nDisallow: /*modals*\n"


def fiche(commune: str, n: int) -> str:
    return f'<a href="{BASE}/fr/vente/france/{commune}/ref-APM-{n}.html">fiche</a>'


PAGE1 = (
    fiche("touques", 111)
    + fiche("touques", 111)  # doublon dans la page
    + fiche("caen", 222)  # hors zone
    + fiche("pont-leveque", 333)  # « Pont-l'Évêque » sans apostrophe
    + f'<a href="{BASE}/fr/vente/france/calvados.html?search&x=1">recherche</a>'
    + '<a href="/fr/vente/france/calvados.html?page=2" rel="next">Annonces suivantes</a>'
)
PAGE2 = fiche("honfleur", 444) + fiche("paris-8eme", 555)


def make_client(tmp_path):
    return PoliteClient(min_delay=0, cache_dir=tmp_path)


def test_extract_detail_page():
    from app.extract.html import extract_listing

    d = extract_listing((PAGES / "barnes_detail.html").read_text(encoding="utf8"), f"{BASE}/fr/vente/france/touques/ref-APM-7659851.html")
    assert d.price == 1113000 and d.surface == 140 and d.land == 2705
    assert d.rooms == 7 and d.bedrooms == 4 and d.year_built == 1985
    assert d.property_type == "propriété" and d.dpe == "E" and d.ges == "B"
    assert len(d.photos) >= 10


@respx.mock
def test_discover_follows_pagination_and_filters_zone(tmp_path):
    respx.get(f"{BASE}/robots.txt").mock(return_value=httpx.Response(200, text=ROBOTS))

    def listing(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=PAGE2 if request.url.params.get("page") == "2" else PAGE1)

    route = respx.get(url__regex=r"https://www\.barnes-international\.com/fr/vente/france/calvados\.html.*").mock(side_effect=listing)
    cfg = {"listing_pages": [{"url": f"{BASE}/fr/vente/france/calvados.html", "dep": "14"}], "max_pages": 5}
    c = BarnesConnector(cfg, make_client(tmp_path))
    c.zone = ZONE
    refs = list(c.discover())
    assert [r.external_id for r in refs] == ["APM-111", "APM-333", "APM-444"]
    assert refs[1].hint["commune_name"] == "Pont-l'Évêque" and refs[1].hint["commune_code"] == "14514"
    # deux pages de vitrine seulement ; jamais d'adresse contenant « search »
    urls = [str(call.request.url) for call in route.calls]
    assert len(urls) == 2 and not any("search" in u for u in urls)


@respx.mock
def test_discover_respects_max_pages_and_zone_off(tmp_path):
    respx.get(f"{BASE}/robots.txt").mock(return_value=httpx.Response(404))
    respx.get(url__regex=r".*calvados\.html.*").mock(return_value=httpx.Response(200, text=PAGE1))  # « suivante » renvoie la même page
    cfg = {"listing_pages": [{"url": f"{BASE}/fr/vente/france/calvados.html", "dep": "14"}], "max_pages": 3, "zone_filter": False}
    c = BarnesConnector(cfg, make_client(tmp_path))
    c.zone = ZONE
    refs = list(c.discover())
    assert [r.external_id for r in refs] == ["APM-111", "APM-222", "APM-333"]


@respx.mock
def test_fetch_keeps_only_property_photos(tmp_path):
    url = f"{BASE}/fr/vente/france/touques/ref-APM-7659851.html"
    page = (PAGES / "barnes_detail.html").read_text(encoding="utf8")
    respx.get(f"{BASE}/robots.txt").mock(return_value=httpx.Response(404))
    respx.get(url).mock(return_value=httpx.Response(200, text=page))
    c = BarnesConnector({}, make_client(tmp_path))
    ref = ListingRef(url=url, external_id="APM-7659851", hint={"commune_code": "14711", "commune_name": "Touques"})
    d = c.fetch(ref)
    assert d.external_id == "APM-7659851" and d.commune_name == "Touques" and d.extra["commune_code"] == "14711"
    assert d.price == 1113000 and d.land == 2705
    assert d.photos and all("/bdata/property/" in p for p in d.photos) and not any("collaborator" in p for p in d.photos)


@respx.mock
def test_fetch_404_returns_none(tmp_path):
    url = f"{BASE}/fr/vente/france/touques/ref-APM-1.html"
    respx.get(f"{BASE}/robots.txt").mock(return_value=httpx.Response(404))
    respx.get(url).mock(return_value=httpx.Response(404))
    assert BarnesConnector({}, make_client(tmp_path)).fetch(ListingRef(url=url)) is None
