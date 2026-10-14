"""Contours des communes et intercommunalités (Etalab, d'après Admin Express IGN)."""
from __future__ import annotations

import gzip
import json
from datetime import date
from email.utils import parsedate_to_datetime

from shapely.geometry import MultiPolygon, shape
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import env
from app.core.http import download_file
from app.datasources.base import DataSource, register
from app.settings_schema import UserSettings

BASE = "https://etalab-datasets.geo.data.gouv.fr/contours-administratifs/latest/geojson"


def _download(name: str) -> tuple[dict, str]:
    dest = env.public_data_dir / "contours" / name
    try:
        headers = download_file(f"{BASE}/{name}", dest)
        modified = headers.get("last-modified")
        when = parsedate_to_datetime(modified).date().isoformat() if modified else date.today().isoformat()
    except RuntimeError:
        if not dest.exists():
            raise
        # Le site ne répond pas : on réutilise la copie locale déjà téléchargée
        when = date.fromtimestamp(dest.stat().st_mtime).isoformat()
    return json.loads(gzip.decompress(dest.read_bytes())), when


def _multi(geom) -> MultiPolygon:
    g = shape(geom)
    return g if g.geom_type == "MultiPolygon" else MultiPolygon([g])


def update_zone_flags(db: Session, settings: UserSettings) -> int:
    """Recalcule quelles communes sont dans la zone (après un changement de réglages)."""
    db.execute(text("UPDATE commune SET in_zone = COALESCE(epci = ANY(:e), false)"), {"e": settings.zone.epci})
    n = db.execute(text("SELECT count(*) FROM commune WHERE in_zone")).scalar_one()
    db.commit()
    return n


@register
class CommunesSource(DataSource):
    key = "communes"
    name = "Contours des communes et EPCI (Etalab / IGN Admin Express)"
    url = "https://etalab-datasets.geo.data.gouv.fr/contours-administratifs/"
    refresh_cron = {"day": 1, "hour": 4}  # mensuel

    def refresh(self, db: Session, settings: UserSettings) -> dict:
        communes, when = _download("communes-100m.geojson.gz")
        epcis, _ = _download("epci-100m.geojson.gz")

        rows = []
        for f in communes["features"]:
            p = f["properties"]
            if p.get("departement", "").startswith("97") or not f.get("geometry"):
                continue
            g = _multi(f["geometry"])
            rows.append({
                "code": p["code"], "nom": p["nom"], "dep": p.get("departement"),
                "epci": p.get("epci"), "geom": g.wkt, "c": g.representative_point().wkt,
            })
        db.execute(
            text("""
            INSERT INTO commune (code, nom, departement, epci, in_zone, geom, centroid)
            VALUES (:code, :nom, :dep, :epci, false, ST_GeomFromText(:geom, 4326), ST_GeomFromText(:c, 4326))
            ON CONFLICT (code) DO UPDATE SET nom = EXCLUDED.nom, departement = EXCLUDED.departement,
              epci = EXCLUDED.epci, geom = EXCLUDED.geom, centroid = EXCLUDED.centroid
            """),
            rows,
        )
        erows = [
            {"code": f["properties"]["code"], "nom": f["properties"]["nom"], "geom": _multi(f["geometry"]).wkt}
            for f in epcis["features"] if f.get("geometry")
        ]
        db.execute(
            text("""
            INSERT INTO epci (code, nom, geom) VALUES (:code, :nom, ST_GeomFromText(:geom, 4326))
            ON CONFLICT (code) DO UPDATE SET nom = EXCLUDED.nom, geom = EXCLUDED.geom
            """),
            erows,
        )
        db.commit()
        in_zone = update_zone_flags(db, settings)
        return {"rows": len(rows), "epci": len(erows), "communes_zone": in_zone, "source_date": when}
