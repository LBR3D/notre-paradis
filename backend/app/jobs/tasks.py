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
