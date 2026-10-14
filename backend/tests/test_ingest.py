from sqlalchemy import select

from app.connectors.base import ListingData
from app.models import PriceEvent, Source
from app.services.ingest import mark_removed, upsert_listing


def _source(db):
    s = Source(key="test", name="Agence test", kind="agence", connector="test")
    db.add(s)
    db.flush()
    return s


def _data(price=350_000, url="https://agence.example/annonce/1"):
    return ListingData(
        url=url, title="Longère à colombages", price=price, surface=140, land=5000, bedrooms=4,
        commune_name="Pont-l'Évêque", photos=["https://agence.example/p1.jpg", "https://agence.example/p2.jpg"],
    )


def test_history_events(db):
    src = _source(db)
    li, ev = upsert_listing(db, src, _data())
    assert ev == "apparition"
    assert li.property is not None and li.property.price == 350_000
    assert len(li.photos) == 2

    _, ev = upsert_listing(db, src, _data())
    assert ev is None  # rien de nouveau

    li, ev = upsert_listing(db, src, _data(price=329_000))
    assert ev == "baisse"
    assert li.property.price == 329_000
    assert li.property.price_initial == 350_000

    assert mark_removed(db, src, seen_urls=set()) == 1
    assert li.status == "retiree"
    assert li.property.is_active is False

    li, ev = upsert_listing(db, src, _data(price=329_000))
    assert ev == "republication"
    assert li.republished_count == 1
    assert li.property.is_active is True

    events = [e.event for e in db.scalars(select(PriceEvent).order_by(PriceEvent.id))]
    assert events == ["apparition", "baisse", "retrait", "republication"]
