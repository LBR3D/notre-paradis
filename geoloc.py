"""Localisation d'un bien, avec un niveau de confiance.

A  adresse exacte (numéro + rue) trouvée dans la Base Adresse Nationale ;
B  un seul diagnostic énergétique (base ADEME) correspond (commune, maison, surface, lettre DPE, période de
   construction), ou un seul est proche des coordonnées approximatives de l'annonce — on prend son adresse ;
C  coordonnées approximatives données par l'annonce (souvent floutées), vérifiées dans la commune ;
D  centre de la commune.

Les autres hypothèses (plusieurs DPE possibles) sont gardées dans `geo_candidates` pour affichage.
"""
from __future__ import annotations

import logging
import re
import time

import httpx
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import env
from app.models import Property

log = logging.getLogger("geoloc")
BAN = "https://data.geopf.fr/geocodage/search/"
ADEME = "https://data.ademe.fr/data-fair/api/v1/datasets/dpe03existant/lines"


def _get(client: httpx.Client, url: str, params: dict, tries: int = 3) -> dict | None:
    for i in range(tries):
        try:
            r = client.get(url, params=params, timeout=30)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 502, 503):
                time.sleep(2 * (i + 1))
                continue
            return None
        except httpx.HTTPError:
            time.sleep(1.5 * (i + 1))
    return None


def _periode_ok(year: int | None, periode: str | None) -> bool:
    """Compatibilité entre l'année de construction annoncée et la période du DPE."""
    if not year or not periode:
        return True
    m = re.match(r"(?:avant\s*)?(\d{4})(?:\s*-\s*(\d{4}))?", periode.strip().lower())
    if "avant" in periode.lower() and m:
        return year <= int(m.group(1)) + 3
    if m and m.group(2):
        return int(m.group(1)) - 3 <= year <= int(m.group(2)) + 3
    if "après" in periode.lower() or "apres" in periode.lower():
        mm = re.search(r"(\d{4})", periode)
        return bool(mm) and year >= int(mm.group(1)) - 3
    return True


def ban_exact(client: httpx.Client, address: str, postal: str | None, commune_code: str | None) -> dict | None:
    if not address or not re.search(r"\d", address):
        return None
    q = f"{address} {postal or ''}".strip()
    data = _get(client, BAN, {"q": q, "limit": 1, **({"citycode": commune_code} if commune_code else {})})
    if not data or not data.get("features"):
        return None
    f = data["features"][0]
    pr = f["properties"]
    if pr.get("type") == "housenumber" and pr.get("score", 0) >= 0.75 and (not commune_code or pr.get("citycode") == commune_code):
        lon, lat = f["geometry"]["coordinates"]
        return {"lat": lat, "lon": lon, "label": pr.get("label")}
    return None


def dpe_candidates(client: httpx.Client, postal: str | None, surface: float | None, dpe: str | None, year: int | None, commune_code: str | None) -> list[dict]:
    if not postal or not surface:
        return []
    tol = max(1.0, surface * 0.015)
    params: dict = {
        "q": postal, "q_fields": "code_postal_ban", "type_batiment_in": "maison", "size": 30,
        "surface_habitable_logement_gte": round(surface - tol, 1), "surface_habitable_logement_lte": round(surface + tol, 1),
        "select": "adresse_ban,_geopoint,etiquette_dpe,surface_habitable_logement,periode_construction,code_insee_ban,date_etablissement_dpe,score_ban",
    }
    if dpe:
        params["etiquette_dpe_in"] = dpe
    # (le paramètre « qs » de l'API est bloqué par le pare-feu de l'ADEME : on utilise les filtres par champ)
    data = _get(client, ADEME, params)
    out = []
    seen = set()
    for r in (data or {}).get("results", []):
        if commune_code and r.get("code_insee_ban") and r["code_insee_ban"] != commune_code:
            continue
        if not _periode_ok(year, r.get("periode_construction")) or not r.get("_geopoint"):
            continue
        key = (r["adresse_ban"], r.get("surface_habitable_logement"))
        if key in seen:
            continue
        seen.add(key)
        lat, lon = (float(x) for x in r["_geopoint"].split(","))
        out.append({"lat": lat, "lon": lon, "adresse": r["adresse_ban"], "surface": r.get("surface_habitable_logement"), "dpe": r.get("etiquette_dpe"), "date": r.get("date_etablissement_dpe")})
    return out


