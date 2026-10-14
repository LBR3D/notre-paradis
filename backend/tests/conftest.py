"""Tests : nécessitent une base PostGIS de test.

    docker compose up -d db
    docker compose exec db createdb -U paradis paradis_test
    cd backend && pytest
"""
import os

# Les tests vident les tables : ils ne doivent JAMAIS tourner sur la vraie base.
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://paradis:paradis@localhost:5432/paradis_test")
assert os.environ["DATABASE_URL"].rsplit("/", 1)[-1].endswith("_test"), "TEST_DATABASE_URL doit désigner une base dont le nom finit par _test"
os.environ.setdefault("SCHEDULER_ENABLED", "false")
os.environ.setdefault("DATA_DIR", "/tmp/notre-paradis-tests")

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.db import SessionLocal, engine  # noqa: E402

HERE = os.path.dirname(__file__)


@pytest.fixture(scope="session", autouse=True)
def _schema():
    cfg = Config(os.path.join(HERE, "..", "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(HERE, "..", "migrations"))
    command.upgrade(cfg, "head")
    yield


@pytest.fixture()
def db():
    s = SessionLocal()
    yield s
    s.rollback()
    s.close()
    with engine.begin() as c:
        c.execute(text(
            "TRUNCATE price_event, photo, listing, reaction, enrichment, property, source, app_settings, run_log RESTART IDENTITY CASCADE"
        ))
