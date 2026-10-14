"""Dédoublonnage : regrouper les annonces d'un même bien publiées par plusieurs agences.

Deux annonces sont le même bien si :
- (fort) au moins 2 photos sont visuellement identiques (distance de Hamming ≤ 6 sur 64 bits) ;
- (moyen) même commune et caractéristiques compatibles : surface ±4 %, terrain ±8 % (si connu des deux),
  pièces et chambres égales (si connues), prix à ±15 % — avec au moins 3 critères concordants
  dont surface ET prix, et aucune contradiction.
Les réactions, notes et statut déjà saisis sont conservés sur le bien le plus « travaillé ».
"""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Property
from app.services.ingest import consolidate
from app.services.photos import hamming

PHOTO_DIST = 6


def _close(a, b, tol) -> bool | None:
    if not a or not b:
        return None
    return abs(a - b) <= tol * max(a, b)


COMMON: set[str] = set()  # empreintes très répandues (logos, images génériques) : ignorées


def photo_overlap(a: Property, b: Property) -> int:
    ha = [p.phash for li in a.listings for p in li.photos if p.phash and p.phash not in COMMON]
    hb = [p.phash for li in b.listings for p in li.photos if p.phash and p.phash not in COMMON]
    n = 0
    for x in ha:
        if any(hamming(x, y) <= PHOTO_DIST for y in hb):
            n += 1
    return n


def _contradiction(a: Property, b: Property) -> bool:
    """Même avec des photos communes, deux biens de tailles ou de prix très différents ne sont pas le même."""
    return (
        _close(a.surface, b.surface, 0.10) is False
        or _close(a.land, b.land, 0.30) is False
        or _close(a.price, b.price, 0.35) is False
        or (a.rooms and b.rooms and abs(a.rooms - b.rooms) > 1)
    )


def same_property(a: Property, b: Property) -> tuple[bool, str]:
    if photo_overlap(a, b) >= 2 and not _contradiction(a, b):
        return True, "photos"
    if not a.commune_code or a.commune_code != b.commune_code:
        return False, ""
    checks = {
        "surface": _close(a.surface, b.surface, 0.04),
        "prix": _close(a.price, b.price, 0.15),
        "terrain": _close(a.land, b.land, 0.08),
        "pieces": None if not (a.rooms and b.rooms) else a.rooms == b.rooms,
        "chambres": None if not (a.bedrooms and b.bedrooms) else a.bedrooms == b.bedrooms,
    }
    if any(v is False for v in checks.values()):
        return False, ""
    ok = [k for k, v in checks.items() if v]
    if "surface" in ok and "prix" in ok and len(ok) >= 3:
        return True, "caracteristiques"
    return False, ""


def _weight(p: Property) -> tuple:
    return (p.reaction is not None, p.status != "nouveau", bool(p.notes), -p.id)


def merge(db: Session, keep: Property, drop: Property) -> None:
    for li in list(drop.listings):
        li.property = keep
    if keep.reaction is None and drop.reaction:
        keep.reaction = drop.reaction
    if keep.status == "nouveau" and drop.status != "nouveau":
        keep.status = drop.status
    if drop.notes:
        keep.notes = f"{keep.notes}\n{drop.notes}" if keep.notes else drop.notes
    keep.first_seen = min(keep.first_seen, drop.first_seen)
    db.flush()
    db.delete(drop)
    db.flush()
    consolidate(keep)


def dedupe(db: Session) -> dict:
    props = db.scalars(select(Property).where(Property.is_active.is_(True))).all()
    # une image présente chez 4 biens distincts ou plus n'identifie pas un bien (logo d'étude, image générique)
    seen: dict[str, set[int]] = defaultdict(set)
    for p in props:
        for li in p.listings:
            for ph in li.photos:
                if ph.phash:
                    seen[ph.phash].add(p.id)
    COMMON.clear()
    COMMON.update(h for h, ids in seen.items() if len(ids) >= 4)
    by_commune: dict[str | None, list[Property]] = defaultdict(list)
    for p in props:
        by_commune[p.commune_code].append(p)
    merged = {"photos": 0, "caracteristiques": 0}
    # les photos peuvent rapprocher des communes différentes (commune mal lue) : on compare aussi par prix proche
    pools = list(by_commune.values())
    for pool in pools:
        i = 0
        pool.sort(key=_weight, reverse=True)
        while i < len(pool):
            a = pool[i]
            j = i + 1
            while j < len(pool):
                b = pool[j]
                ok, why = same_property(a, b)
                if ok:
                    merge(db, a, b)
                    merged[why] += 1
                    pool.pop(j)
                else:
                    j += 1
            i += 1
    db.commit()
    return {"fusions_photos": merged["photos"], "fusions_caracteristiques": merged["caracteristiques"]}
