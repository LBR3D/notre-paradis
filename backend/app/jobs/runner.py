"""Exécution des tâches de fond avec journal (table run_log).

Une tâche est une fonction `f(ctx: JobContext)`. Elle remplit `ctx.stats`,
signale les erreurs non bloquantes avec `ctx.error(...)` et peut écrire des
messages avec `ctx.log(...)`. Le statut final est :
- succes  : aucune erreur ;
- partiel : des erreurs non bloquantes (ex. une source sur dix en échec) ;
- erreur  : exception non rattrapée.
"""
from __future__ import annotations

import logging
import threading
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.core.db import SessionLocal
from app.models import RunLog
from app.services.settings_service import load_settings
from app.settings_schema import UserSettings

log = logging.getLogger("jobs")


@dataclass
class JobContext:
    run_id: int
    settings: UserSettings
    stats: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)
    messages: list = field(default_factory=list)

    def log(self, msg: str) -> None:
        log.info(msg)
        self.messages.append(msg)

    def error(self, where: str, exc: BaseException | str) -> None:
        log.warning("%s : %s", where, exc)
        self.errors.append({"ou": where, "erreur": str(exc)[:1000]})

    def incr(self, key: str, n: int = 1) -> None:
        self.stats[key] = self.stats.get(key, 0) + n


@dataclass
class JobSpec:
    name: str
    label: str
    func: Callable[[JobContext], None]
    # Renvoie les paramètres « cron » d'APScheduler, ou None pour une tâche manuelle
    schedule: Callable[[UserSettings], dict | None] = lambda s: None


JOBS: dict[str, JobSpec] = {}
_running: set[str] = set()
_running_lock = threading.Lock()


def job(name: str, label: str, schedule: Callable[[UserSettings], dict | None] | None = None):
    def deco(func):
        JOBS[name] = JobSpec(name, label, func, schedule or (lambda s: None))
        return func

    return deco


def is_running(name: str) -> bool:
    return name in _running


def run_job(name: str) -> int | None:
    """Exécute une tâche (bloquant). Renvoie l'id du journal, ou None si déjà en cours."""
    spec = JOBS[name]
    with _running_lock:
        if name in _running:
            return None
        _running.add(name)
    db = SessionLocal()
    try:
        run = RunLog(job=name, status="en_cours")
        db.add(run)
        db.commit()
        ctx = JobContext(run_id=run.id, settings=load_settings(db))
        try:
            spec.func(ctx)
            run.status = "partiel" if ctx.errors else "succes"
        except Exception as e:  # noqa: BLE001
            ctx.error("tâche", e)
            ctx.messages.append(traceback.format_exc()[-3000:])
            run.status = "erreur"
        run.finished_at = datetime.now(timezone.utc)
        run.stats = ctx.stats
        run.errors = ctx.errors
        run.message = "\n".join(ctx.messages)[-5000:] or None
        db.commit()
        return run.id
    finally:
        db.close()
        with _running_lock:
            _running.discard(name)


def run_job_async(name: str) -> bool:
    if is_running(name):
        return False
    threading.Thread(target=run_job, args=(name,), daemon=True).start()
    return True
