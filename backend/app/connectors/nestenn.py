"""Connecteur Nestenn (nestenn.com, annonces de toutes les agences du réseau).

Pourquoi un connecteur dédié : nestenn.com ne publie pas de sitemap (`/sitemap.xml` répond 404, aucune
ligne `Sitemap:` dans robots.txt) et les adresses d'annonces (`/maison-de-plain-pied-mondeville-centre-ref-39423437`)
n'ont ni code postal ni département.

Principe (aucun contournement, robots.txt respecté par le client poli) :
1. pages publiques de recherche par département : `/vente/maison/calvados-14`, `/vente/maison/eure-27`…
   (toutes les annonces du département sont sur une seule page) ;
2. chaque carte donne « 27410 MESNIL EN OUCHE » : on ne garde que les communes de la zone (`ZoneIndex.match`) ;
3. la page détail est lue avec l'extracteur générique, corrigé pour ce site (titre, commune, terrain
   « Entre X m² et Y m² », photos de l'annonce seulement, bloc « Autres biens » ignoré).

Configuration d'une source (JSON) :
  departements   segments de département (défaut : calvados-14, eure-27, orne-61)
  types          types de biens (défaut : ["maison"])
  max_listings   garde-fou global (défaut 400)
  zone_filter    false pour désactiver le filtre par commune
"""
from __future__ import annotations

import html as htmllib
import re
from collections.abc import Iterable
from urllib.parse import urljoin

from app.connectors.base import Connector, ListingData, ListingRef, register
from app.extract.html import extract_listing, to_float, visible_text
from app.services.zone import ZoneIndex

DEFAULT_DEPARTMENTS = ["calvados-14", "eure-27", "orne-61"]
_REF = re.compile(r"-ref-(\d+)$")
_CARD_SPLIT = re.compile(r"""<div[^>]+class=["'][^"']*\bbien_item\b""")
_HREF = re.compile(r"""<a\s+href=["']([^"']*-ref-\d+)["']""")
_PLACE = re.compile(r"(\d{5})\s+([^\n<]+?)\s*(?:<|\n)")
_PRICE = re.compile(r"""class=["'][^"']*\bprice\b[^"']*["'][^>]*>\s*([\d\s.]+?)\s*€""")
_LAND_RANGE = re.compile(r"Entre\s+(\d[\d\s.]*?)\s*m²\s+et\s+(\d[\d\s.]*?)\s*m²\s+de\s+terrain", re.I)
_LAND_ONE = re.compile(r"(\d[\d\s.]*?)\s*m²\s+de\s+terrain", re.I)
_RISK = re.compile(r"G[ée]orisques", re.I)


def parse_list_page(page: str, base_url: str = "https://nestenn.com") -> list[dict]:
    """Cartes d'une page de recherche : url, référence, code postal, commune, prix, vendu (bien déjà vendu)."""
    out: list[dict] = []
    seen: set[str] = set()
    for chunk in _CARD_SPLIT.split(page)[1:]:
        h = _HREF.search(chunk)
        if not h:
            continue
        href = htmllib.unescape(h.group(1))
        url = urljoin(base_url.rstrip("/") + "/", href)
        if url in seen:
            continue
        seen.add(url)
        place = _PLACE.search(chunk[h.end():h.end() + 3000])
        price = _PRICE.search(chunk)
        out.append({
            "url": url,
            "ref": _REF.search(href).group(1) if _REF.search(href) else None,
            "postcode": place.group(1) if place else None,
            "place": place.group(2).strip() if place else None,
            "price": int(re.sub(r"\D", "", price.group(1))) if price and re.sub(r"\D", "", price.group(1)) else None,
            "sold": "picto_vendu" in chunk or bool(re.search(r"\bvendu[e]?\b", chunk[h.end():h.end() + 3000], re.I)),
        })
    return out


def _num(s: str) -> float | None:
    return to_float(re.sub(r"[\s.]", "", s))


