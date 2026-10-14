"""Accès à la Géoplateforme IGN (WFS) : téléchargement par carrés et requêtes ponctuelles."""
from __future__ import annotations

import time
from collections.abc import Iterator

import httpx

from app.core.config import env

WFS = "https://data.geopf.fr/wfs/ows"


def _get(client: httpx.Client, params: dict, tries: int = 4) -> dict | None:
    for i in range(tries):
        try:
            r = client.get(WFS, params=params, timeout=90)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(3 * (i + 1))
                continue
            return None
        except (httpx.HTTPError, ValueError):
            time.sleep(2 * (i + 1))
    return None


def wfs_features(typename: str, bbox: tuple[float, float, float, float], cql: str | None = None, page: int = 1000, client: httpx.Client | None = None) -> Iterator[dict]:
    """Entités d'une couche dans un rectangle (lat_min, lon_min, lat_max, lon_max), avec pagination.

    Ordre des axes : latitude puis longitude (EPSG:4326 en WFS 2.0). Les rectangles (BBOX) sont rapides,
    contrairement aux filtres de distance (DWITHIN) qui expirent sur les grosses couches.
    """
    client = client or httpx.Client(headers={"User-Agent": env.user_agent})
    flt = "BBOX(geometrie,{},{},{},{})".format(*bbox) + (f" AND {cql}" if cql else "")
    start = 0
    while True:
        data = _get(client, {
            "SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature", "OUTPUTFORMAT": "application/json", "SRSNAME": "EPSG:4326",
            "TYPENAMES": typename, "COUNT": page, "STARTINDEX": start, "SORTBY": "cleabs", "CQL_FILTER": flt,
        }, )
        if data is None:
            raise RuntimeError(f"WFS indisponible pour {typename} {bbox}")
        feats = data.get("features", [])
        yield from feats
        if len(feats) < page:
            return
        start += page
        time.sleep(0.2)
