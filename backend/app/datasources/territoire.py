"""Données du territoire utilisées pour les critères éliminatoires et le calme / paysage.

- reseau  : routes importantes, voies ferrées en service, aérodromes (IGN BD TOPO) → distances (bruit) ;
- icpe    : installations classées (Géorisques) → élevages, méthaniseurs, éoliennes, industries ;
- rpg     : parcelles agricoles déclarées (RPG, IGN) → part de grandes cultures et de prairies autour du bien ;
- bocage  : haies et bâtiments voisins (IGN BD TOPO) → densité de haies, distance au voisin.

Tout est calculé à partir de la position du bien ; la précision de cette position (A–D) est prise en compte
par le moteur d'éliminatoires (services/eliminate.py), pas ici.
"""
from __future__ import annotations

import math
import time
from datetime import date

import httpx
from shapely.geometry import LineString, MultiLineString, Point, Polygon, shape
from shapely.ops import transform
from shapely.wkt import dumps as wkt_dumps
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import env
from app.core.wfs import wfs_features
from app.datasources.base import DataSource, register
from app.models import Property
from app.settings_schema import UserSettings

# --------------------------------------------------------------------------- outils


def zone_bbox(db: Session, margin: float = 0.05) -> tuple[float, float, float, float]:
    """(lat_min, lon_min, lat_max, lon_max) de la zone de recherche, avec une marge."""
    row = db.execute(text("SELECT ST_XMin(e), ST_YMin(e), ST_XMax(e), ST_YMax(e) FROM (SELECT ST_Extent(geom) e FROM commune WHERE in_zone) x")).one()
    if row[0] is None:
        raise RuntimeError("Aucune commune dans la zone : importez d'abord les communes")
    return (row[1] - margin, row[0] - margin, row[3] + margin, row[2] + margin)


def tiles(bbox: tuple[float, float, float, float], dlat: float = 0.12, dlon: float = 0.18):
    lat = bbox[0]
    while lat < bbox[2]:
        lon = bbox[1]
        while lon < bbox[3]:
            yield (round(lat, 5), round(lon, 5), round(min(lat + dlat, bbox[2]), 5), round(min(lon + dlon, bbox[3]), 5))
            lon += dlon
        lat += dlat


def lines_of(geometry: dict) -> list[LineString]:
    g = shape(geometry)
    parts = list(g.geoms) if isinstance(g, MultiLineString) else [g]
    from shapely import force_2d

    return [force_2d(p) for p in parts if isinstance(p, LineString) and not p.is_empty]


def point_of(db: Session, prop: Property) -> tuple[float, float] | None:
    if prop.geom is None:
        return None
    lat, lon = db.execute(select(func.ST_Y(Property.geom), func.ST_X(Property.geom)).where(Property.id == prop.id)).one()
    return lat, lon


def local_projection(lat0: float):
    kx, ky = 111_320 * math.cos(math.radians(lat0)), 110_574

    def fwd(x, y, z=None):
        return (x * kx, y * ky)

    return fwd


def circle(lat: float, lon: float, radius_m: float, n: int = 32) -> Polygon:
    kx, ky = 111_320 * math.cos(math.radians(lat)), 110_574
    return Polygon([(lon + radius_m * math.cos(2 * math.pi * i / n) / kx, lat + radius_m * math.sin(2 * math.pi * i / n) / ky) for i in range(n)])


# ------------------------------------------------------------------- réseau (bruit)


