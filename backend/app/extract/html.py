"""Extracteur générique : une page d'annonce -> `ListingData`, sans clé d'API.

Sources d'information, de la plus fiable à la moins fiable :
1. données structurées JSON-LD (schema.org) ;
2. balises OpenGraph (titre, image, description) ;
3. clés JavaScript intégrées à la page (`surfaceBien: "142"`, `nbPieces: 7`…) ;
4. expressions régulières sur le texte (« 142 m² », « 410 000 € », « 5 chambres »…).

Un connecteur peut surcharger ce qui est mal lu ; l'extraction par LLM (extract/llm.py)
complète les champs qui manquent quand une clé d'API est configurée.
"""
from __future__ import annotations

import html as htmllib
import json
import re
from urllib.parse import urljoin

from app.connectors.base import ListingData

_TAG = re.compile(r"<(script|style|noscript)\b.*?</\1>", re.S | re.I)
# balise HTML, y compris quand un attribut entre guillemets contient « > » (ex. x-on:click="a > b")
_ANYTAG = re.compile(r"""<(?:[^>"']|"[^"]*"|'[^']*')*>""")
_WS = re.compile(r"[ \t\r\f\v  ]+")

LEGAL = re.compile(r"vos donn[ée]es|cookies?|consentement|RGPD|mentions l[ée]gales|politique de|droit d.acc[èe]s|informations recueillies|J.accepte|CNIL|G[ée]orisques|Estimation du co[ûu]t|newsletter|e-mail|inscri|Notre [ée]quipe", re.I)
IMG_EXT = re.compile(r"\.(?:jpe?g|png|webp)(?:\?|$)", re.I)
BAD_IMG = re.compile(r"logo|sprite|icon|favicon|avatar|placeholder|pixel|banner|agence-|/agences?/", re.I)


def visible_text(page: str) -> str:
    """Texte lisible d'une page (sans scripts ni balises)."""
    t = _TAG.sub(" ", page)
    t = re.sub(r"<(br|/p|/div|/li|/h\d|/tr)[^>]*>", "\n", t, flags=re.I)
    t = _ANYTAG.sub(" ", t)
    t = htmllib.unescape(t)
    lines = [_WS.sub(" ", ln).strip() for ln in t.split("\n")]
    return "\n".join(ln for ln in lines if ln)


def meta(page: str, name: str) -> str | None:
    for m in re.finditer(r"<meta\b[^>]*>", page, re.I):
        tag = m.group(0)
        if re.search(rf"""(?:property|name)\s*=\s*["']{re.escape(name)}["']""", tag, re.I):
            c = re.search(r"""content\s*=\s*"([^"]*)"|content\s*=\s*'([^']*)'""", tag, re.I)
            if c:
                return htmllib.unescape(c.group(1) or c.group(2)).strip()
    return None


def jsonld(page: str) -> list[dict]:
    out: list[dict] = []
    for m in re.finditer(r"""<script[^>]+type=["']application/ld\+json["'][^>]*>(.*?)</script>""", page, re.S | re.I):
        try:
            data = json.loads(m.group(1).strip())
        except ValueError:
            continue
        stack = [data]
        while stack:
            x = stack.pop()
            if isinstance(x, list):
                stack.extend(x)
            elif isinstance(x, dict):
                out.append(x)
                if "@graph" in x:
                    stack.extend(x["@graph"] if isinstance(x["@graph"], list) else [x["@graph"]])
    return out


def to_int(v) -> int | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return int(v)
    s = re.sub(r"[^\d,.]", "", str(v).replace(" ", ""))
    if not s:
        return None
    s = s.split(",")[0] if "," in s and "." not in s else s
    try:
        return int(float(s))
    except ValueError:
        return None


