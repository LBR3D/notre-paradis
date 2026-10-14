"""Interface commune à tous les connecteurs d'annonces.

Pour ajouter une source : créer un fichier dans app/connectors/, écrire une
classe qui hérite de `Connector`, la décorer avec `@register`, et implémenter
`discover()` (liste des annonces) et `fetch()` (détail d'une annonce).
Voir README, section « Ajouter une source ».
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import ClassVar

from app.core.http import PoliteClient


@dataclass
class ListingRef:
    """Une annonce repérée sur une page de liste (avant d'ouvrir sa page détail)."""

    url: str
    external_id: str | None = None
    hint: dict = field(default_factory=dict)  # prix / titre visibles dans la liste


@dataclass
class ListingData:
    """Annonce normalisée, quelle que soit la source."""

    url: str
    external_id: str | None = None
    title: str | None = None
    description: str | None = None
    property_type: str | None = None
    price: int | None = None
    fees: str | None = None
    surface: float | None = None
    land: float | None = None
    rooms: int | None = None
    bedrooms: int | None = None
    year_built: int | None = None
    dpe: str | None = None
    ges: str | None = None
    heating: str | None = None
    sewage: str | None = None
    outbuildings: str | None = None
    property_tax: int | None = None
    condition: str | None = None
    commune_name: str | None = None
    postal_code: str | None = None
    address: str | None = None
    lat: float | None = None
    lon: float | None = None
    virtual_tour_url: str | None = None
    contact: dict = field(default_factory=dict)
    photos: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)
    extraction_method: str = "parser"


class Connector(ABC):
    key: ClassVar[str]
    label: ClassVar[str]
    kind: ClassVar[str] = "agence"

    def __init__(self, config: dict, client: PoliteClient):
        self.config = config or {}
        self.client = client

    @abstractmethod
    def discover(self) -> Iterable[ListingRef]:
        """Parcourt les pages de liste et renvoie toutes les annonces en ligne."""

    @abstractmethod
    def fetch(self, ref: ListingRef) -> ListingData | None:
        """Télécharge et extrait une annonce."""


REGISTRY: dict[str, type[Connector]] = {}


def register(cls: type[Connector]) -> type[Connector]:
    REGISTRY[cls.key] = cls
    return cls
