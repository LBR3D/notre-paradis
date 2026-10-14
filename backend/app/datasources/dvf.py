"""Demandes de valeurs foncières (DVF) — prix réels des ventes de maisons (Etalab, data.gouv.fr).

Sert à situer le prix demandé par rapport au marché local : prix au m² médian des ventes comparables
(même secteur, surface proche, 3 dernières années) et écart du bien avec cette estimation.
"""
from __future__ import annotations

import csv
import gzip
import io
from collections import defaultdict
from datetime import date, timedelta
from statistics import median

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import env
from app.core.http import download_file
from app.datasources.base import DataSource, register
from app.models import Property
from app.settings_schema import UserSettings

BASE = "https://files.data.gouv.fr/geo-dvf/latest/csv"
YEARS = (2022, 2023, 2024, 2025)


def parse_dvf(raw_gz: bytes) -> list[dict]:
    """Une ligne par vente de maison (une seule maison dans la vente, valeur cohérente)."""
    rows = csv.DictReader(io.StringIO(gzip.decompress(raw_gz).decode("utf8")))
    by_mut: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r.get("nature_mutation") == "Vente":
            by_mut[r["id_mutation"]].append(r)
    out = []
    for mid, lines in by_mut.items():
        houses = [x for x in lines if x.get("type_local") == "Maison"]
        if len(houses) != 1:
            continue
        if any(x.get("type_local") in ("Appartement", "Local industriel. commercial ou assimilé") for x in lines):
            continue
        h = houses[0]
        try:
            price = int(float(h["valeur_fonciere"]))
            surface = float(h["surface_reelle_bati"]) if h.get("surface_reelle_bati") else None
        except (ValueError, KeyError):
            continue
        parcels: dict[str, float] = {}
        for x in lines:
            if x.get("surface_terrain"):
                parcels[x.get("id_parcelle", "")] = float(x["surface_terrain"])
        lat, lon = h.get("latitude"), h.get("longitude")
        out.append({
            "id": mid, "date": h["date_mutation"], "price": price, "commune": h["code_commune"], "surface": surface,
            "land": sum(parcels.values()) or None, "rooms": int(h["nombre_pieces_principales"]) if h.get("nombre_pieces_principales") else None,
            "address": " ".join(p for p in (h.get("adresse_numero"), h.get("adresse_nom_voie"), h.get("code_postal"), h.get("nom_commune")) if p),
            "lon": float(lon) if lon else None, "lat": float(lat) if lat else None,
        })
    return out


@register
class DvfSource(DataSource):
    key = "dvf"
    name = "Demandes de valeurs foncières (DVF, DGFiP via Etalab)"
    url = "https://www.data.gouv.fr/fr/datasets/demandes-de-valeurs-foncieres-geolocalisees/"
    refresh_cron = {"day_of_week": "mon", "hour": 3}
    enrich_keys = ("dvf",)

    def refresh(self, db: Session, settings: UserSettings) -> dict:
        deps = [r[0] for r in db.execute(text("SELECT DISTINCT departement FROM commune WHERE in_zone"))]
        total = 0
        latest = ""
        for dep in deps:
            for year in YEARS:
                dest = env.public_data_dir / "dvf" / f"{year}-{dep}.csv.gz"
                try:
                    download_file(f"{BASE}/{year}/departements/{dep}.csv.gz", dest, retries=3)
                except RuntimeError:
                    if not dest.exists():
                        continue
                sales = parse_dvf(dest.read_bytes())
                rows = [
                    {"id": s["id"], "d": s["date"], "p": s["price"], "c": s["commune"], "s": s["surface"], "l": s["land"], "r": s["rooms"],
                     "a": s["address"], "w": f"SRID=4326;POINT({s['lon']} {s['lat']})" if s["lon"] and s["lat"] else None}
                    for s in sales
                ]
                if rows:
                    db.execute(
                        text("""INSERT INTO dvf_sale (id_mutation, sold_on, price, commune_code, surface, land, rooms, address, geom)
                                VALUES (:id, :d, :p, :c, :s, :l, :r, :a, ST_GeomFromEWKT(:w))
                                ON CONFLICT (id_mutation) DO UPDATE SET price=EXCLUDED.price, surface=EXCLUDED.surface, land=EXCLUDED.land,
                                  rooms=EXCLUDED.rooms, address=EXCLUDED.address, geom=EXCLUDED.geom"""),
                        rows,
                    )
                    db.commit()
                total += len(rows)
                latest = max([latest] + [s["date"] for s in sales])
        return {"rows": total, "source_date": latest or None}

    def enrich(self, db: Session, prop: Property, settings: UserSettings) -> dict[str, dict]:
        if not prop.price or not prop.surface or not (prop.commune_code or prop.geom is not None):
            return {}
        since = date.today() - timedelta(days=3 * 365)
        lo, hi = prop.surface * 0.7, prop.surface * 1.4
        comps: list = []
        used = None
        for radius_km in (0, 5, 10, 20):
            if radius_km == 0:
                if not prop.commune_code:
                    continue
                where, params = "commune_code = :c", {"c": prop.commune_code}
                dist = "NULL"
            else:
                if prop.geom is None:
                    break
                where = "ST_DWithin(geom::geography, (SELECT geom::geography FROM property WHERE id=:pid), :rad)"
                params = {"pid": prop.id, "rad": radius_km * 1000}
                dist = "ST_Distance(geom::geography, (SELECT geom::geography FROM property WHERE id=:pid))"
            comps = db.execute(
                text(f"""SELECT id_mutation, sold_on, price, surface, land, address, {dist} AS d FROM dvf_sale
                         WHERE {where} AND sold_on >= :since AND surface BETWEEN :lo AND :hi AND price BETWEEN 20000 AND 3000000
                         ORDER BY d NULLS FIRST, sold_on DESC LIMIT 60"""),
                {**params, "since": since, "lo": lo, "hi": hi},
            ).all()
            used = radius_km
            if len(comps) >= 6:
                break
        if len(comps) < 3:
            return {"dvf": {"n": len(comps), "message": "Pas assez de ventes comparables dans le secteur"}}
        m2 = [c.price / c.surface for c in comps]
        med = median(m2)
        estimate = round(med * prop.surface, -3)
        gap = (prop.price - estimate) / estimate
        return {"dvf": {
            "n": len(comps), "rayon_km": used or "commune", "prix_m2_median": round(med),
            "estimation": int(estimate), "ecart_pct": round(gap * 100, 1),
            "marge_negociation": int(max(0, prop.price - estimate)),
            "periode": f"{since.isoformat()} → aujourd'hui",
            "ventes": [{"date": c.sold_on.isoformat(), "prix": c.price, "surface": c.surface, "terrain": c.land, "adresse": c.address} for c in comps[:6]],
        }}
