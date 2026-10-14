import httpx
import respx

from app.models import Listing, Property, Source
from app.services.geoloc import ADEME, BAN, _periode_ok, geolocate_all


def test_periode():
    assert _periode_ok(1960, "1948-1974") and not _periode_ok(1900, "1948-1974")
    assert _periode_ok(1900, "avant 1948") and _periode_ok(None, "1948-1974")


def _setup(db, **li):
    src = Source(key="g", name="g", kind="agence", connector="sitemap")
    db.add(src)
    db.flush()
    l = Listing(source_id=src.id, url="https://x/" + str(li), commune_code="14514", postal_code="14130", status="active", **li)
    p = Property(commune_code="14514", surface=li.get("surface"))
    l.property = p
    db.add(l)
    db.flush()
    return p


@respx.mock
def test_address_gives_A(db):
    p = _setup(db, address="12 rue de Vaucelles")
    respx.get(BAN).mock(return_value=httpx.Response(200, json={"features": [{"geometry": {"coordinates": [0.1816, 49.2842]}, "properties": {"type": "housenumber", "score": 0.96, "citycode": "14514", "label": "12 Rue de Vaucelles"}}]}))
    assert geolocate_all(db) == {"A": 1}
    assert p.geo_confidence == "A"


@respx.mock
def test_unique_dpe_gives_B(db):
    p = _setup(db, surface=92.0, dpe="F")
    respx.get(ADEME).mock(return_value=httpx.Response(200, json={"results": [{"adresse_ban": "7 Avenue de la Libération 14130 Pont-l'Évêque", "_geopoint": "49.2820,0.1858", "etiquette_dpe": "F", "surface_habitable_logement": 92, "periode_construction": "1948-1974", "code_insee_ban": "14514"}]}))
    assert geolocate_all(db) == {"B": 1}
    assert p.geo_candidates[0]["adresse"].startswith("7 Avenue")


@respx.mock
def test_fallback_to_commune_centre_D(db):
    _setup(db, surface=92.0)
    respx.get(ADEME).mock(return_value=httpx.Response(200, json={"results": []}))
    res = geolocate_all(db)
    assert res in ({"D": 1}, {"?": 1})


@respx.mock
def test_dpe_near_listing_coordinates_gives_B(db):
    p = _setup(db, surface=92.0, lat=49.2820, lon=0.1858)
    two = [
        {"adresse_ban": "7 Avenue A", "_geopoint": "49.2821,0.1860", "etiquette_dpe": "F", "surface_habitable_logement": 92, "code_insee_ban": "14514"},
        {"adresse_ban": "9 Rue Lointaine", "_geopoint": "49.3200,0.2500", "etiquette_dpe": "E", "surface_habitable_logement": 92, "code_insee_ban": "14514"},
    ]
    respx.get(ADEME).mock(return_value=httpx.Response(200, json={"results": two}))
    assert geolocate_all(db) == {"B": 1}
    assert p.geo_method.startswith("DPE + coordonnées")
