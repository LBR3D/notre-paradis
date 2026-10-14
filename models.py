"""Modèle de données.

Vocabulaire :
- Listing  = une annonce publiée par UNE source (agence, notaire, portail…).
- Property = un « bien » réel, qui regroupe toutes les annonces qui le décrivent
             (dédoublonnage). C'est l'objet noté, affiché sur la carte, etc.
"""
from datetime import date, datetime

from geoalchemy2 import Geometry
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def _now():
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class Commune(Base):
    """Communes connues (zone de recherche et alentours)."""

    __tablename__ = "commune"
    code: Mapped[str] = mapped_column(String(5), primary_key=True)  # code INSEE
    nom: Mapped[str] = mapped_column(String(200), index=True)
    departement: Mapped[str] = mapped_column(String(3), index=True)
    epci: Mapped[str | None] = mapped_column(String(9), index=True)
    in_zone: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    geom = mapped_column(Geometry("MULTIPOLYGON", srid=4326, spatial_index=True))
    centroid = mapped_column(Geometry("POINT", srid=4326))


class Epci(Base):
    """Intercommunalités (servent à définir la zone de recherche)."""

    __tablename__ = "epci"
    code: Mapped[str] = mapped_column(String(9), primary_key=True)  # SIREN
    nom: Mapped[str] = mapped_column(String(300), index=True)
    geom = mapped_column(Geometry("MULTIPOLYGON", srid=4326, spatial_index=True))


class Agency(Base):
    """Agence, mandataire ou étude notariale découverte dans la zone."""

    __tablename__ = "agency"
    id: Mapped[int] = mapped_column(primary_key=True)
    siret: Mapped[str | None] = mapped_column(String(14), unique=True)
    name: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(String(20), default="agence")  # agence|notaire|mandataire
    network: Mapped[str | None] = mapped_column(String(100))  # Orpi, Century 21…
    address: Mapped[str | None] = mapped_column(Text)
    commune_code: Mapped[str | None] = mapped_column(String(5), index=True)
    website: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(String(40))
    discovered_from: Mapped[str | None] = mapped_column(String(50))
    geom = mapped_column(Geometry("POINT", srid=4326))
    created_at: Mapped[datetime] = _now()


class Source(Base):
    """Une source d'annonces collectée par un connecteur."""

    __tablename__ = "source"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(200), unique=True)
    name: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(String(20))  # agence|reseau|notaire|portail|alerte_email|manuel
    connector: Mapped[str] = mapped_column(String(100))  # clé du connecteur (registre)
    base_url: Mapped[str | None] = mapped_column(Text)
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    agency_id: Mapped[int | None] = mapped_column(ForeignKey("agency.id"))
    robots_status: Mapped[str] = mapped_column(String(20), default="inconnu")  # autorise|interdit|inconnu
    robots_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = _now()


class Property(Base):
    """Un bien réel (regroupe une ou plusieurs annonces)."""

    __tablename__ = "property"
    id: Mapped[int] = mapped_column(primary_key=True)
    first_seen: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Localisation
    commune_code: Mapped[str | None] = mapped_column(String(5), index=True)
    geom = mapped_column(Geometry("POINT", srid=4326, spatial_index=True))
    geo_confidence: Mapped[str] = mapped_column(String(1), default="D")  # A exacte … D centre commune
    geo_method: Mapped[str | None] = mapped_column(String(50))
    geo_candidates: Mapped[list] = mapped_column(JSONB, default=list)

    # Caractéristiques consolidées (issues des annonces)
    title: Mapped[str | None] = mapped_column(Text)
    property_type: Mapped[str | None] = mapped_column(String(50))
    price: Mapped[int | None] = mapped_column(Integer, index=True)
    price_initial: Mapped[int | None] = mapped_column(Integer)
    surface: Mapped[float | None] = mapped_column(Float)
    land: Mapped[float | None] = mapped_column(Float)
    rooms: Mapped[int | None] = mapped_column(Integer)
    bedrooms: Mapped[int | None] = mapped_column(Integer)
    year_built: Mapped[int | None] = mapped_column(Integer)
    dpe: Mapped[str | None] = mapped_column(String(1))
    ges: Mapped[str | None] = mapped_column(String(1))
    main_photo_url: Mapped[str | None] = mapped_column(Text)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    # Suivi personnel
    status: Mapped[str] = mapped_column(String(20), default="nouveau")  # nouveau|a_voir|visite|ecarte
    reaction: Mapped[str | None] = mapped_column(String(10))  # aime|bof|non
    seen: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    notes: Mapped[str | None] = mapped_column(Text)

    # Analyse et notation
    eliminated: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    elimination_reasons: Mapped[list] = mapped_column(JSONB, default=list)
    scores: Mapped[dict] = mapped_column(JSONB, default=dict)  # {critere: {note, explication}}
    score_total: Mapped[float | None] = mapped_column(Float, index=True)
    analysis: Mapped[dict] = mapped_column(JSONB, default=dict)  # photos + texte (étape 3)

    listings: Mapped[list["Listing"]] = relationship(back_populates="property")


