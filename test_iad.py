from pathlib import Path

import httpx
import respx

from app.connectors.base import ListingRef
from app.connectors.iad import IadConnector, parse_detail, parse_list_page
from app.core.http import PoliteClient
from app.services.zone import ZoneIndex

PAGES = Path(__file__).parent / "pages"
BASE = "https://www.iadfrance.fr"
ZONE = ZoneIndex([("14514", "Pont-l'Évêque", "14"), ("14437", "Mézidon Vallée d'Auge", "14"), ("14366", "Lisieux", "14")])
DETAIL_URL = f"{BASE}/annonce/maison-vente-5-pieces-pont-l-eveque-103m2/r2130950"


def test_parse_detail_real_page():
    d = parse_detail((PAGES / "iad_detail.html").read_text(encoding="utf8"), DETAIL_URL)
    assert d.price == 349000 and d.surface == 103 and d.land == 2370 and d.rooms == 5 and d.bedrooms == 3
    assert d.commune_name == "Pont-l'Évêque" and d.postal_code == "14130"
    assert d.external_id == "2130950"
    assert d.property_type == "maison"
    assert d.dpe == "B" and d.ges == "A" and d.heating == "électrique"
    assert d.title == "Maison 5 pièces de 103 m² à Pont-l'Évêque (14130)"
    # galerie complète (18 photos) et seulement celles de l'annonce (pas la photo d'un bien similaire ni l'avatar du conseiller)
    assert len(d.photos) == 18 and len(set(d.photos)) == 18
    assert all("/property/broadcast/2026/10/07/" in p for p in d.photos)
    assert d.description.startswith("Vous recherchez une maison clé en main")
    assert "pièce d'identité" not in d.description and "Géorisques" not in d.description
    assert d.fees and "vendeur" in d.fees
    assert "Garage" in (d.outbuildings or "")


def test_parse_list_page():
    items = parse_list_page((PAGES / "iad_list.html").read_text(encoding="utf8"), BASE)
    assert len(items) == 30
    first = items[0]
    assert first["url"] == f"{BASE}/annonce/maison-vente-5-pieces-mezidon-vallee-d-auge-153m2/r2131321"
    assert first["place"] == "Mézidon Vallée d'Auge" and first["postcode"] == "14270" and first["price"] == 273000
    assert len({i["url"] for i in items}) == 30


@respx.mock
def test_discover_paginates_and_filters_zone(tmp_path):
    listing = (PAGES / "iad_list.html").read_text(encoding="utf8")
    respx.get(f"{BASE}/robots.txt").mock(return_value=httpx.Response(200, text="User-agent: *\nDisallow: /account/\nDisallow: /liste/annonces*\n"))
    p2 = respx.get(f"{BASE}/annonces/calvados-14/vente/maison", params={"page": "2"}).mock(return_value=httpx.Response(200, text="<html><body>aucune annonce</body></html>"))
    p1 = respx.get(f"{BASE}/annonces/calvados-14/vente/maison").mock(return_value=httpx.Response(200, text=listing))
    client = PoliteClient(min_delay=0, cache_dir=tmp_path)
    c = IadConnector({"departements": ["calvados-14"], "max_listings": 50}, client)
    c.zone = ZONE
    refs = list(c.discover())
    assert p1.called and p2.called  # s'arrête à la première page sans annonce
    assert [r.url for r in refs] == [
        f"{BASE}/annonce/maison-vente-5-pieces-mezidon-vallee-d-auge-153m2/r2131321",
        f"{BASE}/annonce/maison-vente-5-pieces-pont-l-eveque-103m2/r2130950",
        f"{BASE}/annonce/maison-vente-6-pieces-pont-l-eveque-152m2/r2106718",
    ]
    assert refs[0].hint["commune_code"] == "14437" and refs[0].hint["postal_code"] == "14270"
    assert refs[0].external_id == "2131321"


@respx.mock
def test_discover_respects_limit_and_no_zone_filter(tmp_path):
    listing = (PAGES / "iad_list.html").read_text(encoding="utf8")
    respx.get(f"{BASE}/robots.txt").mock(return_value=httpx.Response(404))
    respx.get(f"{BASE}/annonces/calvados-14/vente/maison").mock(return_value=httpx.Response(200, text=listing))
    c = IadConnector({"departements": ["calvados-14"], "zone_filter": False, "max_listings": 5}, PoliteClient(min_delay=0, cache_dir=tmp_path))
    assert len(list(c.discover())) == 5


@respx.mock
def test_fetch_detail(tmp_path):
    page = (PAGES / "iad_detail.html").read_text(encoding="utf8")
    respx.get(f"{BASE}/robots.txt").mock(return_value=httpx.Response(404))
    respx.get(DETAIL_URL).mock(return_value=httpx.Response(200, text=page))
    respx.get(f"{BASE}/annonce/disparue/r1").mock(return_value=httpx.Response(404))
    c = IadConnector({}, PoliteClient(min_delay=0, cache_dir=tmp_path))
    d = c.fetch(ListingRef(url=DETAIL_URL, external_id="2130950", hint={"commune_code": "14514", "commune_name": "Pont-l'Évêque", "postal_code": "14130"}))
    assert d.price == 349000 and d.extra["commune_code"] == "14514"
    assert c.fetch(ListingRef(url=f"{BASE}/annonce/disparue/r1")) is None


@respx.mock
def test_robots_disallow_stops_source(tmp_path):
    import pytest

    from app.core.http import RobotsDisallowed

    respx.get(f"{BASE}/robots.txt").mock(return_value=httpx.Response(200, text="User-agent: *\nDisallow: /annonces/\n"))
    c = IadConnector({"departements": ["calvados-14"]}, PoliteClient(min_delay=0, cache_dir=tmp_path))
    with pytest.raises(RobotsDisallowed):
        list(c.discover())


def test_source_file():
    import json

    d = json.loads((Path(__file__).parent.parent / "app/connectors/sources/iad.json").read_text(encoding="utf8"))
    assert d["key"] == "iad" and d["connector"] == "iad" and d["enabled"] is True


@respx.mock
def test_discover_stops_when_page_repeats(tmp_path):
    listing = (PAGES / "iad_list.html").read_text(encoding="utf8")
    respx.get(f"{BASE}/robots.txt").mock(return_value=httpx.Response(404))
    route = respx.get(f"{BASE}/annonces/calvados-14/vente/maison").mock(return_value=httpx.Response(200, text=listing))
    c = IadConnector({"departements": ["calvados-14"], "zone_filter": False, "max_pages": 40}, PoliteClient(min_delay=0, cache_dir=tmp_path))
    assert len(list(c.discover())) == 30
    assert route.call_count == 2  # page 1, puis page 2 identique -> arrêt
