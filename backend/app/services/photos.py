"""Photos : téléchargement, miniature et empreinte visuelle (dHash 64 bits).

L'empreinte sert au dédoublonnage : la même maison publiée par deux agences a les mêmes photos,
même recadrées ou recompressées. Les photos sont téléchargées avec le client poli.
"""
from __future__ import annotations

import hashlib
import io
from pathlib import Path

from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import env
from app.core.http import PoliteClient
from app.models import Listing, Photo


def dhash(img: Image.Image) -> int:
    g = img.convert("L").resize((9, 8), Image.LANCZOS)
    px = list(g.getdata())
    bits = 0
    for row in range(8):
        for col in range(8):
            bits = (bits << 1) | (px[row * 9 + col] > px[row * 9 + col + 1])
    return bits


def hamming(a: str | int, b: str | int) -> int:
    ia = int(a, 16) if isinstance(a, str) else a
    ib = int(b, 16) if isinstance(b, str) else b
    return bin(ia ^ ib).count("1")


def process_image(data: bytes, thumb_dir: Path, key: str) -> dict:
    img = Image.open(io.BytesIO(data))
    img.load()
    h = dhash(img)
    w, ht = img.size
    thumb_dir.mkdir(parents=True, exist_ok=True)
    thumb = img.convert("RGB")
    thumb.thumbnail((480, 360))
    p = thumb_dir / f"{key}.jpg"
    thumb.save(p, "JPEG", quality=78)
    return {"phash": f"{h:016x}", "width": w, "height": ht, "thumb_path": str(p)}


def hash_new_photos(db: Session, client: PoliteClient | None = None, per_listing: int = 5, max_total: int = 2000) -> dict:
    """Télécharge les premières photos des annonces actives qui n'ont pas encore d'empreinte."""
    client = client or PoliteClient(min_delay=0.4, cache_ttl_hours=0)
    stats = {"traitees": 0, "echecs": 0}
    rows = db.scalars(
        select(Photo).join(Listing).where(Listing.status == "active", Photo.phash.is_(None), Photo.position < per_listing).order_by(Photo.id).limit(max_total)
    ).all()
    for ph in rows:
        try:
            data = client.get_bytes(ph.url, lenient=True)
            if not data:
                raise ValueError("pas d'image")
            key = hashlib.sha1(ph.url.encode()).hexdigest()
            res = process_image(data, env.photos_dir / "thumbs", key)
            ph.phash, ph.width, ph.height, ph.thumb_path = res["phash"], res["width"], res["height"], res["thumb_path"]
            stats["traitees"] += 1
        except Exception:  # noqa: BLE001
            ph.phash = ""  # vide = téléchargement impossible, on ne réessaie pas
            stats["echecs"] += 1
        if stats["traitees"] % 50 == 0:
            db.commit()
    db.commit()
    return stats
