from pathlib import Path

import httpx
import pytest
import respx

from app.connectors.base import ListingRef
from app.connectors.century21 import Century21Connector, parse_list, zone_hit
from app.core.http import PoliteClient, RobotsDisallowed
from app.services.zone import ZoneIndex

PAGES = Path(__file__).parent / "pages"
BASE = "https://www.century21.fr"
URL = f"{BASE}/trouver_logement/detail/16998218041/"
ZONE = ZoneIndex([
    ("14366", "Lisieux", "14"), ("14544", "La Rivière-Saint-Sauveur", "14"), ("14514", "Pont-l'Évêque", "14"),
    ("14525", "Saint-Martin-de-la-Lieue", "14"), ("14137", "Livarot-Pays-d'Auge", "14"),
])
ROBOTS = """User-Agent: *
Disallow: /a/*/annonces/
Disallow: /annonces/achat-maison/cp-
Disallow: /annonces/achat/cp-
Disallow: /annonces/f/
Disallow: /trouver_logement/detail_non_publie/
"""


def card(uid: str, commune: str, dep: str = "14", price: str = "250 000") -> str:
    return f"""<div class="tw-grid js-the-list-of-properties-list-property"><div class="c-the-property-thumbnail-with-content js-the-property-thumbnail-with-content tw-grid" data-uid="{uid}" >
<a href="/trouver_logement/detail/{uid}/"><img data-src="/imagesBien/x.jpg"></a>
<h3 class="x"><div class="y"> {commune}&nbsp; {dep} <br /> 110 m<sup>2</sup>, 5 pièces <div class="z"> Ref : 12{uid[-2:]} </div> </div>
<div><div> Maison à vendre </div><div class="p"> {price}&nbsp;&euro; </div></div></h3></div></div>"""


LIST1 = "<html>" + card("10000000001", "LISIEUX") + card("10000000002", "ST MARTIN DE LA LIEUE") + card("10000000003", "IFS") + '<a href="/annonces/achat-maison/d-14_calvados/page-2/">2</a></html>'
LIST2 = "<html>" + card("10000000002", "ST MARTIN DE LA LIEUE") + card("10000000004", "LA RIVIERE ST SAUVEUR") + "</html>"  # 10000000002 déjà vue


def _conn(tmp_path):
    c = Century21Connector({"departements": ["14_calvados"], "max_pages": 5}, PoliteClient(min_delay=0, cache_dir=tmp_path))
    c.zone = ZONE
    return c


def test_parse_list_and_zone_hit():
    cards = parse_list(LIST1)
    assert [(c["uid"], c["commune"], c["dep"], c["price"]) for c in cards] == [
        ("10000000001", "LISIEUX", "14", 250000), ("10000000002", "ST MARTIN DE LA LIEUE", "14", 250000), ("10000000003", "IFS", "14", 250000),
    ]
    assert zone_hit(ZONE, "ST MARTIN DE LA LIEUE", "14")[0] == "14525"  # « ST » = « Saint »
    assert zone_hit(ZONE, "LA RIVIERE ST SAUVEUR", "14")[0] == "14544"
    assert zone_hit(ZONE, "LIVAROT PAYS D AUGE", "14")[0] == "14137"
    assert zone_hit(ZONE, "IFS", "14") is None and zone_hit(ZONE, "LISIEUX", "61") is None


@respx.mock
def test_discover_department_lists(tmp_path):
    respx.get(f"{BASE}/robots.txt").mock(return_value=httpx.Response(200, text=ROBOTS))
    p1 = respx.get(f"{BASE}/annonces/achat-maison/d-14_calvados/").mock(return_value=httpx.Response(200, text=LIST1))
    p2 = respx.get(f"{BASE}/annonces/achat-maison/d-14_calvados/page-2/").mock(return_value=httpx.Response(200, text=LIST2))
    refs = list(_conn(tmp_path).discover())
    assert p1.called and p2.called and len(respx.calls) == 3  # robots + 2 pages : pas de page 3, pas d'autre adresse
    assert [r.external_id for r in refs] == ["10000000001", "10000000002", "10000000004"]  # IFS hors zone, doublon écarté
    assert refs[0].url == f"{BASE}/trouver_logement/detail/10000000001/"
    assert refs[1].hint == {"commune_code": "14525", "commune_name": "Saint-Martin-de-la-Lieue"}


@respx.mock
def test_robots_forbids_postal_code_searches(tmp_path):
    respx.get(f"{BASE}/robots.txt").mock(return_value=httpx.Response(200, text=ROBOTS))
    client = PoliteClient(min_delay=0, cache_dir=tmp_path)
    assert client.allowed(f"{BASE}/annonces/achat-maison/d-14_calvados/")
    assert client.allowed(f"{BASE}/trouver_logement/detail/16998218041/")
    assert not client.allowed(f"{BASE}/annonces/achat-maison/cp-14100_lisieux/")
    assert not client.allowed(f"{BASE}/trouver_logement/detail_non_publie/1/")
    with pytest.raises(RobotsDisallowed):
        client.get(f"{BASE}/annonces/achat-maison/cp-14100_lisieux/")


@respx.mock
def test_fetch_real_page(tmp_path):
    respx.get(f"{BASE}/robots.txt").mock(return_value=httpx.Response(200, text=ROBOTS))
    respx.get(URL).mock(return_value=httpx.Response(200, text=(PAGES / "century21_detail.html").read_text(encoding="utf8")))
    ref = ListingRef(url=URL, external_id="16998218041", hint={"commune_code": "14544", "commune_name": "La Rivière-Saint-Sauveur"})
    d = _conn(tmp_path).fetch(ref)
    assert d.price == 336000 and d.surface == 159.92 and d.land == 240 and d.rooms == 7 and d.bedrooms == 5
    assert d.commune_name == "La Rivière-Saint-Sauveur" and d.postal_code == "14600" and d.extra["commune_code"] == "14544"
    assert d.property_type == "maison" and d.year_built is None
    assert d.heating == "Individuel radiateur electricité" and d.condition == "Travaux à prévoir : Le RDC"
    assert "317000" in d.fees and "6 %" in d.fees
    assert len(d.photos) == 8 and all("c21_202_3802_176_" in p for p in d.photos) and d.photos[0].startswith(BASE)
    assert d.description.startswith("Dans la commune recherchée") and "Résumé" not in d.description
    assert d.contact["agence"].startswith("CENTURY 21") and d.contact["telephone"]