@register
class ReseauSource(DataSource):
    key = "reseau"
    name = "Routes, voies ferrées, aérodromes (IGN BD TOPO)"
    url = "https://geoservices.ign.fr/bdtopo"
    licence = "Licence Ouverte 2.0 (IGN)"
    refresh_cron = {"day": 15, "hour": 3}
    enrich_keys = ("bruit",)
    ttl_days = 60

    def refresh(self, db: Session, settings: UserSettings) -> dict:
        bbox = zone_bbox(db)
        client = httpx.Client(headers={"User-Agent": env.user_agent})
        n_road = n_rail = n_air = 0
        for t in tiles(bbox):
            rows = []
            for f in wfs_features("BDTOPO_V3:troncon_de_route", t, "importance IN ('1','2','3') AND etat_de_l_objet='En service'", client=client):
                p = f["properties"]
                for i, ln in enumerate(lines_of(f["geometry"])):
                    rows.append({"k": f"{p['cleabs']}#{i}", "n": p.get("nature"), "i": p.get("importance"), "l": p.get("nombre_de_voies"), "g": wkt_dumps(ln)})
            if rows:
                db.execute(text("""INSERT INTO terr_road (cleabs, nature, importance, lanes, geom) VALUES (:k,:n,:i,:l,ST_GeomFromText(:g,4326))
                                   ON CONFLICT (cleabs) DO UPDATE SET nature=EXCLUDED.nature, importance=EXCLUDED.importance, lanes=EXCLUDED.lanes, geom=EXCLUDED.geom"""), rows)
            n_road += len(rows)
            rows = []
            for f in wfs_features("BDTOPO_V3:troncon_de_voie_ferree", t, "etat_de_l_objet='En service'", client=client):
                p = f["properties"]
                for i, ln in enumerate(lines_of(f["geometry"])):
                    rows.append({"k": f"{p['cleabs']}#{i}", "n": p.get("nature"), "g": wkt_dumps(ln)})
            if rows:
                db.execute(text("""INSERT INTO terr_rail (cleabs, nature, geom) VALUES (:k,:n,ST_GeomFromText(:g,4326))
                                   ON CONFLICT (cleabs) DO UPDATE SET nature=EXCLUDED.nature, geom=EXCLUDED.geom"""), rows)
            n_rail += len(rows)
            db.commit()
        for f in wfs_features("BDTOPO_V3:aerodrome", bbox, client=client):
            p = f["properties"]
            from shapely import force_2d

            db.execute(text("""INSERT INTO terr_airfield (cleabs, name, nature, geom) VALUES (:k,:n,:t,ST_GeomFromText(:g,4326))
                               ON CONFLICT (cleabs) DO UPDATE SET name=EXCLUDED.name, nature=EXCLUDED.nature, geom=EXCLUDED.geom"""),
                       {"k": p["cleabs"], "n": p.get("toponyme"), "t": p.get("nature"), "g": wkt_dumps(force_2d(shape(f["geometry"])))})
            n_air += 1
        db.commit()
        return {"rows": n_road + n_rail + n_air, "routes": n_road, "voies_ferrees": n_rail, "aerodromes": n_air, "source_date": date.today().isoformat()}

    def enrich(self, db: Session, prop: Property, settings: UserSettings) -> dict[str, dict]:
        if prop.geom is None:
            return {}
        e = settings.eliminatoires
        # « route chargée » : pas de comptage de trafic ouvert sur toute la zone ; on utilise la hiérarchie des routes
        # de l'IGN (1-2 : liaisons entre villes et départements ; 3 : liaisons entre bourgs).
        classes = ("1", "2") if e.route_chargee_seuil_vehicules_jour >= 4000 else ("1", "2", "3")
        row = db.execute(text("""
            WITH p AS (SELECT geom FROM property WHERE id=:pid)
            SELECT
              (SELECT min(ST_Distance(r.geom::geography, p.geom::geography)) FROM terr_road r, p WHERE r.nature='Type autoroutier' AND r.geom && ST_Expand(p.geom, 0.1)),
              (SELECT min(ST_Distance(r.geom::geography, p.geom::geography)) FROM terr_road r, p WHERE r.importance = ANY(:cl) AND r.geom && ST_Expand(p.geom, 0.1)),
              (SELECT min(ST_Distance(r.geom::geography, p.geom::geography)) FROM terr_rail r, p WHERE r.geom && ST_Expand(p.geom, 0.1)),
              (SELECT min(ST_Distance(r.geom::geography, p.geom::geography)) FROM terr_airfield r, p WHERE r.geom && ST_Expand(p.geom, 0.1))
            """), {"pid": prop.id, "cl": list(classes)}).one()
        r = lambda v: None if v is None else int(round(v))  # noqa: E731
        return {"bruit": {
            "autoroute_m": r(row[0]), "route_chargee_m": r(row[1]), "voie_ferree_m": r(row[2]), "aerodrome_m": r(row[3]),
            "classes_route_chargee": list(classes), "lden_estime": None,
            "methode": "distances à vol d'oiseau ; routes chargées = routes d'importance 1-2 de l'IGN (pas de comptage de trafic) ; bruit en dB non estimé",
        }}