def parse_detail(page: str, url: str) -> ListingData:
    """Page détail Nestenn -> ListingData (extracteur générique + corrections propres au site)."""
    data = extract_listing(page, url)
    text = visible_text(page)

    m = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S | re.I)
    if m:
        t = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", m.group(1)))).strip()
        if t:
            data.title = t

    ref = _REF.search(url.split("?")[0].rstrip("/"))
    if ref:
        data.external_id = ref.group(1)
        # la page affiche aussi des photos d'autres biens (« Autres biens sur… ») : on garde celles de l'annonce
        own = [p for p in data.photos if ref.group(1) in p]
        if own:
            data.photos = own

    # en-tête de l'annonce : « 27410 MESNIL EN OUCHE » juste après « N° Mandat … »
    loc = re.search(r"N° Mandat[^\n]*\n(?:[^\n]*\n){0,2}?(\d{5})\s+([^\n]+)\n", text)
    if loc:
        data.postal_code = loc.group(1)
        data.extra["commune_site"] = loc.group(2).strip()

    # terrain : « Entre 4335 m² et 4792 m² de terrain » (fourchette) ou « 900 m² de terrain »
    r = _LAND_RANGE.search(text)
    if r:
        lo, hi = _num(r.group(1)), _num(r.group(2))
        if lo and hi:
            data.land = max(lo, hi)
            data.extra["terrain_fourchette"] = [min(lo, hi), max(lo, hi)]
    else:
        o = _LAND_ONE.search(text)
        if o and _num(o.group(1)):
            data.land = _num(o.group(1))

    # description : sans les mentions « Géorisques » répétées
    if data.description:
        data.description = "\n".join(ln for ln in data.description.split("\n") if not _RISK.search(ln)).strip() or data.description

    ag = re.search(r"\n(Agence Nestenn [^\n]+)\n", text)
    if ag:
        data.contact = {"agence": ag.group(1).strip()}
    return data


@register
class NestennConnector(Connector):
    key = "nestenn"
    label = "Nestenn (réseau)"
    kind = "reseau"

    zone: ZoneIndex | None = None  # injecté par le job de collecte

    def _base(self) -> str:
        return (self.config.get("base_url") or "https://nestenn.com").rstrip("/")

    def discover(self) -> Iterable[ListingRef]:
        zone = self.zone
        use_zone = self.config.get("zone_filter", True) and zone is not None
        limit = int(self.config.get("max_listings", 400))
        seen: set[str] = set()
        n = 0
        for dept in self.config.get("departements") or DEFAULT_DEPARTMENTS:
            for ptype in self.config.get("types") or ["maison"]:
                res = self.client.get(f"{self._base()}/vente/{ptype}/{dept}")
                if res.status in (404, 410):
                    continue
                if res.status != 200:
                    raise RuntimeError(f"HTTP {res.status} sur {res.url}")
                for it in parse_list_page(res.text, self._base()):
                    if it["url"] in seen or it["sold"]:  # « Maison vendue » : plus à vendre
                        continue
                    seen.add(it["url"])
                    hit = zone.match(it["place"], it["postcode"]) if use_zone else None
                    if use_zone and not hit:
                        continue
                    hint = {"price": it["price"]}
                    if hit:
                        hint.update(commune_code=hit.commune_code, commune_name=hit.commune_name, postal_code=hit.postal_code)
                    yield ListingRef(url=it["url"], external_id=it["ref"], hint=hint)
                    n += 1
                    if n >= limit:
                        return

    def fetch(self, ref: ListingRef) -> ListingData | None:
        res = self.client.get(ref.url)
        if res.status in (404, 410):
            return None
        if res.status != 200:
            raise RuntimeError(f"HTTP {res.status} sur {ref.url}")
        data = parse_detail(res.text, ref.url)
        h = ref.hint or {}
        data.commune_name = h.get("commune_name") or data.commune_name
        data.postal_code = h.get("postal_code") or data.postal_code
        if h.get("commune_code"):
            data.extra["commune_code"] = h["commune_code"]
        data.external_id = data.external_id or ref.external_id
        return data
