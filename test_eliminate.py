from app.models import Property
from app.services.eliminate import evaluate, evaluate_all
from app.settings_schema import UserSettings

S = UserSettings()


def prop(**kw):
    base = dict(price=300000, surface=150, land=5000, bedrooms=3, geo_confidence="A")
    base.update(kw)
    return Property(**base)


def codes(reasons, certitude=None):
    return {r["critere"] for r in reasons if certitude in (None, r["certitude"])}


def test_clean_property_has_no_reason():
    assert evaluate(prop(), {}, S) == []


def test_user_criteria():
    r = evaluate(prop(price=900000, surface=60, bedrooms=1, land=500, year_built=2010), {}, S)
    assert codes(r, "certaine") == {"prix", "surface", "chambres", "terrain", "type"}


def test_missing_data_never_eliminates():
    assert evaluate(prop(price=None, surface=None, land=None, bedrooms=None), {}, S) == []


def test_noise_certain_when_position_precise():
    enr = {"bruit": {"autoroute_m": 800, "route_chargee_m": 100, "voie_ferree_m": None, "aerodrome_m": 5000}}
    r = evaluate(prop(geo_confidence="A"), enr, S)
    assert codes(r, "certaine") == {"autoroute", "route_chargee"}


def test_noise_only_to_verify_when_position_approximate():
    enr = {"bruit": {"autoroute_m": 1200, "route_chargee_m": 100}}
    r = evaluate(prop(geo_confidence="D"), enr, S)
    assert codes(r, "certaine") == set()
    assert codes(r, "a_verifier") == {"autoroute", "route_chargee"}
    # position approximative (C, ±600 m) : une route à 0 m reste « à vérifier », jamais éliminatoire
    r = evaluate(prop(geo_confidence="C"), {"bruit": {"route_chargee_m": 0}}, S)
    assert codes(r, "certaine") == set() and codes(r, "a_verifier") == {"route_chargee"}


def test_livestock_wind_and_methaniser():
    enr = {"elevage": {"elevages": [{"nom": "GAEC X", "distance_m": 1300, "distance_ponderee_m": 866, "au_vent": True}], "methaniseurs": [{"nom": "Métha", "distance_m": 1000}]}}
    r = evaluate(prop(), enr, S)
    assert codes(r, "certaine") == {"elevage", "methaniseur"}
    s2 = UserSettings()
    s2.eliminatoires.ponderer_vent_dominant = False
    assert "elevage" not in codes(evaluate(prop(), enr, s2))


def test_big_crops_threshold_and_switch_off():
    enr = {"agriculture": {"disponible": True, "rayon_m": 1000, "grandes_cultures": 70}}
    assert codes(evaluate(prop(geo_confidence="B"), enr, S), "certaine") == {"grandes_cultures"}
    assert codes(evaluate(prop(geo_confidence="D"), {"agriculture": {"disponible": True, "rayon_m": 1000, "grandes_cultures": 55}}, S), "a_verifier") == {"grandes_cultures"}
    s2 = UserSettings()
    s2.eliminatoires.actif_agriculture = False
    assert evaluate(prop(), enr, s2) == []


def test_trip_time():
    assert codes(evaluate(prop(), {"route": {"duree_min": 200}}, S), "certaine") == {"trajet"}


def test_evaluate_all_updates_flags(db):
    p = Property(price=900000, surface=150, is_active=True)
    db.add(p)
    db.flush()
    assert evaluate_all(db, S)["eliminés"] == 1
    assert p.eliminated and p.elimination_reasons[0]["critere"] == "prix"