class Listing(Base):
    """Une annonce publiée par une source."""

    __tablename__ = "listing"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("source.id"), index=True)
    property_id: Mapped[int | None] = mapped_column(ForeignKey("property.id"), index=True)
    url: Mapped[str] = mapped_column(Text, unique=True)
    external_id: Mapped[str | None] = mapped_column(String(200))

    first_seen: Mapped[datetime] = _now()
    last_seen: Mapped[datetime] = _now()
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    republished_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active|retiree

    # Champs extraits
    title: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    property_type: Mapped[str | None] = mapped_column(String(50))
    price: Mapped[int | None] = mapped_column(Integer)
    fees: Mapped[str | None] = mapped_column(String(100))  # « 5 % TTC à la charge de l'acquéreur »
    surface: Mapped[float | None] = mapped_column(Float)
    land: Mapped[float | None] = mapped_column(Float)
    rooms: Mapped[int | None] = mapped_column(Integer)
    bedrooms: Mapped[int | None] = mapped_column(Integer)
    year_built: Mapped[int | None] = mapped_column(Integer)
    dpe: Mapped[str | None] = mapped_column(String(1))
    ges: Mapped[str | None] = mapped_column(String(1))
    heating: Mapped[str | None] = mapped_column(String(200))
    sewage: Mapped[str | None] = mapped_column(String(200))
    outbuildings: Mapped[str | None] = mapped_column(Text)
    property_tax: Mapped[int | None] = mapped_column(Integer)
    condition: Mapped[str | None] = mapped_column(String(100))
    commune_name: Mapped[str | None] = mapped_column(String(200))
    commune_code: Mapped[str | None] = mapped_column(String(5), index=True)
    postal_code: Mapped[str | None] = mapped_column(String(5))
    address: Mapped[str | None] = mapped_column(Text)
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    virtual_tour_url: Mapped[str | None] = mapped_column(Text)
    contact: Mapped[dict] = mapped_column(JSONB, default=dict)
    extra: Mapped[dict] = mapped_column(JSONB, default=dict)  # tout le reste
    extraction_method: Mapped[str | None] = mapped_column(String(20))  # parser|llm|email|manuel
    content_hash: Mapped[str | None] = mapped_column(String(64))

    property: Mapped[Property | None] = relationship(back_populates="listings")
    photos: Mapped[list["Photo"]] = relationship(back_populates="listing", order_by="Photo.position")


class Photo(Base):
    __tablename__ = "photo"
    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listing.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(Text)
    local_path: Mapped[str | None] = mapped_column(Text)
    thumb_path: Mapped[str | None] = mapped_column(Text)
    phash: Mapped[str | None] = mapped_column(String(32), index=True)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    position: Mapped[int] = mapped_column(Integer, default=0)
    analysis: Mapped[dict] = mapped_column(JSONB, default=dict)

    listing: Mapped[Listing] = relationship(back_populates="photos")
    __table_args__ = (UniqueConstraint("listing_id", "url"),)


