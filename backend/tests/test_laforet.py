from pathlib import Path

import httpx
import respx

from app.connectors.base import ListingRef
from app.connectors.laforet import LaforetConnector
from app.core.http import PoliteClient
from app.services.zone import ZoneIndex

PAGES = Path(__file__).parent / "pages"
URL = "https://www.laforet.com/agence-immobiliere/bernay/acheter/lisieux/maison-10-pieces-52601493"
ZONE = ZoneIndex([("14520", "Le Pré-d'Auge", "14"), ("14366", "Lisieux", "14"), ("14225", "Dives-sur-Mer", "14")])
CFG = {
    "base_url": "https://www.laforet.com",
    "sitemaps": ["https://www.laforet.com/storage/sitemaps/produits.xml"],
    "url_regex": "/agence-immobiliere/[^/]+/acheter/[^/]+/maison-",
}
SITEMAP = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">
<url><loc>https://www.laforet.com/agence-immobiliere/bernay/acheter/lisieux/maison-10-pieces-52601493</loc><image:image><image:loc>https://img.example/a.jpg</image:loc></image:image></url>
<url><loc>https://www.laforet.com/agence-immobiliere/bernay/acheter/lisieux/appartement-2-pieces-52000001</loc></url>
<url><loc>https://www.laforet.com/agence-immobiliere/brest/acheter/brest/maison-6-pieces-52978480</loc></url>
<url><loc>https://www.laforet.com/agence-immobiliere/houlgate/acheter/dives-sur-mer/maison-5-pieces-52634720</loc></url>
<url><loc>https://www.laforet.com/agence-immobiliere/lisieux/louer/lisieux/maison-4-pieces-21000000</loc></url>
</urlset>"""


def _conn(tmp_path, zone=ZONE):
    c = LaforetConnector(dict(CFG), PoliteClient(min_delay=0, cache_dir=tmp_path))
    c.zone = zone
    return c


@respx.mock
def test_discover_filters_zone_type_and_sale(tmp_path):
    respx.get("https://www.laforet.com/robots.txt").mock(return_value=httpx.Response(200, text="User-agent: *\nDisallow: /bien/*/pdf\n"))
    respx.get("https://www.laforet.com/storage/sitemaps/produits.xml").mock(return_value=httpx.Response(200, content=SITEMAP))
    refs = list(_conn(tmp_path).discover())
    assert [r.external_id for r in refs] == ["52601493", "52634720"]  # ni appartement, ni Brest, ni location


@respx.mock
def test_fetch_real_page(tmp_path):
    respx.get("https://www.laforet.com/robots.txt").mock(return_value=httpx.Response(404))
    respx.get(URL).mock(return_value=httpx.Response(200, text=(PAGES / "laforet_detail.html").read_text(encoding="utf8")))
    d = _conn(tmp_path).fetch(ListingRef(url=URL, external_id="52601493"))
    assert d.price == 435000 and d.surface == 220 and d.land == 5500 and d.rooms == 10 and d.bedrooms == 5
    assert d.commune_name == "Le Pré-d'Auge" and d.postal_code == "14340" and d.extra["commune_code"] == "14520"
    assert d.property_type == "maison" and d.heating == "Fuel" and d.year_built is None
    assert len(d.photos) == 18 and all("52601493" in p for p in d.photos)
    assert d.description.startswith("Élégance") and "vous accueille" not in d.description and "REF" not in d.description
    assert d.contact["agence"] == "Laforêt BERNAY"


@respx.mock
def test_fetch_out_of_zone_is_skipped(tmp_path):
    respx.get("https://www.laforet.com/robots.txt").mock(return_value=httpx.Response(404))
    respx.get(URL).mock(return_value=httpx.Response(200, text=(PAGES / "laforet_detail.html").read_text(encoding="utf8")))
    other = ZoneIndex([("14366", "Lisieux", "14")])  # Le Pré-d'Auge n'y est pas : « près de Lisieux » ne suffit pas
    assert _conn(tmp_path, other).fetch(ListingRef(url=URL, external_id="52601493")) is None


@respx.mock
def test_fetch_404(tmp_path):
    respx.get("https://www.laforet.com/robots.txt").mock(return_value=httpx.Response(404))
    respx.get(URL).mock(return_value=httpx.Response(404))
    assert _conn(tmp_path).fetch(ListingRef(url=URL)) is None
