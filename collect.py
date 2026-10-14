"""Collecte : parcourt les sources activées, enregistre les annonces de la zone.

Une source en échec n'arrête pas les autres (statut « partiel »). Une annonce qui n'est plus
listée par sa source est marquée « retirée » seulement si le parcours de la source est complet.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors import load_all
from app.connectors.base import REGISTRY
from app.connectors.catalog import seed_sources
from app.core.http import PoliteClient, RobotsDisallowed
from app.jobs.runner import JobContext
from app.models import Source
from app.services.ingest import mark_removed, upsert_listing
from app.services.zone import ZoneIndex
from app.settings_schema import UserSettings

load_all()
log = logging.getLogger("collect")


def check_robots(client: PoliteClient, source: Source) -> bool:
    if not source.base_url:
        return True
    ok = client.allowed(source.base_url.rstrip("/") + "/")
    source.robots_status = "autorise" if ok else "interdit"
    source.robots_checked_at = datetime.now(timezone.utc)
    return ok


def collect_source(db: Session, source: Source, zone: ZoneIndex, settings: UserSettings, ctx: JobContext, client: PoliteClient | None = None, limit: int | None = None) -> dict:
    cls = REGISTRY[source.connector]
    client = client or PoliteClient(min_delay=settings.collecte.delai_min_secondes, cache_ttl_hours=settings.collecte.duree_cache_heures)
    stats = {"vues": 0, "nouvelles": 0, "baisses": 0, "retirees": 0, "erreurs": 0}
    if not check_robots(client, source):
        source.last_status = "interdit"
        ctx.error(source.key, "robots.txt interdit l'accès : source ignorée")
        return stats
    config = dict(source.config or {})
    if limit:
        config["max_listings"] = limit
    conn = cls(config, client)
    conn.zone = zone
    seen: set[str] = set()
    complete = True
    try:
        for ref in conn.discover():
            seen.add(ref.url)
            try:
                data = conn.fetch(ref)
            except RobotsDisallowed:
                stats["erreurs"] += 1
                continue
            except Exception as e:  # noqa: BLE001
                stats["erreurs"] += 1
                ctx.error(f"{source.key} {ref.url}", e)
                complete = False
                continue
            if data is None:
                continue
            stats["vues"] += 1
            if data.commune_name is None and ref.hint.get("commune_name"):
                data.commune_name = ref.hint["commune_name"]
            _, event = upsert_listing(db, source, data)
            if event == "apparition":
                stats["nouvelles"] += 1
            elif event == "baisse":
                stats["baisses"] += 1
            db.commit()
    except Exception as e:  # noqa: BLE001
        complete = False
        db.rollback()
        ctx.error(source.key, e)
    if complete and not limit:
        stats["retirees"] = mark_removed(db, source, seen)
    source.last_run_at = datetime.now(timezone.utc)
    source.last_status = "ok" if complete else "partiel"
    db.commit()
    return stats


def run_collect(db: Session, ctx: JobContext, only: str | None = None, limit: int | None = None) -> None:
    seed_sources(db)
    db.commit()
    zone = ZoneIndex.load(db)
    if not len(zone):
        ctx.error("zone", "aucune commune dans la zone : importez d'abord les communes")
        return
    q = select(Source).where(Source.enabled.is_(True))
    if only:
        q = q.where(Source.key == only)
    client = PoliteClient(min_delay=ctx.settings.collecte.delai_min_secondes, cache_ttl_hours=ctx.settings.collecte.duree_cache_heures)
    for source in db.scalars(q).all():
        res = collect_source(db, source, zone, ctx.settings, ctx, client=client, limit=limit)
        for k, v in res.items():
            ctx.incr(k, v)
        ctx.log(f"{source.name} : {res}")
