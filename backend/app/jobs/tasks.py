"""Déclaration des tâches planifiées.

Étape 0 : rafraîchissement des données publiques.
Les étapes suivantes ajoutent ici la collecte, l'enrichissement, l'analyse…
"""
from __future__ import annotations

from app.core.db import session_scope
from app.datasources import REGISTRY as DATASOURCES
from app.jobs.runner import JobContext, job


def _datasource_job(key: str):
    ds = DATASOURCES[key]

    def run(ctx: JobContext) -> None:
        with session_scope() as db:
            res = ds.run_refresh(db, ctx.settings)
            ctx.stats.update(res)
            ctx.log(f"{ds.name} : {res}")

    job(f"donnees:{key}", f"Données publiques — {ds.name}", schedule=lambda s, c=ds.refresh_cron: c)(run)


for _key in DATASOURCES:
    _datasource_job(_key)


def _after_collect(ctx: JobContext) -> None:
    """Enchaînement après la collecte : photos → dédoublonnage → localisation → enrichissement → éliminatoires."""
    from app.services.dedup import dedupe
    from app.services.geoloc import geolocate_all
    from app.services.photos import hash_new_photos

    from app.services.eliminate import evaluate_all
    from app.services.enrich import enrich_all

    steps = (
        ("photos", lambda db: hash_new_photos(db)),
        ("dedoublonnage", dedupe),
        ("localisation", geolocate_all),
        ("enrichissement", lambda db: enrich_all(db, ctx.settings)),
        ("eliminatoires", lambda db: evaluate_all(db, ctx.settings)),
    )
    for name, fn in steps:
        try:
            with session_scope() as db:
                res = fn(db)
            ctx.stats[name] = res
            ctx.log(f"{name} : {res}")
        except Exception as e:  # noqa: BLE001
            ctx.error(name, e)


@job("collecte", "Collecte des annonces (toutes les sources)", schedule=lambda s: {"hour": ",".join(str(h) for h in s.collecte.heures), "minute": 15} if s.collecte.actif and s.collecte.heures else None)
def collecte(ctx: JobContext) -> None:
    from app.services.collect import run_collect

    with session_scope() as db:
        run_collect(db, ctx)
    _after_collect(ctx)


@job("traitement", "Photos, dédoublonnage, localisation, enrichissement (sans nouvelle collecte)")
def traitement(ctx: JobContext) -> None:
    _after_collect(ctx)


@job("agences", "Découverte des agences et notaires (Sirene)", schedule=lambda s: {"day_of_week": "sun", "hour": 4})
def agences(ctx: JobContext) -> None:
    from app.services.agencies import discover_agencies

    with session_scope() as db:
        res = discover_agencies(db)
        ctx.stats.update(res)
        ctx.log(f"Agences : {res}")