class PriceEvent(Base):
    """Historique : apparition, baisse, hausse, retrait, republication."""

    __tablename__ = "price_event"
    id: Mapped[int] = mapped_column(primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("listing.id", ondelete="CASCADE"), index=True)
    observed_at: Mapped[datetime] = _now()
    event: Mapped[str] = mapped_column(String(20))
    price: Mapped[int | None] = mapped_column(Integer)
    previous_price: Mapped[int | None] = mapped_column(Integer)


class Enrichment(Base):
    """Une donnée publique calculée pour un bien, avec sa source et sa date."""

    __tablename__ = "enrichment"
    id: Mapped[int] = mapped_column(primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("property.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(100))
    value: Mapped[dict] = mapped_column(JSONB)
    source: Mapped[str] = mapped_column(String(200))
    source_date: Mapped[str | None] = mapped_column(String(50))
    computed_at: Mapped[datetime] = _now()
    __table_args__ = (UniqueConstraint("property_id", "key"),)


class Reaction(Base):
    """Historique de vos réactions (sert à apprendre vos goûts)."""

    __tablename__ = "reaction"
    id: Mapped[int] = mapped_column(primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("property.id", ondelete="CASCADE"), index=True)
    reaction: Mapped[str] = mapped_column(String(10))  # aime|bof|non
    tags: Mapped[list] = mapped_column(JSONB, default=list)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()


class RunLog(Base):
    """Journal de chaque tâche (collecte, enrichissement, import de données…)."""

    __tablename__ = "run_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    job: Mapped[str] = mapped_column(String(100), index=True)
    started_at: Mapped[datetime] = _now()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="en_cours")  # en_cours|succes|partiel|erreur
    stats: Mapped[dict] = mapped_column(JSONB, default=dict)
    message: Mapped[str | None] = mapped_column(Text)
    errors: Mapped[list] = mapped_column(JSONB, default=list)


class ApiUsage(Base):
    """Consommation des API payantes (Claude, TomTom…)."""

    __tablename__ = "api_usage"
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = _now()
    provider: Mapped[str] = mapped_column(String(30))
    model: Mapped[str | None] = mapped_column(String(100))
    purpose: Mapped[str] = mapped_column(String(100))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    requests: Mapped[int] = mapped_column(Integer, default=1)
    cost_eur: Mapped[float] = mapped_column(Float, default=0.0)
    property_id: Mapped[int | None] = mapped_column(ForeignKey("property.id", ondelete="SET NULL"))


class DataSourceStatus(Base):
    """État de chaque jeu de données publiques en cache (source, date, fraîcheur)."""

    __tablename__ = "datasource_status"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(300))
    url: Mapped[str | None] = mapped_column(Text)
    licence: Mapped[str | None] = mapped_column(String(100))
    source_date: Mapped[str | None] = mapped_column(String(50))
    last_refresh_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="jamais")  # jamais|ok|erreur
    rows: Mapped[int | None] = mapped_column(Integer)
    message: Mapped[str | None] = mapped_column(Text)


class AppSettings(Base):
    """Réglages modifiables dans l'application (une seule ligne, id = 1)."""

    __tablename__ = "app_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    data: Mapped[dict] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DvfSale(Base):
    """Vente de maison issue des « Demandes de valeurs foncières » (DVF), une ligne par vente."""

    __tablename__ = "dvf_sale"
    id_mutation: Mapped[str] = mapped_column(String(30), primary_key=True)
    sold_on: Mapped[date] = mapped_column(Date, index=True)
    price: Mapped[int] = mapped_column(Integer)
    commune_code: Mapped[str] = mapped_column(String(5), index=True)
    surface: Mapped[float | None] = mapped_column(Float)
    land: Mapped[float | None] = mapped_column(Float)
    rooms: Mapped[int | None] = mapped_column(Integer)
    address: Mapped[str | None] = mapped_column(Text)
    geom = mapped_column(Geometry("POINT", srid=4326, spatial_index=True))
