"""Critères éliminatoires : un bien est écarté (mais reste consultable) s'il enfreint un de vos seuils.

Honnêteté sur la précision : la position d'un bien est plus ou moins sûre (niveau A à D). Un bien n'est
« éliminé » que si la règle est enfreinte **même dans le cas le plus favorable** (distance + incertitude de
position < seuil). Si elle n'est enfreinte que dans le pire cas, le bien reste visible avec un avertissement
« à vérifier ». Les données manquantes ne suffisent jamais à éliminer.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Enrichment, Property
from app.settings_schema import UserSettings

INCERTITUDE_M = {"A": 15, "B": 40, "C": 600, "D": 2500}  # rayon d'incertitude de la position selon son niveau
RECENT_AVANT_AN = 2000


def _dist_rule(reasons: list, critere: str, label: str, d: float | None, seuil: float, unc: float, unite: str = "m") -> None:
    if d is None or seuil <= 0:
        return
    if d + unc < seuil:
        reasons.append({"critere": critere, "raison": f"{label} : {int(d)} {unite} (seuil {int(seuil)} {unite})", "valeur": d, "seuil": seuil, "certitude": "certaine"})
    elif d - unc < seuil:
        reasons.append({"critere": critere, "raison": f"{label} : à vérifier, environ {int(d)} {unite} (seuil {int(seuil)} {unite}, position {'approximative' if unc > 100 else 'à confirmer'})",
                        "valeur": d, "seuil": seuil, "certitude": "a_verifier"})


def evaluate(prop: Property, enr: dict[str, dict], settings: UserSettings) -> list[dict]:
    c, e, z = settings.criteres, settings.eliminatoires, settings.zone
    reasons: list[dict] = []
    unc = INCERTITUDE_M.get(prop.geo_confidence or "D", 2500)

    def hard(critere: str, raison: str, valeur, seuil) -> None:
        reasons.append({"critere": critere, "raison": raison, "valeur": valeur, "seuil": seuil, "certitude": "certaine"})

    # --- vos critères
    if prop.price and prop.price > c.prix_max_eur:
        hard("prix", f"Prix {prop.price:,} € > {c.prix_max_eur:,} €".replace(",", " "), prop.price, c.prix_max_eur)
    if prop.surface and prop.surface < c.surface_min_m2:
        hard("surface", f"Surface {prop.surface:g} m² < {c.surface_min_m2} m²", prop.surface, c.surface_min_m2)
    if prop.surface and prop.surface > c.surface_max_m2:
        hard("surface", f"Surface {prop.surface:g} m² > {c.surface_max_m2} m² (trop grand à entretenir)", prop.surface, c.surface_max_m2)
    if prop.bedrooms is not None and prop.bedrooms < c.chambres_min:
        hard("chambres", f"{prop.bedrooms} chambre(s) < {c.chambres_min}", prop.bedrooms, c.chambres_min)
    if prop.land and prop.land < c.terrain_min_m2:
        hard("terrain", f"Terrain {int(prop.land)} m² < {c.terrain_min_m2} m²", prop.land, c.terrain_min_m2)
    if "construction récente" in c.types_exclus and prop.year_built and prop.year_built >= RECENT_AVANT_AN:
        hard("type", f"Construction récente ({prop.year_built})", prop.year_built, RECENT_AVANT_AN)

    # --- trajet
    route = (enr.get("route") or {})
    if route.get("duree_min") and route["duree_min"] > z.temps_route_max_min:
        hard("trajet", f"Trajet {route['duree_min']} min > {z.temps_route_max_min} min", route["duree_min"], z.temps_route_max_min)

    # --- bruit
    if e.actif_bruit:
        b = enr.get("bruit") or {}
        _dist_rule(reasons, "autoroute", "Autoroute / voie rapide proche", b.get("autoroute_m"), e.autoroute_m, unc)
        _dist_rule(reasons, "route_chargee", "Route importante proche", b.get("route_chargee_m"), e.route_chargee_m, unc)
        _dist_rule(reasons, "voie_ferree", "Voie ferrée en service proche", b.get("voie_ferree_m"), e.voie_ferree_m, unc)
        _dist_rule(reasons, "aerodrome", "Aérodrome proche", b.get("aerodrome_m"), e.aerodrome_m, unc)

    # --- agriculture
    if e.actif_agriculture:
        el = enr.get("elevage") or {}
        key = "distance_ponderee_m" if e.ponderer_vent_dominant else "distance_m"
        for site in el.get("elevages", [])[:3]:
            _dist_rule(reasons, "elevage", f"Élevage classé ({site['nom']})", site[key], e.elevage_intensif_m, unc)
        for site in el.get("methaniseurs", [])[:2]:
            _dist_rule(reasons, "methaniseur", f"Méthaniseur ({site['nom']})", site["distance_m"], e.methaniseur_m, unc)
        ag = enr.get("agriculture") or {}
        if ag.get("disponible") and ag.get("grandes_cultures") is not None and ag["grandes_cultures"] > e.grandes_cultures_max_pct:
            pct = ag["grandes_cultures"]
            sure = unc <= 100 or pct > e.grandes_cultures_max_pct + 15
            reasons.append({"critere": "grandes_cultures", "raison": f"Grandes cultures : {pct:g} % dans {ag['rayon_m']} m (seuil {e.grandes_cultures_max_pct} %)",
                            "valeur": pct, "seuil": e.grandes_cultures_max_pct, "certitude": "certaine" if sure else "a_verifier"})

    # --- voisinage
    bo = enr.get("bocage") or {}
    v = bo.get("voisin_le_plus_proche_m")
    if bo.get("disponible") and v is not None and c.distance_voisin_min_m > 0:
        _dist_rule(reasons, "voisin", "Voisin proche", v, c.distance_voisin_min_m, 15 if prop.geo_confidence == "A" else 40)
    return reasons


def evaluate_all(db: Session, settings: UserSettings) -> dict:
    enrs: dict[int, dict] = {}
    for en in db.scalars(select(Enrichment)):
        enrs.setdefault(en.property_id, {})[en.key] = en.value
    stats = {"eliminés": 0, "a_verifier": 0, "ok": 0}
    for prop in db.scalars(select(Property).where(Property.is_active.is_(True))):
        reasons = evaluate(prop, enrs.get(prop.id, {}), settings)
        prop.elimination_reasons = reasons
        prop.eliminated = any(r["certitude"] == "certaine" for r in reasons)
        stats["eliminés" if prop.eliminated else "a_verifier" if reasons else "ok"] += 1
    db.commit()
    return stats
