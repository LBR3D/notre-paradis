"""Immonot (annonces de notaires) : connecteur par sitemap + extraction dédiée des fiches.

robots.txt (vérifié) : tout est autorisé sauf /utilisateur/, /account/, /api/, /web-view/ ; pas de crawl-delay.
Le sitemap `annonce_detail_ancien/chunk-N.xml` liste les fiches (~25 000 au total) :
  /immobilier-notaire/detail/<id>/achat-maison-a-vendre-27210-berville-sur-mer-eure.html
Contrairement aux agences, le code postal PRÉCÈDE la commune dans l'adresse (« 14600-honfleur-calvados ») :
`ZoneIndex.match_url` ne sait pas la lire, d'où `match_slug` ci-dessous.

Fiche : JSON-LD (BuyAction -> prix, adresse, photos ; LocalBusiness -> office notarial), bloc
« Caractéristiques » (pièces, chambres, surfaces), classes DPE/GES dans `data-dpe-classe`.
Attention : la géolocalisation du JSON-LD est celle de l'étude, pas du bien : elle est ignorée.

Configuration (JSON) : voir SitemapConnector ; `sitemap_regex`, `url_regex`, `max_listings` suffisent.
"""
from __future__ import annotations

import html as htmllib
import json
import re
from collections.abc import Iterable

from app.connectors.base import ListingData, ListingRef, register
from app.connectors.sitemap import SitemapConnector
from app.extract.html import extract_listing, jsonld, meta, parse_property_type, parse_year, to_float, to_int
from app.extract.notarial import parse_heating, parse_honoraires, parse_outbuildings, parse_sewage, parse_tax
from app.services.zone import ZoneIndex

_SLUG = re.compile(r"-(\d{5})-([a-z0-9-]+)\.html$")
_ID = re.compile(r"/detail/([^/]+)/")
_FEATURES = re.compile(r'</svg>\s*([^<]+?)\s*</p><p class="text-base font-bold[^"]*">([^<]*)</p>')
_BODY = re.compile(r'<div class="mt-8 whitespace-pre-line leading-relaxed">(.*?)</div>', re.S)
_DPE = re.compile(r'<figure[^>]*data-dpe-classe="([A-G])"[^>]*>\s*<figcaption[^>]*>(.*?)</figcaption>', re.S)
_SPECIFIC_TYPES = {"longère", "manoir", "chaumière", "maison à colombages", "corps de ferme", "moulin"}  # « château » exclu : souvent un nom de commune


def match_slug(zone: ZoneIndex, url: str):
    """Commune de la zone d'après « …-<code postal>-<commune>[-<département>].html »."""
    m = _SLUG.search(url.lower())
    if not m:
        return None
    postal, rest = m.group(1), m.group(2)
    words = rest.split("-")
    for n in range(min(len(words), 9), 0, -1):
        hit = zone.by_key.get(("-".join(words[:n]), postal[:2]))
        if hit:
            from app.services.zone import ZoneHit

            return ZoneHit(hit[0], hit[1], postal)
    return None


def _text(fragment: str) -> str:
    t = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = htmllib.unescape(t)
    return "\n".join(re.sub(r"[ \t  ]+", " ", ln).strip() for ln in t.split("\n")).strip()


