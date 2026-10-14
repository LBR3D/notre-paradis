import gzip
from datetime import date, timedelta

from app.datasources.dvf import DvfSource, parse_dvf
from app.datasources.routes import next_friday
from app.models import DvfSale, Property
from app.settings_schema import UserSettings

CSV = (
    "id_mutation,date_mutation,nature_mutation,valeur_fonciere,adresse_numero,adresse_nom_voie,code_postal,code_commune,nom_commune,id_parcelle,type_local,surface_reelle_bati,nombre_pieces_principales,surface_terrain,longitude,latitude\n"
    "m1,2025-03-01,Vente,250000,3,RUE X,14130,14514,Pont-l'Évêque,p1,Maison,100,5,800,0.18,49.28\n"
    "m1,2025-03-01,Vente,250000,3,RUE X,14130,14514,Pont-l'Évêque,p2,,,,400,0.18,49.28\n"
    "m2,2025-03-02,Vente,180000,,,14130,14514,Pont-l'Évêque,p3,Appartement,60,3,,0.18,49.28\n"
    "m3,2025-03-03,Vente,300000,,,14130,14514,Pont-l'Évêque,p4,Maison,90,4,500,0.18,49.28\n"
    "m3,2025-03-03,Vente,300000,,,14130,14514,Pont-l'Évêque,p4,Maison,60,2,500,0.18,49.28\n"
    "m4,2025-03-04,Echange,100000,,,14130,14514,Pont-l'Évêque,p5,Maison,90,4,500,0.18,49.28\n"
)


def test_parse_dvf_keeps_single_house_sales():
    out = parse_dvf(gzip.compress(CSV.encode()))
    assert [x["id"] for x in out] == ["m1"]
    assert out[0]["land"] == 1200 and out[0]["surface"] == 100 and out[0]["price"] == 250000


def test_enrich_dvf_estimates_gap(db):
    for i in range(8):
        db.add(DvfSale(id_mutation=f"s{i}", sold_on=date.today() - timedelta(days=100), price=200000 + i * 5000, commune_code="14514", surface=100))
    p = Property(commune_code="14514", price=300000, surface=100)
    db.add(p)
    db.flush()
    res = DvfSource().enrich(db, p, UserSettings())["dvf"]
    assert res["n"] == 8 and res["estimation"] == 218000 or res["estimation"] == 217000
    assert res["ecart_pct"] > 30 and res["marge_negociation"] > 70000


def test_next_friday_is_future_friday():
    d = next_friday("18:00")
    assert d.weekday() == 4 and d.hour == 18
