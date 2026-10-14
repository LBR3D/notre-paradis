from pathlib import Path

import httpx
import respx

from app.connectors.base import ListingRef
from app.connectors.immonot import ImmonotConnector, extract_immonot, match_slug
from app.core.http import PoliteClient
from app.extract.notarial import parse_honoraires, parse_land_text
from app.services.zone import ZoneIndex

PAGES = Path(__file__).parent / "pages"
ZONE = ZoneIndex([
    ("14366", "Lisieux", "14"),
    ("14714", "Livarot-Pays-d'Auge", "14"),
    ("14333", "Honfleur", "14"),
    ("27691", "Pont-Audemer", "27"),
])
D = "https://www.immonot.com/immobilier-notaire/detail"
URL = f"{D}/0000013224_61089-959/achat-maison-a-vendre-14140-livarot-pays-d-auge-calvados.html"

INDEX = b"""<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<sitemap><loc>https://www.immonot.com/sitemap/landing/chunk-1.xml</loc></sitemap>
<sitemap><loc>https://www.immonot.com/sitemap/annonce_detail_ancien/chunk-1.xml</loc></sitemap></sitemapindex>"""
URLSET = f"""<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>{URL}</loc></url>
<url><loc>{D}/l800242829/achat-maison-a-vendre-14600-honfleur-calvados.html</loc></url>
<url><loc>{D}/l800242830/achat-maison-a-vendre-29860-plabennec-finistere.html</loc></url>
<url><loc>{D}/l800242831/location-maison-14100-lisieux-calvados.html</loc></url>
<url><loc>{D}/l800242832/achat-terrain-a-batir-a-vendre-14100-lisieux-calvados.html</loc></url>
<url><loc>{D}/l800242833/achat-appartement-a-vendre-14100-lisieux-calvados.html</loc></url>
<url><loc>{D}/l800242834/viager-maison-14100-lisieux-calvados.html</loc></url>
<url><loc>{D}/2516756/achat-propriete-a-vendre-27500-pont-audemer-eure.html</loc></url>
<url><loc>{D}/l800242835/achat-maison-a-vendre-61000-lisieux-orne.html</loc></url></urlset>""".encode()

CFG = {
    "sitemaps": ["https://www.immonot.com/sitemap.xml"],
    "sitemap_regex": "annonce_detail_ancien",
    "url_regex": r"/detail/[^/]+/achat-(?:maison|propriete)-a-vendre-",
}


def page() -> str:
    return (PAGES / "immonot_detail.html").read_text(encoding="utf8")


def test_match_slug_reads_commune_after_postal_code():
    assert match_slug(ZONE, URL).commune_code == "14714"
    assert match_slug(ZONE, URL).postal_code == "14140"
    assert match_slug(ZONE, f"{D}/x/achat-maison-a-vendre-14600-honfleur-calvados.html").commune_code == "14333"
    assert match_slug(ZONE, f"{D}/x/achat-maison-a-vendre-27500-pont-audemer-eure.html").commune_code == "27691"
    assert match_slug(ZONE, f"{D}/x/achat-maison-a-vendre-29860-plabennec-finistere.html") is None
    # bon code postal mais commune d'un autre département : refusée
    assert match_slug(ZONE, f"{D}/x/achat-maison-a-vendre-61000-lisieux-orne.html") is None