# --------------------------------------------------------------------------- ICPE

ELEVAGE_RUBRIQUES = ("2101", "2102", "2111", "2110", "2120", "2130", "2140", "2150", "2160", "3660")


def classify_icpe(rec: dict) -> tuple[list[str], list[str]]:
    rub = [str(r.get("numeroRubrique")) for r in (rec.get("rubriques") or [])]
    kinds: list[str] = []
    if any(r.startswith("2781") for r in rub):
        kinds.append("methaniseur")
    if rec.get("bovins") or rec.get("porcs") or rec.get("volailles") or any(r in ELEVAGE_RUBRIQUES for r in rub):
        kinds.append("elevage")
    if rec.get("eolienne") or any(r.startswith("2980") for r in rub):
        kinds.append("eolienne")
    if rec.get("carriere") or any(r.startswith("251") for r in rub):
        kinds.append("carriere")
    if rec.get("industrie") and not kinds:
        kinds.append("industrie")
    return kinds, rub


@register
class IcpeSource(DataSource):
    key = "icpe"
    name = "Installations classées (Géorisques / DREAL)"
    url = "https://www.georisques.gouv.fr/donnees/bases-de-donnees/installations-industrielles"
    licence = "Licence Ouverte 2.0"
    refresh_cron = {"day_of_week": "sun", "hour": 5}
    enrich_keys = ("elevage",)
    ttl_days = 30

    def refresh(self, db: Session, settings: UserSettings) -> dict:
        deps = [r[0] for r in db.execute(text("SELECT DISTINCT departement FROM commune WHERE in_zone"))]
        client = httpx.Client(headers={"User-Agent": env.user_agent}, timeout=60)
        total = 0
        for dep in deps:
            page = 1
            while True:
                data = None
                for i in range(4):
                    try:
                        r = client.get("https://georisques.gouv.fr/api/v1/installations_classees", params={"departement": dep, "page": page, "page_size": 100})
                        if r.status_code == 200:
                            data = r.json()
                            break
                    except (httpx.HTTPError, ValueError):
                        pass
                    time.sleep(2 * (i + 1))
                if data is None:
                    raise RuntimeError(f"Géorisques indisponible (département {dep}, page {page})")
                rows = []
                for rec in data.get("data", []):
                    if rec.get("longitude") is None or rec.get("latitude") is None:
                        continue
                    if "fin d'exploitation" in (rec.get("etatActivite") or "").lower() or "cessation" in (rec.get("etatActivite") or "").lower():
                        continue
                    kinds, rub = classify_icpe(rec)
                    rows.append({"c": rec["codeAIOT"], "n": rec.get("raisonSociale"), "v": rec.get("commune"), "r": rec.get("regime"),
                                 "a": rec.get("etatActivite"), "k": kinds, "u": rub, "g": f"SRID=4326;POINT({rec['longitude']} {rec['latitude']})"})
                if rows:
                    db.execute(text("""INSERT INTO icpe_site (code, name, commune, regime, activity, kinds, rubriques, geom)
                                       VALUES (:c,:n,:v,:r,:a,:k,:u,ST_GeomFromEWKT(:g))
                                       ON CONFLICT (code) DO UPDATE SET name=EXCLUDED.name, regime=EXCLUDED.regime, activity=EXCLUDED.activity,
                                         kinds=EXCLUDED.kinds, rubriques=EXCLUDED.rubriques, geom=EXCLUDED.geom"""), rows)
                    db.commit()
                total += len(rows)
                if page >= (data.get("total_pages") or 1):
                    break
                page += 1
                time.sleep(0.2)
        return {"rows": total, "source_date": date.today().isoformat()}

    def enrich(self, db: Session, prop: Property, settings: UserSettings) -> dict[str, dict]:
        if prop.geom is None:
            return {}
        rows = db.execute(text("""
            WITH p AS (SELECT geom FROM property WHERE id=:pid)
            SELECT s.code, s.name, s.regime, s.kinds, ST_Distance(s.geom::geography, p.geom::geography) AS d,
                   degrees(ST_Azimuth(p.geom, s.geom)) AS az
            FROM icpe_site s, p WHERE s.geom && ST_Expand(p.geom, 0.1) AND s.kinds <> '{}'
            ORDER BY d LIMIT 60"""), {"pid": prop.id}).all()

        def pack(kind: str):
            out = []
            for r in rows:
                if kind in r.kinds:
                    west = 190 <= (r.az or 0) <= 310  # vents dominants d'ouest : un site à l'ouest souffle vers le bien
                    out.append({"nom": r.name, "regime": r.regime, "distance_m": int(r.d), "distance_ponderee_m": int(r.d / 1.5) if west else int(r.d), "au_vent": west})
            return out[:5]

        return {"elevage": {
            "elevages": pack("elevage"), "methaniseurs": pack("methaniseur"), "eoliennes": pack("eolienne"), "carrieres": pack("carriere"),
            "methode": "installations classées déclarées (élevages soumis à enregistrement/autorisation) ; les petits élevages non classés n'y figurent pas",
        }}


