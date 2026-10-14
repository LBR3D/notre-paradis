import json
from pathlib import Path

import httpx
import respx

from app.connectors.base import ListingRef
from app.connectors.espaces_atypiques import EspacesAtypiquesConnector
from app.core.http import PoliteClient
from app.services.zone import ZoneIndex

ROOT = Path(__file__).parent
BASE = "https://www.espaces-atypiques.com"
CFG = json.loads((ROOT.parent / "app/connectors/sources/espaces-atypiques.json").read_text(encoding="utf8"))["config"]
ZONE = ZoneIndex([("14654", "Belle Vie en Auge", "14"), ("14514", "Pont-l'Évêque", "14"), ("14711", "Touques", "14"), ("14333", "Honfleur", "14"), ("14137", "Saint-Pierre-en-Auge", "14")])
ROBOTS = "User-agent: *\nDisallow: /wp-admin/\nDisallow: /*?*\nDisallow: /*/page/1/\nDisallow: /*/page/6*\nDisallow: /biens-vendus/\n"
DETAIL = f"{BASE}/ventes/14270-belle-vie-en-auge-maison-de-maitre-et-ses-herbages-18074/"


def links(*slugs: str) -> str:
    return "".join(f'<a href="{BASE}/ventes/{s}/">x</a>' for s in slugs)


PAGE1 = (
    links(
        "14270-belle-vie-en-auge-maison-de-maitre-et-ses-herbages-18074",
        "14130-pont-l-eveque-manoir-du-xvi-eme-siecle-et-son-parc-17764",
        "14000-caen-maison-darchitecte-avec-piscine-au-coeur-de-ville-18617",  # Caen hors zone de test
        "14170-saint-pierre-en-auge-maison-normande-renovee-et-dependances-17878",
        "14170-saint-pierre-en-auge-maison-normande-renovee-et-dependances-17878",
    )
    + f'<a href="{BASE}/ventes/maison/14-calvados/?orderby=prix">tri</a>'
    + f'<link rel="next" href="{BASE}/ventes/maison/14-calvados/page/2/" />'
)
PAGE2 = links("14800-touques-maison-de-pecheur-avec-terrasse-au-calme-18739") + f'<link rel="next" href="{BASE}/ventes/maison/14-calvados/page/6/" />'


@respx.mock
def test_discover_reads_listing_pages_within_robots(tmp_path):
    respx.get(f"{BASE}/robots.txt").mock(return_value=httpx.Response(200, text=ROBOTS))
    p1 = respx.get(f"{BASE}/ventes/maison/14-calvados/").mock(return_value=httpx.Response(200, text=PAGE1))
    p2 = respx.get(f"{BASE}/ventes/maison/14-calvados/page/2/").mock(return_value=httpx.Response(200, text=PAGE2))
    p6 = respx.get(f"{BASE}/ventes/maison/14-calvados/page/6/").mock(return_value=httpx.Response(200, text=PAGE1))
    cfg = dict(CFG, listing_pages=[f"{BASE}/ventes/maison/14-calvados/"])
    c = EspacesAtypiquesConnector(cfg, PoliteClient(min_delay=0, cache_dir=tmp_path))
    c.zone = ZONE
    refs = list(c.discover())
    assert [(r.external_id, r.hint["commune_name"], r.hint["postal_code"]) for r in refs] == [
        ("18074", "Belle Vie en Auge", "14270"),
        ("17764", "Pont-l'Évêque", "14130"),
        ("17878", "Saint-Pierre-en-Auge", "14170"),
        ("18739", "Touques", "14800"),
    ]
    assert p1.called and p2.called and not p6.called  # /page/6/ interdit par robots.txt, jamais de « ? »
    assert not any("?" in str(call.request.url) for call in respx.calls)


@respx.mock
def test_fetch_real_page(tmp_path):
    page = (ROOT / "pages" / "espaces_atypiques_detail.html").read_text(encoding="utf8")
    respx.get(f"{BASE}/robots.txt").mock(return_value=httpx.Response(200, text=ROBOTS))
    respx.get(DETAIL).mock(return_value=httpx.Response(200, text=page))
    c = EspacesAtypiquesConnector(CFG, PoliteClient(min_delay=0, cache_dir=tmp_path))
    ref = ListingRef(url=DETAIL, external_id="18074", hint={"commune_code": "14654", "commune_name": "Belle Vie en Auge", "postal_code": "14270"})
    d = c.fetch(ref)
    assert d.external_id == "18074" and d.postal_code == "14270" and d.commune_name == "Belle Vie en Auge"
    assert d.price == 473000 and d.surface == 164 and d.land == 18888 and d.rooms == 7 and d.bedrooms == 4
    assert d.property_tax == 890 and d.dpe == "E" and d.ges == "E"
    assert round(d.lat, 3) == 49.072 and round(d.lon, 3) == 0.054
    assert d.property_type == "maison" and "Situ" in d.description
    assert len(d.photos) == 13
    assert all("/wp-content/uploads/" in p for p in d.photos)  # ni thème, ni fond de carte, ni miniatures
    assert not any("-480x320" in p for p in d.photos)


@respx.mock
def test_sold_listing_is_ignored(tmp_path):
    page = (ROOT / "pages" / "espaces_atypiques_detail.html").read_text(encoding="utf8").replace("statut-offre-en-cours", "statut-offre-vendu")
    respx.get(f"{BASE}/robots.txt").mock(return_value=httpx.Response(200, text=ROBOTS))
    respx.get(DETAIL).mock(return_value=httpx.Response(200, text=page))
    c = EspacesAtypiquesConnector(CFG, PoliteClient(min_delay=0, cache_dir=tmp_path))
    assert c.fetch(ListingRef(url=DETAIL)) is None
