"""Connecteurs d'annonces. `load_all()` importe tous les modules du dossier (ils s'enregistrent seuls)."""
import importlib
import pkgutil

from app.connectors.base import REGISTRY  # noqa: F401


def load_all() -> None:
    for m in pkgutil.iter_modules(__path__):
        if m.name not in ("base", "catalog"):
            importlib.import_module(f"{__name__}.{m.name}")
