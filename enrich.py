"""Enrichissement : calcule, pour chaque bien actif, les données publiques de chaque source."""
from __future__ import annotations

import logging

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.datasources import REGISTRY
from app.models import Enrichment, Property
from app.settings_schema import UserSettings

log = logging.getLogger("enrich")


def enrich_all(db: Session, settings: UserSettings, only: list[str] | None = None, limit: int = 1000, force: bool = False) -> dict:
    stats: dict[str, int] = {"biens": 0, "valeurs": 0, "erreurs": 0}
    now = datetime.now(timezone.utc)
    computed: dict[tuple[int, str], datetime] = {(e.property_id, e.key): e.computed_at for e in db.scalars(select(Enrichment))}
    for prop in db.scalars(select(Property).where(Property.is_active.is_(True)).order_by(Property.id).limit(limit)).all():
        for key, ds in REGISTRY.items():
            if only and key not in only:
                continue
            if ds.enrich_keys and not force and all(
                (t := computed.get((prop.id, k))) and now - t < timedelta(days=ds.ttl_days) for k in ds.enrich_keys
            ):
                continue
            try:
                values = ds.enrich(db, prop, settings)
                if values:
                    ds.save_enrichment(db, prop, values)
                    stats["valeurs"] += len(values)
            except Exception as e:  # noqa: BLE001
                db.rollback()
                stats["erreurs"] += 1
                log.warning("enrichissement %s/%s : %s", key, prop.id, e)
        stats["biens"] += 1
        db.commit()
    return stats
