"""Planificateur (APScheduler) : lance les tâches aux heures prévues.

Les horaires dépendent des réglages (ex. heures de collecte) : `reschedule()`
est rappelé à chaque enregistrement des réglages.
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.db import SessionLocal
from app.jobs.runner import JOBS, run_job
from app.services.settings_service import load_settings

log = logging.getLogger("scheduler")
scheduler = BackgroundScheduler(timezone="Europe/Paris", job_defaults={"coalesce": True, "max_instances": 1})


def reschedule() -> None:
    db = SessionLocal()
    try:
        settings = load_settings(db)
    finally:
        db.close()
    for j in scheduler.get_jobs():
        j.remove()
    for spec in JOBS.values():
        cron = spec.schedule(settings)
        if cron:
            scheduler.add_job(run_job, CronTrigger(**cron), args=[spec.name], id=spec.name, misfire_grace_time=3600)
    log.info("Tâches planifiées : %s", [j.id for j in scheduler.get_jobs()])


def start() -> None:
    if not scheduler.running:
        scheduler.start()
    reschedule()


def next_runs() -> dict[str, str | None]:
    out = {}
    for j in scheduler.get_jobs():
        t = getattr(j, "next_run_time", None)  # absent tant que le planificateur n'est pas démarré
        out[j.id] = t.isoformat() if t else None
    return out
