"""Enregistrement des annonces collectées et de leur historique.

- nouvelle annonce        → événement « apparition »
- prix différent          → « baisse » ou « hausse »
- annonce disparue        → « retrait »   (voir mark_removed)
- annonce réapparue       → « republication »

Le rattachement à un « bien » (dédoublonnage multi-agences) est fait par
`attach_to_property` ; l'étape 1 le remplacera par la version complète
(photos, caractéristiques, proximité).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.base import ListingData
from app.models import Listing, Photo, PriceEvent, Property, Source

FIELDS = [
    "external_id", "title", "description", "property_type", "price", "fees", "surface", "land",
    "rooms", "bedrooms", "year_built", "dpe", "ges", "heating", "sewage", "outbuildings",
    "property_tax", "condition", "commune_name", "postal_code", "address", "lat", "lon",
    "virtual_tour_url", "contact", "extra", "extraction_method",
]


def _hash(data: ListingData) -> str:
    d = asdict(data)
    d.pop("extra", None)
    return hashlib.sha256(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()


def upsert_listing(db: Session, source: Source, data: ListingData) -> tuple[Listing, str | None]:
    """Crée ou met à jour une annonce. Renvoie (annonce, événement éventuel)."""
    now = datetime.now(timezone.utc)
    listing = db.scalar(select(Listing).where(Listing.url == data.url))
    event = None

    if listing is None:
        listing = Listing(source_id=source.id, url=data.url, first_seen=now, last_seen=now)
        db.add(listing)
        event = "apparition"
        previous_price = None
    else:
        previous_price = listing.price
        if listing.status == "retiree":
            listing.status = "active"
            listing.removed_at = None
            listing.republished_count += 1
            event = "republication"
        elif data.price and previous_price and data.price != previous_price:
            event = "baisse" if data.price < previous_price else "hausse"
        listing.last_seen = now

    for f in FIELDS:
        v = getattr(data, f)
        if v not in (None, "", [], {}):
            setattr(listing, f, v)
    if data.extra.get("commune_code"):
        listing.commune_code = data.extra["commune_code"]
    listing.content_hash = _hash(data)
    db.flush()

    existing = {p.url for p in listing.photos}
    for i, url in enumerate(data.photos):
        if url not in existing:
            listing.photos.append(Photo(url=url, position=i))

    if event:
        db.add(PriceEvent(listing_id=listing.id, event=event, price=data.price, previous_price=previous_price))

    attach_to_property(db, listing, event)
    return listing, event


def mark_removed(db: Session, source: Source, seen_urls: set[str]) -> int:
    """Après une collecte complète d'une source : les annonces absentes sont « retirées »."""
    now = datetime.now(timezone.utc)
    n = 0
    for listing in db.scalars(
        select(Listing).where(Listing.source_id == source.id, Listing.status == "active")
    ):
        if listing.url not in seen_urls:
            listing.status = "retiree"
            listing.removed_at = now
            db.add(PriceEvent(listing_id=listing.id, event="retrait", price=listing.price))
            n += 1
    db.flush()
    for prop in db.scalars(select(Property).where(Property.is_active.is_(True))):
        prop.is_active = any(item.status == "active" for item in prop.listings)
    return n


def attach_to_property(db: Session, listing: Listing, event: str | None) -> Property:
    """Version simple : un bien par annonce. Remplacée à l'étape 1 par le dédoublonnage."""
    prop = listing.property
    if prop is None:
        prop = Property()
        db.add(prop)
        listing.property = prop
    consolidate(prop)
    if event in ("baisse", "republication"):
        prop.seen = False  # réapparaît dans « Nouveautés »
    return prop


def consolidate(prop: Property) -> None:
    """Calcule les caractéristiques du bien à partir de ses annonces actives."""
    items = [x for x in prop.listings if x.status == "active"] or list(prop.listings)
    if not items:
        return

    def first(attr):
        for x in items:
            v = getattr(x, attr)
            if v not in (None, ""):
                return v
        return None

    prices = [x.price for x in items if x.price]
    prop.price = min(prices) if prices else None
    if prop.price_initial is None:
        prop.price_initial = prop.price
    for attr in ("title", "property_type", "surface", "land", "rooms", "bedrooms", "year_built", "dpe", "ges", "commune_code"):
        setattr(prop, attr, first(attr))
    photos = [p for x in items for p in x.photos]
    if photos:
        prop.main_photo_url = photos[0].url
    prop.is_active = any(x.status == "active" for x in prop.listings)
