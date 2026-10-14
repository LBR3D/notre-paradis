"""Point d'entrée : API + planificateur + interface web (fichiers statiques)."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select

from app.api.routes import router
from app.core.config import env
from app.core.db import SessionLocal
from app.jobs import scheduler, tasks  # noqa: F401  (enregistre les tâches)
from app.jobs.runner import run_job_async
from app.models import Commune

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s : %(message)s")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    for d in (env.cache_dir, env.public_data_dir, env.photos_dir):
        d.mkdir(parents=True, exist_ok=True)
    if env.scheduler_enabled:
        scheduler.start()
        # Premier démarrage : importer les communes pour afficher la zone
        db = SessionLocal()
        try:
            if not db.scalar(select(func.count()).select_from(Commune)):
                run_job_async("donnees:communes")
        finally:
            db.close()
    yield
    if scheduler.scheduler.running:
        scheduler.scheduler.shutdown(wait=False)


app = FastAPI(title="Notre paradis", lifespan=lifespan)
app.include_router(router)

if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = STATIC_DIR / path
        if path and f.is_file():
            return FileResponse(f)
        return FileResponse(STATIC_DIR / "index.html")
