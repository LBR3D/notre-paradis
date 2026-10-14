"""Zone de recherche : reconnaître une commune de la zone dans un texte ou une adresse web.

Les sites d'agences écrivent presque toujours la commune et le code postal dans
l'adresse de l'annonce (« …-maison-t7-pont-l-eveque-14130-… »). On s'en sert pour
ne télécharger que les annonces de la zone, sans ouvrir les autres.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session


def slugify(value: str) -> str:
    """« Pont-l'Évêque » -> « pont-l-eveque »."""
    s = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


_POSTAL = re.compile(r"(?<![0-9])(\d{5})(?![0-9])")


@dataclass(frozen=True)
class ZoneHit:
    commune_code: str
    commune_name: str
    postal_code: str | None


class ZoneIndex:
    """Index (nom de commune, département) -> code INSEE, pour les communes de la zone."""

    MAX_WORDS = 7  # « Saint-Martin-de-la-Lieue » = 5 mots, marge incluse

    def __init__(self, rows: list[tuple[str, str, str]]):
        # rows : (code INSEE, nom, département)
        self.by_key: dict[tuple[str, str], tuple[str, str]] = {}
        for code, nom, dep in rows:
            self.by_key[(slugify(nom), dep)] = (code, nom)
            # variantes courantes : « st- » pour « saint- »
            s = slugify(nom)
            if s.startswith("saint-") or s.startswith("sainte-"):
                short = s.replace("saint-", "st-", 1).replace("sainte-", "ste-", 1)
                self.by_key.setdefault((short, dep), (code, nom))

    @classmethod
    def load(cls, db: Session, only_zone: bool = True) -> ZoneIndex:
        sql = "SELECT code, nom, departement FROM commune" + (" WHERE in_zone" if only_zone else "")
        return cls([(r[0], r[1], r[2]) for r in db.execute(text(sql))])

    def __len__(self) -> int:
        return len(self.by_key)

    def match(self, commune_name: str | None, postal_code: str | None) -> ZoneHit | None:
        """Commune connue à partir d'un nom et/ou d'un code postal."""
        if not commune_name:
            return None
        slug = slugify(commune_name)
        deps = [postal_code[:2]] if postal_code and len(postal_code) >= 2 else sorted({d for (_, d) in self.by_key})
        for dep in deps:
            hit = self.by_key.get((slug, dep))
            if hit:
                return ZoneHit(hit[0], hit[1], postal_code)
        return None

    def match_url(self, url: str) -> ZoneHit | None:
        """Cherche « commune-CODEPOSTAL » dans une adresse web ; None si la commune n'est pas dans la zone."""
        path = re.sub(r"^https?://[^/]+", "", url.lower())
        for m in _POSTAL.finditer(path):
            postal = m.group(1)
            words = [w for w in re.split(r"[^a-z0-9]+", path[: m.start()]) if w]
            for n in range(1, self.MAX_WORDS + 1):
                if n > len(words):
                    break
                hit = self.by_key.get(("-".join(words[-n:]), postal[:2]))
                if hit:
                    return ZoneHit(hit[0], hit[1], postal)
        return None

    def match_text(self, content: str) -> ZoneHit | None:
        """Cherche « 14130 Pont-l'Évêque » ou « Pont-l'Évêque (14) » dans un texte libre."""
        for m in re.finditer(r"(\d{5})\s+([A-ZÉÈÊÀÂÎÔÛÇ][\w'’\- éèêàâîôûç]{1,40})", content):
            postal, rest = m.group(1), m.group(2)
            words = re.split(r"\s+", rest.strip())
            for n in range(min(len(words), 5), 0, -1):
                hit = self.match(" ".join(words[:n]), postal)
                if hit:
                    return hit
        return None
