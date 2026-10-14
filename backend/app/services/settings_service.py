"""Lecture / écriture des réglages stockés en base."""
from typing import Any

from sqlalchemy.orm import Session

from app.models import AppSettings
from app.settings_schema import UserSettings


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_settings(db: Session) -> UserSettings:
    row = db.get(AppSettings, 1)
    defaults = UserSettings().model_dump()
    stored = row.data if row else {}
    merged = _deep_merge(defaults, stored or {})
    # Les champs devenus invalides (ex. renommés) sont ignorés plutôt que bloquants
    try:
        return UserSettings.model_validate(merged)
    except Exception:
        return UserSettings()


def save_settings(db: Session, data: dict[str, Any]) -> UserSettings:
    current = load_settings(db).model_dump()
    merged = _deep_merge(current, data)
    validated = UserSettings.model_validate(merged)  # lève une erreur 422 si invalide
    row = db.get(AppSettings, 1)
    if row is None:
        row = AppSettings(id=1, data={})
        db.add(row)
    row.data = validated.model_dump()
    db.commit()
    return validated


def reset_section(db: Session, section: str) -> UserSettings:
    defaults = UserSettings().model_dump()
    if section not in defaults:
        raise KeyError(section)
    current = load_settings(db).model_dump()
    current[section] = defaults[section]
    return save_settings(db, current)
