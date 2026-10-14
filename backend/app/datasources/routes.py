"""Temps de route depuis votre adresse de départ.

- OSRM (OpenStreetMap, serveur public) : temps de base, sans circulation ;
- TomTom Routing (si TOMTOM_API_KEY est renseignée) : temps prévu un vendredi à l'heure de départ choisie,
  avec la circulation habituelle. Les résultats sont mémorisés par carré de ~1 km pour économiser les appels.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import env
from app.datasources.base import DataSource, register
from app.models import ApiUsage, Property
from app.settings_schema import UserSettings

OSRM = "https://router.project-osrm.org/route/v1/driving"
TOMTOM = "https://api.tomtom.com/routing/1/calculateRoute"
_cache: dict[tuple, dict] = {}


def next_friday(hhmm: str) -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    d = date.today()
    d += timedelta(days=(4 - d.weekday()) % 7 or 7)
    return datetime(d.year, d.month, d.day, h, m, tzinfo=ZoneInfo("Europe/Paris"))


def osrm_route(src: tuple[float, float], dst: tuple[float, float], client: httpx.Client) -> dict | None:
    url = f"{OSRM}/{src[1]},{src[0]};{dst[1]},{dst[0]}"
    for i in range(3):
        try:
            r = client.get(url, params={"overview": "false"}, timeout=30)
            if r.status_code == 200 and r.json().get("routes"):
                rt = r.json()["routes"][0]
                return {"duree_min": round(rt["duration"] / 60), "distance_km": round(rt["distance"] / 1000)}
            if r.status_code == 429:
                time.sleep(3 * (i + 1))
        except httpx.HTTPError:
            time.sleep(2 * (i + 1))
    return None


def tomtom_route(src, dst, depart: datetime, key: str, client: httpx.Client) -> dict | None:
    url = f"{TOMTOM}/{src[0]},{src[1]}:{dst[0]},{dst[1]}/json"
    try:
        r = client.get(url, params={"key": key, "departAt": depart.isoformat(timespec="seconds"), "traffic": "true", "routeType": "fastest"}, timeout=30)
        if r.status_code != 200:
            return None
        s = r.json()["routes"][0]["summary"]
        return {"duree_min": round(s["travelTimeInSeconds"] / 60), "retard_trafic_min": round(s.get("trafficDelayInSeconds", 0) / 60)}
    except (httpx.HTTPError, KeyError, IndexError):
        return None


@register
class RoutesSource(DataSource):
    key = "routes"
    name = "Temps de route (OSRM / OpenStreetMap, TomTom si clé)"
    url = "https://project-osrm.org/"
    licence = "ODbL (OpenStreetMap) ; TomTom selon contrat"
    refresh_cron = None
    enrich_keys = ("route",)
    ttl_days = 30

    def refresh(self, db: Session, settings: UserSettings) -> dict:
        _cache.clear()
        return {"rows": 0, "source_date": date.today().isoformat()}

    def enrich(self, db: Session, prop: Property, settings: UserSettings) -> dict[str, dict]:
        if prop.geom is None:
            return {}
        lat, lon = db.execute(select(func.ST_Y(Property.geom), func.ST_X(Property.geom)).where(Property.id == prop.id)).one()
        z = settings.zone
        src = (z.depart_lat, z.depart_lon)
        key = (round(lat, 2), round(lon, 2), z.depart_vendredi_heure)
        if key in _cache:
            return {"route": _cache[key]}
        client = httpx.Client(headers={"User-Agent": env.user_agent})
        base = osrm_route(src, (lat, lon), client)
        time.sleep(0.5)
        if not base:
            return {}
        out = {"base_min": base["duree_min"], "distance_km": base["distance_km"], "duree_min": base["duree_min"], "source_duree": "OSRM (sans circulation)"}
        if env.tomtom_api_key:
            tt = tomtom_route(src, (lat, lon), next_friday(z.depart_vendredi_heure), env.tomtom_api_key, client)
            if tt:
                db.add(ApiUsage(provider="tomtom", purpose="route vendredi soir", requests=1, cost_eur=0.0))
                out.update({"vendredi_soir_min": tt["duree_min"], "retard_trafic_min": tt["retard_trafic_min"], "duree_min": tt["duree_min"], "source_duree": "TomTom (circulation du vendredi soir)"})
        _cache[key] = out
        return {"route": out}
