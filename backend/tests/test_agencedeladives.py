import json
from pathlib import Path

import httpx
import respx

from app.connectors.agency_site import AgencySiteConnector, dedupe_photos, norm_slug
from app.connectors.base import ListingRef
from app.core.http import PoliteClient
from app.services.zone import ZoneIndex

ROOT = Path(__file__).parent
BASE = "https://www.agencedeladives.com"
CFG = json.loads((ROOT.parent / "app/connectors/sources/agence-de-la-dives.json").read_text(encoding="utf8"))["config"]
ZONE = ZoneIndex([("14654", "Saint-Pierre-en-Auge", "14"), ("14366", "Lisieux", "14")])
SITEMAP = f"""<?xml version='1.0' encoding='utf-8'?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>{BASE}</loc></url>
<url><loc>{BASE}/vente/maison</loc></url>
<url><loc>{BASE}/vente/appartement-3-pieces-lisieux-14100,VA1970</loc></url>
<url><loc>{BASE}/vente/maison-ancienne-9-pieces-jort-14170,VM502</loc></url>
<url><loc>{BASE}/vente/maison-traditionnelle-6-pieces-saint-pierre-en-auge-14170,VM360</loc></url>
<url><loc>{BASE}/vente/,VM444</loc></url>
<url><loc>{BASE}/vente/maison-individuelle-5-pieces-saint-pierre-en-auge-14170,VM479</loc></url>
<url><loc>{BASE}/vente/maison/saint-pierre-en-auge/14170</loc></url>
<url><loc>{BASE}/location/maison-5-pieces-lisieux-14100,LM12</loc></url>
</urlset>""".encode()
DETAIL = f"{BASE}/vente/maison-ancienne-9-pieces-jort-14170,VM502"


@respx.mock
def test_discover_keeps_sale_houses_of_the_zone(tmp_path):
    respx.get(f"{BASE}/robots.txt").mock(return_value=httpx.Response(200, text="User-agent: *\nCrawl-delay: 5\n"))
    respx.get(f"{BASE}/sitemap.xml").mock(return_value=httpx.Response(200, content=SITEMAP))
    c = AgencySiteConnector(CFG, PoliteClient(min_delay=0, cache_dir=tmp_path))
    c.zone = ZONE
    refs = list(c.discover())
    # Jort n'est pas dans la zone de test ; appartement, location, pages de liste et adresse sans commune écartés
    assert [r.external_id for r in refs] == ["VM360", "VM479"]
    assert refs[0].hint["commune_name"] == "Saint-Pierre-en-Auge" and refs[0].hint["postal_code"] == "14170"


@respx.mock
def test_fetch_real_page(tmp_path):
    page = (ROOT / "pages" / "agencedeladives_detail.html").read_text(encoding="utf8")
    respx.get(f"{BASE}/robots.txt").mock(return_value=httpx.Response(404))
    respx.get(DETAIL).mock(return_value=httpx.Response(200, text=page))
    c = AgencySiteConnector(CFG, PoliteClient(min_delay=0, cache_dir=tmp_path))
    d = c.fetch(ListingRef(url=DETAIL, hint={"commune_code": "14333", "commune_name": "Jort", "postal_code": "14170"}))
    assert d.external_id == "VM502" and d.commune_name == "Jort" and d.postal_code == "14170"
    assert d.price == 318300 and d.surface == 208 and d.land == 1766 and d.rooms == 9 and d.bedrooms == 6
    assert d.dpe == "D" and d.ges == "B" and d.year_built is None  # « l'année 2023 » du texte DPE n'est pas une année de construction
    assert "Bois" in d.heating and "belles bâtisses" in d.description
    assert len(d.photos) >= 20 and not any("/dpe/" in p for p in d.photos)
    assert len(d.photos) == len({p.split("_original")[0].split("_l.")[0] for p in d.photos})  # un cliché une seule fois
    assert all("_original." in p for p in d.photos if "VM502_21" in p)


def test_dedupe_photos_prefers_size_and_excludes():
    ph = ["https://c/x/a_1_l.jpg", "https://c/x/a_1_original.jpg", "https://c/x/a_2_l.jpg", "https://c/dpe/dpe_1.png"]
    assert dedupe_photos(ph, r"(a_\d+)_", r"_original\.", "/dpe/") == ["https://c/x/a_1_original.jpg", "https://c/x/a_2_l.jpg"]


def test_norm_slug_matches_abbreviations():
    assert norm_slug("la-riviere-st-sauveur") == norm_slug("La Rivière-Saint-Sauveur")
    assert norm_slug("pont-leveque") == norm_slug("Pont-l'Évêque")