# --------------------------------------------------------------------------- RPG

GRANDES_CULTURES = {"1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "15", "24"}
PRAIRIES = {"16", "17", "18", "19"}
VERGERS = {"20", "22", "23", "27"}
RPG_URL = "https://apicarto.ign.fr/api/rpg/v2"


def rpg_shares(features: list[dict], lat: float, lon: float, radius_m: float) -> dict:
    fwd = local_projection(lat)
    disc = transform(fwd, circle(lat, lon, radius_m, 64))
    area = disc.area
    acc = {"grandes_cultures": 0.0, "prairies": 0.0, "vergers": 0.0, "autres": 0.0}
    for f in features:
        try:
            g = transform(fwd, shape(f["geometry"]))
            a = g.intersection(disc).area if g.intersects(disc) else 0.0
        except Exception:  # noqa: BLE001
            continue
        grp = str(f["properties"].get("code_group"))
        key = "grandes_cultures" if grp in GRANDES_CULTURES else "prairies" if grp in PRAIRIES else "vergers" if grp in VERGERS else "autres"
        acc[key] += a
    pct = {k: round(100 * v / area, 1) for k, v in acc.items()}
    pct["non_declare"] = round(max(0.0, 100 - sum(pct.values())), 1)
    return pct


@register
class RpgSource(DataSource):
    key = "rpg"
    name = "Registre parcellaire graphique (RPG, IGN / ASP)"
    url = "https://geoservices.ign.fr/rpg"
    licence = "Licence Ouverte 2.0"
    refresh_cron = None
    enrich_keys = ("agriculture",)
    ttl_days = 180

    def refresh(self, db: Session, settings: UserSettings) -> dict:
        return {"rows": 0, "source_date": "RPG 2024"}

    def fetch(self, lat: float, lon: float, radius_m: float, client: httpx.Client) -> tuple[list[dict], int] | None:
        import json

        poly = circle(lat, lon, radius_m, 24)
        geom = json.dumps({"type": "Polygon", "coordinates": [[list(c) for c in poly.exterior.coords]]})
        for year in (2024, 2023, 2022):
            feats: list[dict] = []
            start = 0
            ok = False
            while True:
                data = None
                for i in range(3):
                    try:
                        r = client.get(RPG_URL, params={"annee": year, "geom": geom, "_start": start, "_limit": 500}, timeout=60)
                        if r.status_code == 200:
                            data = r.json()
                            break
                    except (httpx.HTTPError, ValueError):
                        pass
                    time.sleep(2 * (i + 1))
                if data is None:
                    break
                ok = True
                batch = data.get("features", [])
                feats += batch
                if len(batch) < 500:
                    break
                start += 500
            if ok and feats:
                return feats, year
        return None

    def enrich(self, db: Session, prop: Property, settings: UserSettings) -> dict[str, dict]:
        pt = point_of(db, prop)
        if not pt:
            return {}
        radius = settings.eliminatoires.grandes_cultures_rayon_m
        client = httpx.Client(headers={"User-Agent": env.user_agent})
        res = self.fetch(pt[0], pt[1], radius, client)
        time.sleep(0.3)
        if not res:
            return {"agriculture": {"disponible": False, "rayon_m": radius}}
        feats, year = res
        return {"agriculture": {"disponible": True, "rayon_m": radius, "annee_rpg": year, **rpg_shares(feats, pt[0], pt[1], radius)}}


# ------------------------------------------------------------------ haies et voisinage


@register
class BocageSource(DataSource):
    key = "bocage"
    name = "Haies et bâtiments voisins (IGN BD TOPO)"
    url = "https://geoservices.ign.fr/bdtopo"
    licence = "Licence Ouverte 2.0 (IGN)"
    refresh_cron = None
    enrich_keys = ("bocage",)
    ttl_days = 180

    def refresh(self, db: Session, settings: UserSettings) -> dict:
        return {"rows": 0, "source_date": "BD TOPO (continu)"}

    def enrich(self, db: Session, prop: Property, settings: UserSettings) -> dict[str, dict]:
        pt = point_of(db, prop)
        if not pt or prop.geo_confidence == "D":
            return {"bocage": {"disponible": False, "raison": "position trop imprécise (centre de commune)"}}
        lat, lon = pt
        radius = 500
        dlat, dlon = radius / 110_574, radius / (111_320 * math.cos(math.radians(lat)))
        bbox = (lat - dlat, lon - dlon, lat + dlat, lon + dlon)
        client = httpx.Client(headers={"User-Agent": env.user_agent})
        fwd = local_projection(lat)
        disc = transform(fwd, circle(lat, lon, radius, 48))
        centre = transform(fwd, Point(lon, lat))
        hedge_m = 0.0
        for f in wfs_features("BDTOPO_V3:haie", bbox, client=client):
            from shapely import force_2d

            g = transform(fwd, force_2d(shape(f["geometry"])))
            hedge_m += g.intersection(disc).length
        buildings = []
        for f in wfs_features("BDTOPO_V3:batiment", bbox, "etat_de_l_objet='En service'", client=client):
            from shapely import force_2d

            g = transform(fwd, force_2d(shape(f["geometry"])))
            if g.area >= 25:  # on ignore les abris et appentis
                buildings.append((centre.distance(g), g))
        buildings.sort(key=lambda x: x[0])
        voisin = None
        if buildings:
            own = buildings[0][1]
            others = [d for d, g in buildings[1:] if own.distance(g) > 30]  # hors dépendances de la même parcelle
            voisin = int(min(others)) if others else None
        area_ha = disc.area / 10_000
        return {"bocage": {
            "disponible": True, "rayon_m": radius, "haies_m": int(hedge_m), "haies_m_par_ha": round(hedge_m / area_ha, 1),
            "batiments_250m": sum(1 for d, _ in buildings if d <= 250), "voisin_le_plus_proche_m": voisin,
            "methode": "bâtiments de plus de 25 m² hors dépendances à moins de 30 m du bâtiment principal ; indicatif",
        }}
