import json
from pathlib import Path

import httpx
import respx

from app.connectors.agency_site import AgencySiteConnector
from app.connectors.base import ListingRef
from app.core.http import PoliteClient
from app.services.zone import ZoneIndex

ROOT = Path(__file__).parent
BASE = "https://www.cheychrys-immobilier.com"
CFG = json.loads((ROOT.parent / "app/connectors/sources/cheychrys-immobilier.json").read_text(encoding="utf8"))["config"]
ZONE = ZoneIndex([("14333", "Honfleur", "14"), ("14292", "Genneville", "14"), ("14551", "La Rivière-Saint-Sauveur", "14"), ("14073", "Cormeilles", "27")])
DETAIL = f"{BASE}/vente/14-calvados/37-genneville/1-maison/t6/2042-maison-normande-de-charme-dans-un-bel-environnement-de-campagne/"
LOCS = [
    f"{BASE}/vente/1",
    f"{BASE}/vente/14-calvados/1-honfleur/1-maison/t4/1933-honfleur-maison-avec-cour/",
    f"{BASE}/vente/14-calvados/1-honfleur/2-appartement/t3/1880-vente-appartement-centre-ville-honfleur/",
    f"{BASE}/vente/14-calvados/8-la-riviere-st-sauveur/1-maison/t3/1965-maison-de-ville-avec-terrasse-exposee-sud/",
    f"{BASE}/vente/14-calvados/33-ablon/1-maison/t4/1879-maison-traditionnelle-de-1978/",  # Ablon absent de la zone de test
    f"{BASE}/vente/27-eure/26-berville-sur-mer/1-maison/t5/2049-berville-sur-mer-maison-familiale/",
    f"{BASE}/location/14-calvados/1-honfleur/1-maison/t4/1000-maison-a-louer/",
    DETAIL,
]
SITEMAP = ('<?xml version="1.0"?><urlset xmlns="https://www.sitemaps.org/schemas/sitemap/0.9">' + "".join(f"<url><loc>{u}</loc></url>" for u in LOCS) + "</urlset>").encode()


@respx.mock
def test_discover_uses_department_and_commune_from_url(tmp_path):
    respx.get(f"{BASE}/robots.txt").mock(return_value=httpx.Response(200, text="User-agent: *\nDisallow: /admin\nAllow: /\n"))
    respx.get(f"{BASE}/sitemap.xml").mock(return_value=httpx.Response(200, content=SITEMAP))
    c = AgencySiteConnector(CFG, PoliteClient(min_delay=0, cache_dir=tmp_path))
    c.zone = ZONE
    refs = list(c.discover())
    assert [(r.external_id, r.hint["commune_name"]) for r in refs] == [
        ("1933", "Honfleur"),
        ("1965", "La Rivière-Saint-Sauveur"),
        ("2042", "Genneville"),
    ]


@respx.mock
def test_fetch_real_page(tmp_path):
    page = (ROOT / "pages" / "cheychrys_detail.html").read_text(encoding="utf8")
    respx.get(f"{BASE}/robots.txt").mock(return_value=httpx.Response(404))
    respx.get(DETAIL).mock(return_value=httpx.Response(200, text=page))
    c = AgencySiteConnector(CFG, PoliteClient(min_delay=0, cache_dir=tmp_path))
    d = c.fetch(ListingRef(url=DETAIL, external_id="2042", hint={"commune_code": "14292", "commune_name": "Genneville"}))
    assert d.external_id == "2042" and d.commune_name == "Genneville" and d.postal_code == "14600"
    assert d.price == 375000 and d.surface == 118.5 and d.land == 3000 and d.rooms == 6 and d.bedrooms == 3
    assert d.year_built == 1900 and d.property_tax == 1780 and d.heating == "Pompe à chaleur"
    assert d.property_type == "maison" and "maison normande" in d.description.lower()
    assert len(d.photos) >= 8
    assert not any("/modules/partners/" in p for p in d.photos)
    assert len(d.photos) == len({p.rsplit("/", 1)[-1] for p in d.photos})  # une seule taille par cliché
    assert all("/1600xauto/" in p for p in d.photos)
