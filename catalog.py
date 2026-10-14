"""Catalogue des sources prêtes à l'emploi (réseaux nationaux d'agences, notaires).

Une source = un fichier JSON dans `app/connectors/sources/` (clé, nom, type, connecteur, adresse,
configuration, `enabled`, `note`). Elles sont insérées en base au premier démarrage (`seed_sources`) ;
leur état (activée, robots.txt, dernier résultat) se gère ensuite dans la page Journaux.
Une source `enabled: false` est connue mais pas encore vérifiée : le motif est dans `note`.
"""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Source

SOURCES_DIR = Path(__file__).parent / "sources"
FIELDS = {"key", "name", "kind", "connector", "base_url", "config", "enabled", "note"}


def load_catalog() -> list[dict]:
    out = []
    for p in sorted(SOURCES_DIR.glob("*.json")):
        d = json.loads(p.read_text(encoding="utf8"))
        out.append({k: v for k, v in d.items() if k in FIELDS})
    return out


def seed_sources(db: Session) -> int:
    """Ajoute les sources absentes ; met à jour la configuration des sources déjà présentes."""
    n = 0
    for entry in load_catalog():
        existing = db.scalar(select(Source).where(Source.key == entry["key"]))
        if existing is None:
            db.add(Source(**entry))
            n += 1
        else:
            existing.config = entry.get("config", {})
            existing.base_url = entry.get("base_url")
            existing.connector = entry["connector"]
            existing.note = entry.get("note")
    db.flush()
    return n
