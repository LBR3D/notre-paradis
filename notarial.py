"""Aides d'extraction propres aux annonces de notaires (honoraires, chauffage, assainissement…).

Les annonces de notaires sont rédigées en texte libre : ces fonctions en tirent des champs
structurés, sans jamais inventer (valeur absente => None).
"""
from __future__ import annotations

import re

_NUM = r"\d[\d  .]*(?:[,.]\d+)?"


def _int(s: str) -> int:
    return int(re.sub(r"[^\d]", "", s.split(",")[0]))


def parse_honoraires(text: str) -> dict:
    """« 200 000 € + Honoraires de négociation TTC : 6 840 €. Soit 3.42% à la charge de l'acquéreur ».

    Renvoie {"net": 200000, "honoraires": 6840, "taux": 3.42, "charge": "acquéreur", "texte": "…"} (clés présentes si lues).
    """
    out: dict = {}
    m = re.search(
        rf"(?:({_NUM})\s*€\s*\+\s*)?honoraires?\s+(?:de\s+)?(?:n[ée]gociation\s*)?(TTC|HT)?\s*:?\s*({_NUM})\s*€"
        r"(?:\.?\s*soit\s+([\d.,]+)\s*%\s*(?:TTC\s*)?[àa]\s+la\s+charge\s+(?:de\s+l['’]|du\s+|de\s+)\s*(acqu[ée]reur|vendeur))?",
        text,
        re.I,
    )
    if not m:
        return out
    if m.group(1):
        out["net"] = _int(m.group(1))
    out["honoraires"] = _int(m.group(3))
    taxe = (m.group(2) or "TTC").upper()
    out["texte"] = f"Honoraires {taxe} : {out['honoraires']:,} €".replace(",", " ")
    if m.group(4):
        out["taux"] = float(m.group(4).replace(",", "."))
        out["charge"] = m.group(5).lower().replace("é", "e")
        who = "de l'acquéreur" if out["charge"].startswith("acq") else "du vendeur"
        out["texte"] += f" ({m.group(4).replace(',', '.')} % à la charge {who})"
    return out


def parse_heating(text: str) -> str | None:
    kinds = re.search(
        r"chauffage[^.;\n]{0,30}?(fioul|mazout|gaz(?: de ville| naturel)?|[ée]lectrique|bois|granul[ée]s|pompe [àa] chaleur|g[ée]othermie|po[êe]le)", text, re.I
    ) or re.search(r"chaudi[èe]re\s+(?:\w+\s+){0,2}?(fioul|mazout|gaz|bois|granul[ée]s|[ée]lectrique)", text, re.I) or re.search(
        r"(pompe [àa] chaleur|po[êe]le [àa] (?:bois|granul[ée]s))", text, re.I
    )
    if kinds:
        return re.sub(r"\s+", " ", kinds.group(0)).strip()[:120]
    return None


def parse_sewage(text: str) -> str | None:
    m = re.search(
        r"(tout[- ]?[àa][- ]?l.[ée]gout|assainissement\s+(?:individuel|collectif|non collectif|autonome)|fosse\s+septique|micro[- ]?station|fosse\s+toutes\s+eaux)",
        text,
        re.I,
    )
    return m.group(1).lower() if m else None


def parse_outbuildings(text: str) -> str | None:
    found = []
    for key in ("garage", "dépendance", "grange", "cave", "atelier", "étang", "piscine", "puits", "chai", "four à pain", "pigeonnier", "écurie", "verger", "gîte"):
        if re.search(rf"\b{key}s?\b", text, re.I):
            found.append(key)
    return ", ".join(found) or None


def parse_tax(text: str) -> int | None:
    m = re.search(rf"(?:taxe fonci[èe]re|\bTF\b)\s*(?:de|:)?\s*({_NUM})\s*(?:€|euros?)", text, re.I)
    return _int(m.group(1)) if m else None


def parse_land_text(text: str) -> float | None:
    """« 1 hectare, 77 ares et 20 centiares » ou « 90 407 m² de terrain » -> m²."""
    m = re.search(r"(\d+)\s*(?:ha|hectares?)\b(?:[\s,]+(?:et\s+)?(\d+)\s*(?:ares?|a)\b)?(?:[\s,]+(?:et\s+)?(\d+)\s*(?:centiares?|ca)\b)?", text, re.I)
    if m:
        return int(m.group(1)) * 10_000 + int(m.group(2) or 0) * 100 + int(m.group(3) or 0)
    m = re.search(rf"({_NUM})\s*m[²2]\s*(?:de\s*)?(?:terrain|parcelle|jardin)", text, re.I)
    return float(re.sub(r"[  ]", "", m.group(1)).replace(",", ".")) if m else None
