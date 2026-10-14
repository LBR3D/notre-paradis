import json
from pathlib import Path

import httpx
import respx

from app.connectors.base import ListingRef
from app.connectors.nestenn import NestennConnector, parse_detail, parse_list_page
from app.core.http import PoliteClient
from app.services.zone import ZoneIndex

PAGES = Path(__file__).parent / "pages"
BASE = "https://nestenn.com"
ZONE = ZoneIndex([("27411", "Mesnil-en-Ouche", "27"), ("27659", "Tilly", "27"), ("27151", "Étrépagny", "27")])
DETAIL_URL = f"{BASE}/longere-normande-renovee-de-166m-proche-bernay-ref-39563416"


def test_parse_detail_real_page():
    d = parse_detail((PAGES / "nestenn_detail.html").read_text(encoding="utf8"), DETAIL_URL)
    assert d.price == 269700 and d.surface == 166 and d.rooms == 6 and d.bedrooms == 4
    assert d.land == 4792 and d.extra["terrain_fourchette"] == [4335, 4792]
    assert d.postal_code == "27410" and d.extra["commune_site"] == "MESNIL EN OUCHE"
    assert d.title == "Longère Normande rénovée de 166m² -proche Bernay"
    assert d.property_type == "longère"
    assert d.dpe == "C" and d.ges == "A" and d.year_built == 1900
    assert d.external_id == "39563416"
    assert d.lat and d.lon
    # seulement les photos de l'annonce (la page montre aussi d'autres biens)
    assert len(d.photos) == 10 and all("39563416" in p for p in d.photos)
    assert "Géorisques" not in d.description and d.description.startswith("Découvrez cette charmante maison ancienne")
    assert d.contact.get("agence", "").startswith("Agence Nestenn")


def test_parse_list_page_extract():
    items = parse_list_page((PAGES / "nestenn_list.html").read_text(encoding="utf8"), BASE)
    assert len(items) == 8
    first = items[0]
    assert first["url"] == f"{BASE}/maison-panilleuse-5-piece-s-92-m2-ref-39737452"
    assert first["postcode"] == "27510" and first["place"] == "PANILLEUSE" and first["price"] == 212000 and first["ref"] == "39737452"
    assert any(i["sold"] for i in items) and not first["sold"]
    assert all(i["postcode"] for i in items)


@respx.mock
def test_discover_filters_zone_and_skips_sold(tmp_path):
    listing = (PAGES / "nestenn_list.html").read_text(encoding="utf8")
    respx.get(f"{BASE}/robots.txt").mock(return_value=httpx.Response(200, text="User-agent: *\nAllow: /\nDisallow: /listing*$\nDisallow: /impressionbien-*$\n"))
    respx.get(f"{BASE}/vente/maison/eure-27").mock(return_value=httpx.Response(200, text=listing))
    c = NestennConnector({"departements": ["eure-27"]}, PoliteClient(min_delay=0, cache_dir=tmp_path))
    c.zone = ZONE
    refs = list(c.discover())
    urls = [r.url for r in refs]
    assert [u[-9:] for u in urls] == ["-39563416", "-39364369"]  # Mesnil-en-Ouche, Étrépagny
    # Tilly (vendu) ne doit jamais ressortir ; Gisors / Vernon sont hors zone
    assert not any(u.endswith("ref-39007567") for u in urls)
    assert not any("gisors" in u for u in urls)
    for r in refs:
        assert r.hint["commune_code"] in {"27411", "27659", "27151"} and r.external_id


@respx.mock
def test_discover_no_zone_filter_keeps_unsold(tmp_path):
    listing = (PAGES / "nestenn_list.html").read_text(encoding="utf8")
    respx.get(f"{BASE}/robots.txt").mock(return_value=httpx.Response(404))
    respx.get(f"{BASE}/vente/maison/eure-27").mock(return_value=httpx.Response(200, text=listing))
    c = NestennConnector({"departements": ["eure-27"], "zone_filter": False}, PoliteClient(min_delay=0, cache_dir=tmp_path))
    items = parse_list_page(listing, BASE)
    assert len(list(c.discover())) == len([i for i in items if not i["sold"]])


@respx.mock
def test_fetch_uses_hint(tmp_path):
    page = (PAGES / "nestenn_detail.html").read_text(encoding="utf8")
    respx.get(f"{BASE}/robots.txt").mock(return_value=httpx.Response(404))
    respx.get(DETAIL_URL).mock(return_value=httpx.Response(200, text=page))
    c = NestennConnector({}, PoliteClient(min_delay=0, cache_dir=tmp_path))
    d = c.fetch(ListingRef(url=DETAIL_URL, external_id="39563416", hint={"commune_code": "27411", "commune_name": "Mesnil-en-Ouche", "postal_code": "27410"}))
    assert d.commune_name == "Mesnil-en-Ouche" and d.postal_code == "27410" and d.extra["commune_code"] == "27411"
    assert d.price == 269700


def test_source_file():
    d = json.loads((Path(__file__).parent.parent / "app/connectors/sources/nestenn.json").read_text(encoding="utf8"))
    assert d["key"] == "nestenn" and d["connector"] == "nestenn" and d["enabled"] is True
