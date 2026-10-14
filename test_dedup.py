from app.models import Listing, Photo, Property, Source
from app.services.dedup import dedupe, same_property
from app.services.ingest import consolidate
from app.services.photos import dhash, hamming


def _mk(db, src, url, commune="14514", **kw):
    li = Listing(source_id=src.id, url=url, commune_code=commune, status="active", **kw)
    db.add(li)
    p = Property(commune_code=commune)
    li.property = p
    db.flush()
    consolidate(p)
    return li


def test_hamming():
    assert hamming("ff", "00") == 8 and hamming(5, 5) == 0


def test_same_by_characteristics_and_not_when_contradiction(db):
    src = Source(key="s1", name="s1", kind="agence", connector="sitemap")
    db.add(src)
    db.flush()
    a = _mk(db, src, "https://a/1", price=300000, surface=120, land=1500, rooms=5, bedrooms=3)
    b = _mk(db, src, "https://b/1", price=310000, surface=121, land=1500, rooms=5, bedrooms=3)
    c = _mk(db, src, "https://c/1", price=305000, surface=121, land=1500, rooms=6, bedrooms=3)
    assert same_property(a.property, b.property) == (True, "caracteristiques")
    assert same_property(a.property, c.property)[0] is False


def test_dedupe_merges_and_keeps_reaction(db):
    src = Source(key="s2", name="s2", kind="agence", connector="sitemap")
    db.add(src)
    db.flush()
    a = _mk(db, src, "https://a/2", price=300000, surface=120, land=1500, rooms=5)
    b = _mk(db, src, "https://b/2", price=295000, surface=120, land=1500, rooms=5)
    b.property.reaction = "aime"
    db.flush()
    res = dedupe(db)
    assert res["fusions_caracteristiques"] == 1
    db.expire_all()
    assert a.property_id == b.property_id
    assert a.property.reaction == "aime"
    assert a.property.price == 295000


def test_photo_match_rejected_when_sizes_contradict(db):
    from app.services.photos import hamming  # noqa: F401

    src = Source(key="s3", name="s3", kind="agence", connector="sitemap")
    db.add(src)
    db.flush()
    a = _mk(db, src, "https://a/3", price=522500, surface=164, land=5000, rooms=7)
    b = _mk(db, src, "https://b/3", price=369900, surface=95, land=3000, rooms=5)
    for li in (a, b):
        for i in range(3):
            li.photos.append(Photo(url=f"https://img/{li.id}/{i}", phash=f"{i:016x}", position=i))
    db.flush()
    assert same_property(a.property, b.property)[0] is False