def _km(a: tuple[float, float], b: tuple[float, float]) -> float:
    from math import asin, cos, radians, sin, sqrt

    dlat, dlon = radians(b[0] - a[0]), radians(b[1] - a[1])
    h = sin(dlat / 2) ** 2 + cos(radians(a[0])) * cos(radians(b[0])) * sin(dlon / 2) ** 2
    return 2 * 6371 * asin(sqrt(h))


def _wkt(lat: float, lon: float) -> str:
    return f"SRID=4326;POINT({lon} {lat})"


def locate_property(db: Session, prop: Property, client: httpx.Client) -> str:
    items = [x for x in prop.listings if x.status == "active"] or list(prop.listings)
    if not items:
        return "?"
    commune = prop.commune_code
    postal = next((x.postal_code for x in items if x.postal_code), None)
    candidates: list[dict] = []

    # A — adresse
    for li in items:
        if li.address:
            hit = ban_exact(client, li.address, li.postal_code or postal, commune)
            if hit:
                return _save(db, prop, hit["lat"], hit["lon"], "A", "adresse (BAN)", [hit])

    # B — DPE
    surface = prop.surface
    dpe = next((x.dpe for x in items if x.dpe), None)
    cands = dpe_candidates(client, postal, surface, dpe, prop.year_built, commune)
    candidates = cands[:8]
    if len(cands) == 1:
        c = cands[0]
        return _save(db, prop, c["lat"], c["lon"], "B", "DPE unique (ADEME)", candidates)

    # B (bis) — plusieurs DPE possibles, mais un seul proche des coordonnées approximatives de l'annonce
    approx = next(((li.lat, li.lon) for li in items if li.lat and li.lon), None)
    if approx and len(cands) > 1:
        near = [c for c in cands if _km(approx, (c["lat"], c["lon"])) <= 1.2]
        if len(near) == 1:
            c = near[0]
            return _save(db, prop, c["lat"], c["lon"], "B", "DPE + coordonnées de l'annonce concordants", candidates)

    # C — coordonnées de l'annonce, si elles sont dans/près de la commune
    for li in items:
        if li.lat and li.lon and commune:
            ok = db.scalar(
                text("SELECT ST_DWithin(geom::geography, ST_SetSRID(ST_MakePoint(:lon,:lat),4326)::geography, 1500) FROM commune WHERE code=:c"),
                {"lon": li.lon, "lat": li.lat, "c": commune},
            )
            if ok:
                return _save(db, prop, li.lat, li.lon, "C", "coordonnées de l'annonce (approximatives)", candidates)

    # D — centre de la commune
    if commune:
        row = db.execute(text("SELECT ST_Y(centroid), ST_X(centroid) FROM commune WHERE code=:c"), {"c": commune}).first()
        if row and row[0] is not None:
            return _save(db, prop, row[0], row[1], "D", "centre de la commune", candidates)
    return "?"


def _save(db: Session, prop: Property, lat: float, lon: float, conf: str, method: str, candidates: list) -> str:
    prop.geom = _wkt(lat, lon)
    prop.geo_confidence = conf
    prop.geo_method = method
    prop.geo_candidates = candidates
    return conf


def geolocate_all(db: Session, only_missing: bool = True, limit: int = 500) -> dict:
    client = httpx.Client(headers={"User-Agent": env.user_agent})
    q = select(Property).where(Property.is_active.is_(True))
    if only_missing:
        q = q.where(Property.geo_method.is_(None))
    stats: dict[str, int] = {}
    for prop in db.scalars(q.limit(limit)).all():
        try:
            c = locate_property(db, prop, client)
        except Exception as e:  # noqa: BLE001
            log.warning("géolocalisation %s : %s", prop.id, e)
            db.rollback()
            c = "erreur"
        stats[c] = stats.get(c, 0) + 1
        db.commit()
        time.sleep(0.15)
    return stats