def to_float(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(" ", "").replace(" ", "").replace(",", ".")
    m = re.search(r"\d+(?:\.\d+)?", s)
    return float(m.group(0)) if m else None


def js_value(page: str, *keys: str) -> str | None:
    """Valeur d'une clé JavaScript/JSON intégrée : `surfaceBien: "142"` ou `"nbPieces":7`."""
    for k in keys:
        m = re.search(rf"""["']?\b{re.escape(k)}["']?\s*[:=]\s*(?:"([^"]*)"|'([^']*)'|(-?[\d.]+))""", page)
        if m:
            v = next((g for g in m.groups() if g is not None), None)
            if v not in (None, ""):
                return v
    return None


def parse_price(text: str) -> int | None:
    best = None
    for m in re.finditer(r"(\d{1,3}(?:[   .]\d{3})+|\d{4,8})\s*(?:€|euros?|eur\b)", text, re.I):
        v = to_int(re.sub(r"[   .]", "", m.group(1)))
        if v and 20_000 <= v <= 20_000_000:
            best = best or v
    return best


def parse_surface(text: str) -> float | None:
    for m in re.finditer(r"(\d{2,4}(?:[,.]\d+)?)\s*(?:m²|m2|m\s*²)", text, re.I):
        v = to_float(m.group(1))
        if v and 15 <= v <= 2000:
            return v
    return None


def parse_land(text: str) -> float | None:
    m = re.search(r"(?:terrain|parcelle|jardin)[^\n\d]{0,40}?(\d[\d  .]*(?:[,.]\d+)?)\s*(m²|m2|ha|hectares?|a\b)", text, re.I)
    if not m:
        m2 = re.search(r"(\d[\d  .]*(?:[,.]\d+)?)\s*(m²|m2|ha)\s*(?:de\s*)?(?:terrain|parcelle)", text, re.I)
        m = m2
    if not m:
        return None
    raw = re.sub(r"[  ]", "", m.group(1))
    raw = raw.replace(".", "") if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", raw) else raw
    v = to_float(raw)
    unit = m.group(2).lower()
    if v is None:
        return None
    return v * 10_000 if unit.startswith("ha") or unit.startswith("hect") else v


def parse_count(text: str, *words: str) -> int | None:
    for w in words:
        m = re.search(rf"(\d{{1,2}})\s*{w}", text, re.I)
        if m:
            return int(m.group(1))
    return None


def parse_letter(text: str, label: str) -> str | None:
    m = re.search(rf"{label}[^A-Za-z\n]{{0,40}}\b([A-G])\b(?![\'’])", text)
    return m.group(1) if m else None


def labeled_value(text: str, label: str) -> str | None:
    """Valeur d'une fiche « libellé / valeur » : `Nombre de chambre(s)\\n3` ou `Chambres : 3` (une ligne par champ)."""
    m = re.search(rf"^[ \t]*(?:{label})[ \t]*(?::[ \t]*|\n[ \t]*)([^\n]{{1,80}})$", text, re.I | re.M)
    return m.group(1).strip() if m else None


def parse_year(text: str) -> int | None:
    m = re.search(r"(?:construit|construction|(?<!l')(?<!l’)\bann[ée]e\b(?!\s+de\s+r[ée]f))[^\d\n]{0,30}((?:1[5-9]|20)\d{2})", text, re.I)  # « années 2021 » (DPE) exclu
    return int(m.group(1)) if m else None


def parse_property_type(text: str) -> str | None:
    t = text.lower()
    for key, label in [
        ("longère", "longère"), ("longere", "longère"), ("manoir", "manoir"), ("château", "château"),
        ("chaumière", "chaumière"), ("colombage", "maison à colombages"), ("corps de ferme", "corps de ferme"),
        ("ferme", "ferme"), ("propriété", "propriété"), ("moulin", "moulin"), ("villa", "villa"),
        ("maison", "maison"), ("terrain", "terrain"), ("appartement", "appartement"),
    ]:
        if key in t:
            return label
    return None


def photos_from_page(page: str, base_url: str, limit: int = 40) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()

    def add(u: str | None):
        if not u:
            return
        u = htmllib.unescape(u.strip()).replace("\\/", "/")
        if u.startswith("//"):
            u = "https:" + u
        u = urljoin(base_url, u)
        key = u.split("?")[0]
        if u.startswith("http") and key not in seen and not BAD_IMG.search(u):
            seen.add(key)
            urls.append(u)

    add(meta(page, "og:image"))
    for d in jsonld(page):
        im = d.get("image")
        for x in im if isinstance(im, list) else [im]:
            add(x.get("url") if isinstance(x, dict) else x)
    for m in re.finditer(r"""(?:src|data-src|data-lazy|data-original|href|content)\s*=\s*["']([^"']+)["']""", page):
        if IMG_EXT.search(m.group(1)) and re.search(r"photo|image|media|upload|annonce|cloudimg|sweepbright|bien|estate", m.group(1), re.I):
            add(m.group(1))
    for m in re.finditer(r"""["'](https?:\\?/\\?/[^"'\s]+?\.(?:jpe?g|png|webp)[^"'\s]*)["']""", page, re.I):
        add(m.group(1))
    return urls[:limit]


def _from_jsonld(items: list[dict], data: ListingData) -> None:
    for d in items:
        t = d.get("@type")
        types = t if isinstance(t, list) else [t]
        if not any(x in ("Product", "RealEstateListing", "House", "SingleFamilyResidence", "Residence", "Offer", "Apartment") for x in types):
            continue
        data.title = data.title or d.get("name")
        data.description = data.description or d.get("description")
        offer = d.get("offers") or d
        if isinstance(offer, list):
            offer = offer[0] if offer else {}
        if isinstance(offer, dict):
            data.price = data.price or to_int(offer.get("price"))
        fs = d.get("floorSize")
        if isinstance(fs, dict):
            data.surface = data.surface or to_float(fs.get("value"))
        data.rooms = data.rooms or to_int(d.get("numberOfRooms"))
        data.bedrooms = data.bedrooms or to_int(d.get("numberOfBedrooms"))
        addr = d.get("address")
        if isinstance(addr, dict):
            data.commune_name = data.commune_name or addr.get("addressLocality")
            data.postal_code = data.postal_code or addr.get("postalCode")
            data.address = data.address or addr.get("streetAddress")
        geo = d.get("geo")
        if isinstance(geo, dict):
            data.lat = data.lat or to_float(geo.get("latitude"))
            data.lon = data.lon or to_float(geo.get("longitude"))


def extract_listing(page: str, url: str) -> ListingData:
    """Extraction générique. Ne lève pas d'exception : les champs introuvables restent vides."""
    data = ListingData(url=url)
    text = visible_text(page)
    og_title = meta(page, "og:title")
    og_desc = meta(page, "og:description") or meta(page, "description")
    title = re.sub(r"\s*[|\-–]\s*[^|\-–]{2,40}$", "", og_title) if og_title else None
    data.title = title or None

    _from_jsonld(jsonld(page), data)

    # clés JS intégrées
    data.surface = data.surface or to_float(js_value(page, "surfaceBien", "surfaceHabitable", "surface_habitable", "livingArea", "surface"))
    data.land = data.land or to_float(js_value(page, "surfaceTerrain", "surface_terrain", "landArea", "terrain"))
    data.rooms = data.rooms or to_int(js_value(page, "nbPieces", "nb_pieces", "rooms", "pieces"))
    data.bedrooms = data.bedrooms or to_int(js_value(page, "nbChambres", "nb_chambres", "bedrooms", "chambres"))
    data.year_built = data.year_built or to_int(js_value(page, "anneeConstruction", "annee_construction", "yearBuilt"))
    data.price = data.price or to_int(js_value(page, "prix", "price", "prixBien", "prix_vente"))
    lat = to_float((js_value(page, "latitude", "lat") or "").replace("-", ".") if js_value(page, "latitude", "lat") and re.fullmatch(r"\d+-\d+", js_value(page, "latitude", "lat") or "") else js_value(page, "latitude", "lat"))
    lon_raw = js_value(page, "longitude", "lng", "lon")
    lon = to_float(lon_raw.replace("-", ".") if lon_raw and re.fullmatch(r"-?\d+-\d+", lon_raw) else lon_raw)
    if lat and lon and 41 < lat < 52 and -6 < lon < 10:
        data.lat = data.lat or lat
        data.lon = data.lon or lon

    # texte visible
    blob = "\n".join(x for x in [og_title, og_desc, text] if x)
    data.price = data.price or parse_price(og_title or "") or parse_price(blob)
    data.surface = data.surface or parse_surface(og_title or "") or parse_surface(blob)
    data.land = data.land or parse_land(blob)
    # fiches « libellé / valeur » (Nombre de chambre(s) : 3), plus fiables que la prose
    data.bedrooms = data.bedrooms or to_int(labeled_value(text, r"Nombre de chambres?(?:\(s\))?|Nb de chambres?"))
    data.rooms = data.rooms or to_int(labeled_value(text, r"Nombre de pi[èe]ces?(?:\(s\))?"))
    yr = to_int(labeled_value(text, r"Ann[ée]e de construction|Ann[ée]e construction"))
    data.year_built = data.year_built or (yr if yr and 1500 <= yr <= 2030 else None)
    data.property_tax = data.property_tax or to_int(labeled_value(text, r"Taxe fonci[èe]re(?: annuelle)?"))
    data.heating = data.heating or labeled_value(text, r"Mode de chauffage|Chauffage")
    cp = labeled_value(text, r"Code postal")
    data.postal_code = data.postal_code or (cp if cp and re.fullmatch(r"\d{5}", cp) else None)
    data.rooms = data.rooms or parse_count(blob, r"pi[èe]ces?")
    data.bedrooms = data.bedrooms or parse_count(blob, r"chambres?")
    data.bedrooms = data.bedrooms or to_int(labeled_value(text, r"Chambres?(?:\(s\))?"))  # dernier recours
    data.year_built = data.year_built or parse_year(blob)
    data.dpe = parse_letter(blob, r"(?:DPE|[ÉE]nergie|(?i:classe [ée]nergie)|[ÉE]tiquette [ÉE]nergie)")
    data.ges = parse_letter(blob, r"(?:GES|[ÉE]missions?|(?i:classe climat))")
    if not data.dpe:
        d = js_value(page, "dpe", "classeEnergie")
        if d and d.upper() in list("ABCDEFG"):
            data.dpe = d.upper()
    data.property_type = parse_property_type(og_title or data.title or "") or parse_property_type(url)
    data.description = data.description or og_desc

    # description longue : premiers paragraphes de texte qui ne sont pas du juridique / du formulaire
    paras = [p for p in text.split("\n") if len(p) > 100 and not LEGAL.search(p)]
    if paras:
        long = "\n".join(paras[:4])
        if not data.description or len(long) > len(data.description):
            data.description = long[:6000]

    data.photos = photos_from_page(page, url)
    data.extraction_method = "parser"
    return data


MISSING_KEY_FIELDS = ("price", "surface", "land", "bedrooms", "commune_name")


def missing_fields(d: ListingData) -> list[str]:
    return [f for f in MISSING_KEY_FIELDS if getattr(d, f) in (None, "")]
