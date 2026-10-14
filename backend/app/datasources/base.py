"""Interface commune aux sources de données publiques.

Chaque source :
- `refresh()` télécharge/importe ses données dans le cache local (PostGIS ou
  fichiers) et renvoie des statistiques ;
- `enrich()` (facultatif) calcule les valeurs pour un bien ; chaque valeur est
  enregistrée avec la source et la date des données.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import ClassVar

from sqlalchemy.orm import Session

from app.models import DataSourceStatus, Enrichment, Property
from app.settings_schema import UserSettings


class DataSource(ABC):
    key: ClassVar[str]
    name: ClassVar[str]
    url: ClassVar[str]
    licence: ClassVar[str] = "Licence Ouverte 2.0 (Etalab)"
    refresh_cron: ClassVar[dict | None] = {"day_of_week": "sun", "hour": 3}

    @abstractmethod
    def refresh(self, db: Session, settings: UserSettings) -> dict:
        """Met à jour le cache local. Renvoie {'rows': n, 'source_date': '...'}."""

    def enrich(self, db: Session, prop: Property, settings: UserSettings) -> dict[str, dict]:
        """Renvoie {clé: valeur} à enregistrer pour ce bien. Par défaut : rien."""
        return {}

    # --------------------------------------------------------------- helpers
    def status(self, db: Session) -> DataSourceStatus:
        st = db.get(DataSourceStatus, self.key)
        if st is None:
            st = DataSourceStatus(key=self.key, name=self.name, url=self.url, licence=self.licence)
            db.add(st)
        return st

    def run_refresh(self, db: Session, settings: UserSettings) -> dict:
        st = self.status(db)
        try:
            res = self.refresh(db, settings)
            st.status = "ok"
            st.rows = res.get("rows")
            st.source_date = res.get("source_date")
            st.message = None
            return res
        except Exception as e:
            db.rollback()
            st = self.status(db)
            st.status = "erreur"
            st.message = str(e)[:2000]
            raise
        finally:
            st.last_refresh_at = datetime.now(timezone.utc)
            db.commit()

    def save_enrichment(self, db: Session, prop: Property, values: dict[str, dict]) -> None:
        st = self.status(db)
        for k, v in values.items():
            row = db.query(Enrichment).filter_by(property_id=prop.id, key=k).one_or_none()
            if row is None:
                row = Enrichment(property_id=prop.id, key=k)
                db.add(row)
            row.value = v
            row.source = self.name
            row.source_date = st.source_date


REGISTRY: dict[str, DataSource] = {}


def register(cls: type[DataSource]) -> type[DataSource]:
    REGISTRY[cls.key] = cls()
    return cls
