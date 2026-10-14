"""Découverte des agences immobilières et études notariales de la zone (base Sirene).

Source : API « Recherche d'entreprises » (data.gouv.fr, Licence Ouverte). Codes NAF :
68.31Z agences immobilières, 69.10Z activités juridiques (notaires, repérés par leur nom).
Les agences trouvées alimentent la table `agency` ; leur site web sera renseigné ensuite
(manuellement ou par recherche) pour créer les sources de collecte.
"""
from __future__ import annotations

import re
import time

import httpx
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import env
from app.models import Agency

API = "https://recherche-entreprises.api.gouv.fr/search"
NETWORKS = [
    ("orpi", "Orpi"), ("century 21", "Century 21"), ("century21", "Century 21"), ("laforet", "Laforêt"), ("laforêt", "Laforêt"),
    ("guy hoquet", "Guy Hoquet"), ("stephane plaza", "Stéphane Plaza"), ("stéphane plaza", "Stéphane Plaza"), ("iad", "iad"),
    ("safti", "Safti"), ("capifrance", "Capifrance"), ("nestenn", "Nestenn"), ("foncia", "Foncia"), ("l'adresse", "L'Adresse"),
    ("era immobilier", "ERA"), ("immo de france", "Immo de France"), ("sextant", "Sextant"), ("barnes", "Barnes"),
]


def guess_network(name: str) -> str | None:
    n = name.lower()
    for key, label in NETWORKS:
        if re.search(rf"(?<![a-z]){re.escape(key)}(?![a-z])", n):
            return label
    return None


def _kind(naf: str, name: str) -> str | None:
    if naf == "68.31Z":
        return "agence"
    if naf == "69.10Z" and re.search(r"notair|notaire|office notarial|\bscp\b.*not", name, re.I):
        return "notaire"
    return None


def _get(client: httpx.Client, params: dict, tries: int = 4) -> httpx.Response | None:
    for i in range(tries):
        try:
            return client.get(API, params=params)
        except httpx.HTTPError:
            time.sleep(2 * (i + 1))
    return None


def discover_agencies(db: Session, client: httpx.Client | None = None, pause: float = 0.2) -> dict:
    client = client or httpx.Client(timeout=30, headers={"User-Agent": env.user_agent})
    codes = [r[0] for r in db.execute(text("SELECT code FROM commune WHERE in_zone"))]
    stats = {"communes": len(codes), "trouvees": 0, "nouvelles": 0}
    known = {a.siret for a in db.scalars(select(Agency)) if a.siret}
    for code in codes:
        for naf in ("68.31Z", "69.10Z"):
            page = 1
            while True:
                r = _get(client, {"activite_principale": naf, "code_commune": code, "etat_administratif": "A", "per_page": 25, "page": page})
                time.sleep(pause)
                if r is None:
                    break
                if r.status_code == 429:
                    time.sleep(5)
                    continue
                if r.status_code != 200:
                    break
                data = r.json()
                for company in data.get("results", []):
                    name = company.get("nom_complet") or ""
                    for et in company.get("matching_etablissements") or []:
                        if et.get("commune") != code or et.get("etat_administratif") not in (None, "A"):
                            continue
                        siret = et.get("siret")
                        kind = _kind(et.get("activite_principale") or naf, name)
                        if not kind:
                            continue
                        stats["trouvees"] += 1
                        if siret in known:
                            continue
                        known.add(siret)
                        lat = lon = None
                        if et.get("latitude") and et.get("longitude"):
                            lat, lon = float(et["latitude"]), float(et["longitude"])
                        ag = Agency(
                            siret=siret, name=(et.get("nom_commercial") or (et.get("liste_enseignes") or [None])[0] or name)[:300],
                            kind=kind, network=guess_network(name), address=et.get("adresse"), commune_code=code,
                            discovered_from="sirene",
                        )
                        if lat and lon:
                            ag.geom = f"SRID=4326;POINT({lon} {lat})"
                        db.add(ag)
                        stats["nouvelles"] += 1
                if page >= (data.get("total_pages") or 1):
                    break
                page += 1
        db.commit()
    return stats