def extract_immonot(page: str, url: str) -> ListingData:
    d = extract_listing(page, url)  # base générique (titre, prix, OpenGraph…), corrigée ci-dessous
    d.lat = d.lon = None  # coordonnées = celles de l'étude
    d.year_built = None
    d.dpe = d.ges = None
    d.photos = []
    d.contact = {}

    og = meta(page, "og:title") or ""
    d.title = og or d.title

    # --- JSON-LD : prix, adresse, photos, description, office
    for node in jsonld(page):
        t = node.get("@type")
        types = t if isinstance(t, list) else [t]
        if "BuyAction" in types:
            d.price = to_int(node.get("price")) or d.price
            addr = (node.get("location") or {}).get("address") or {}
            d.postal_code = addr.get("postalCode") or d.postal_code
            d.commune_name = addr.get("addressLocality") or d.commune_name
            obj = node.get("object") or {}
            imgs = obj.get("image") or []
            d.photos = [u for u in (imgs if isinstance(imgs, list) else [imgs]) if isinstance(u, str)]
            if obj.get("description"):
                d.description = obj["description"]
            if obj.get("mpn"):
                d.external_id = obj["mpn"]
        if "LocalBusiness" in types or "Notary" in (node.get("additionalType") or []) or "https://schema.org/Notary" in (node.get("additionalType") or []):
            a = node.get("address") or {}
            d.contact = {
                k: v
                for k, v in {
                    "nom": node.get("name"),
                    "type": "étude notariale",
                    "adresse": ", ".join(x for x in [a.get("streetAddress"), f"{a.get('postalCode', '')} {a.get('addressLocality', '')}".strip()] if x) or None,
                    "telephone": node.get("telephone"),
                    "email": node.get("email"),
                    "url": node.get("url"),
                }.items()
                if v
            }

    # --- bloc « Caractéristiques »
    feats = {htmllib.unescape(k).strip(): htmllib.unescape(v).strip() for k, v in _FEATURES.findall(page)}
    d.extra["caracteristiques"] = feats
    if "Nombre de pièces" in feats:
        d.rooms = to_int(feats["Nombre de pièces"])
    d.bedrooms = to_int(feats.get("Chambres")) if "Chambres" in feats else d.bedrooms
    if "Surface habitable" in feats:
        d.surface = to_float(feats["Surface habitable"])
    if "Surface terrain" in feats:
        d.land = to_float(feats["Surface terrain"])
    if feats.get("Référence"):
        d.extra["reference_etude"] = feats["Référence"]

    # --- description complète de l'annonce (texte du notaire)
    body = _BODY.search(page)
    if body:
        d.description = _text(body.group(1))[:6000]
    desc = d.description or ""

    # --- prix / honoraires
    flat = _text(re.sub(r"<!--.*?-->", "", page[: page.find("Caractéristiques")] if "Caractéristiques" in page else page))
    h = parse_honoraires(flat)
    if h:
        d.fees = h["texte"]
        d.extra["honoraires"] = {k: v for k, v in h.items() if k != "texte"}
        if h.get("net"):
            d.extra["prix_net_vendeur"] = h["net"]
    if re.search(r"\bviager\b", f"{d.title} {desc}", re.I):
        d.extra["viager"] = True  # le prix affiché est alors un bouquet : voir fetch()

    # --- DPE / GES (pastilles graphiques : lettre dans data-dpe-classe)
    for letter, caption in _DPE.findall(page):
        if re.search(r"gaz à effet de serre|GES", caption):
            d.ges = d.ges or letter
        elif re.search(r"performance", caption, re.I):
            d.dpe = d.dpe or letter

    # --- champs tirés du texte libre
    d.year_built = parse_year(desc)
    d.heating = parse_heating(desc)
    d.sewage = parse_sewage(desc)
    d.outbuildings = parse_outbuildings(desc)
    d.property_tax = parse_tax(desc)
    spec = parse_property_type(desc[:400])
    d.property_type = spec if spec in _SPECIFIC_TYPES else (parse_property_type(og.split(" à vendre")[0]) or d.property_type)

    # --- photos de secours (sans les annonces voisines ni les logos)
    if not d.photos:
        seen = set()
        for p in extract_listing(page, url).photos:
            if "/immonot/photo/" in p and p not in seen:
                seen.add(p)
                d.photos.append(p)
    d.extraction_method = "parser"
    return d


@register
class ImmonotConnector(SitemapConnector):
    key = "immonot"
    label = "Immonot (notaires)"
    kind = "notaire"

    def discover(self) -> Iterable[ListingRef]:
        zone = self.zone
        limit = int(self.config.get("max_listings", 400))
        n = 0
        seen: set[str] = set()
        for sm in self._sitemap_urls():
            for url in self._walk(sm):
                if url in seen or not self.accepts(url):
                    continue
                seen.add(url)
                hit = match_slug(zone, url) if zone is not None else None
                if zone is not None and not hit:
                    continue
                ident = _ID.search(url)
                yield ListingRef(
                    url=url,
                    external_id=ident.group(1) if ident else None,
                    hint={"commune_code": hit.commune_code, "commune_name": hit.commune_name, "postal_code": hit.postal_code} if hit else {},
                )
                n += 1
                if n >= limit:
                    return

    def fetch(self, ref: ListingRef) -> ListingData | None:
        res = self.client.get(ref.url)
        if res.status in (404, 410):
            return None
        if res.status != 200:
            raise RuntimeError(f"HTTP {res.status} sur {ref.url}")
        data = extract_immonot(res.text, ref.url)
        if data.extra.get("viager"):
            return None  # viager : le prix affiché est un bouquet, pas un prix de vente
        h = ref.hint or {}
        data.commune_name = h.get("commune_name") or data.commune_name
        data.postal_code = h.get("postal_code") or data.postal_code
        if h.get("commune_code"):
            data.extra["commune_code"] = h["commune_code"]
        data.external_id = ref.external_id or data.external_id
        return data