def test_extract_notary_page():
    d = extract_immonot(page(), URL)
    assert d.price == 273000 and d.surface == 130 and d.land == 827 and d.rooms == 6 and d.bedrooms == 4
    assert d.property_type == "maison"
    assert d.dpe == "E" and d.ges == "E"
    assert d.fees == "Honoraires TTC : 13 000 € (5.00 % à la charge de l'acquéreur)"
    assert d.extra["prix_net_vendeur"] == 260000 and d.extra["honoraires"]["taux"] == 5.0
    assert d.contact["nom"] == "SELARL Anne-Marie SÉJOURNÉ" and "Vimoutiers" in d.contact["adresse"]
    assert d.contact["telephone"] and d.contact["email"]
    assert d.heating == "chauffage au gaz de ville"
    assert d.commune_name == "Livarot-Pays-d'Auge" and d.postal_code == "14140"
    assert d.external_id and d.extra["reference_etude"] == "61089-959"
    assert len(d.photos) >= 10 and len(set(d.photos)) == len(d.photos)
    assert all("/immonot/photo/" in p for p in d.photos)
    assert "beau pavillon" in d.description and "Contacter" not in d.description
    # coordonnées du JSON-LD = celles de l'étude, pas du bien
    assert d.lat is None and d.lon is None


def test_parse_helpers():
    h = parse_honoraires("200 000 € + Honoraires de négociation TTC : 6 840 €. Soit 3.42% à la charge de l'acquéreur")
    assert h["net"] == 200000 and h["honoraires"] == 6840 and h["taux"] == 3.42 and h["charge"] == "acquereur"
    assert parse_honoraires("Prix 100 000 €") == {}
    assert parse_land_text("terrain clos de 1 hectare, 77 ares et 20 centiares") == 17720
    assert parse_land_text("sur 827 m² de terrain") == 827


@respx.mock
def test_discover_sitemap_filters_zone_and_sale_type(tmp_path):
    respx.get("https://www.immonot.com/robots.txt").mock(return_value=httpx.Response(200, text="User-agent: *\nDisallow: /api/\nAllow: /\n"))
    respx.get("https://www.immonot.com/sitemap.xml").mock(return_value=httpx.Response(200, content=INDEX))
    chunk = respx.get("https://www.immonot.com/sitemap/annonce_detail_ancien/chunk-1.xml").mock(return_value=httpx.Response(200, content=URLSET))
    landing = respx.get("https://www.immonot.com/sitemap/landing/chunk-1.xml").mock(return_value=httpx.Response(200, content=URLSET))
    c = ImmonotConnector(CFG, PoliteClient(min_delay=0, cache_dir=tmp_path))
    c.zone = ZONE
    refs = list(c.discover())
    assert [r.url for r in refs] == [URL, f"{D}/l800242829/achat-maison-a-vendre-14600-honfleur-calvados.html", f"{D}/2516756/achat-propriete-a-vendre-27500-pont-audemer-eure.html"]
    assert refs[0].external_id == "0000013224_61089-959" and refs[0].hint["commune_code"] == "14714"
    assert chunk.called and not landing.called  # seul le sitemap des fiches « ancien » est lu


@respx.mock
def test_fetch_applies_hint_and_handles_gone_and_viager(tmp_path):
    respx.get("https://www.immonot.com/robots.txt").mock(return_value=httpx.Response(404))
    respx.get(URL).mock(return_value=httpx.Response(200, text=page()))
    gone = f"{D}/l1/achat-maison-a-vendre-14600-honfleur-calvados.html"
    respx.get(gone).mock(return_value=httpx.Response(404))
    viager = f"{D}/l2/achat-maison-a-vendre-14600-honfleur-calvados.html"
    respx.get(viager).mock(return_value=httpx.Response(200, text=page().replace("beau pavillon", "maison en viager occupé")))
    c = ImmonotConnector(CFG, PoliteClient(min_delay=0, cache_dir=tmp_path))
    c.zone = ZONE
    hint = {"commune_code": "14714", "commune_name": "Livarot-Pays-d'Auge", "postal_code": "14140"}
    d = c.fetch(ListingRef(url=URL, external_id="0000013224_61089-959", hint=hint))
    assert d.price == 273000 and d.extra["commune_code"] == "14714" and d.external_id == "0000013224_61089-959"
    assert c.fetch(ListingRef(url=gone)) is None
    assert c.fetch(ListingRef(url=viager)) is None  # viager : le prix affiché est un bouquet
