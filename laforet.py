"""Laforêt (laforet.com) : sitemap des annonces + lecture dédiée de la page détail.

- robots.txt : ni `/agence-immobiliere/…/acheter/…` ni le sitemap ne sont interdits.
- Le sitemap `storage/sitemaps/produits.xml` liste toutes les annonces (vente et location) sous la forme
  `/agence-immobiliere/<agence>/acheter/<ville>/<type>-<n>-pieces-<identifiant>`. L'adresse ne contient PAS
  de code postal, et `<ville>` est une ville de référence (« près de Lisieux ») qui n'est pas toujours la
  commune réelle du bien. On présélectionne donc sur la ville de l'adresse (communes de la zone), puis on
  confirme avec la commune et le code postal lus dans la page (fil d'Ariane + dataLayer) : hors zone => ignorée.
- Limite connue : une annonce dont la ville de référence est hors zone alors que la commune réelle est dans
  la zone n'est pas vue (option `agences` pour ajouter toutes les annonces d'agences voisines, plus coûteux).

Configuration (en plus de celle de `sitemap`) :
  agences   liste d'identifiants d'agences (ex. ["bernay", "pontaudemer"]) dont on ouvre toutes les maisons
"""
from __future__ import annotations

import html as htmllib
import json
import re
from collections.abc import Iterable

from app.connectors.base import ListingData, ListingRef, register
from app.connectors.sitemap import SitemapConnector
from app.extract.html import extract_listing, meta, to_float, to_int

_URL = re.compile(r"/agence-immobiliere/(?P<agence>[^/]+)/acheter/(?P<ville>[^/]+)/(?P<type>[a-z-]+?)(?:-\d+-pieces?)?-(?P<id>\d+)/?$")
_INTRO = re.compile(r"^\s*Votre Agence Laforêt vous accueille[^\n]*\n?", re.I)  # horaires d'accueil de l'agence
_BR = re.compile(r"<br\s*/?>", re.I)


def _item(page: str, listing_id: str) -> dict:
    """Objet dataLayer `viewItem` de CETTE annonce (la page contient aussi des annonces similaires)."""
    m = re.search(rf'"itemId":{re.escape(listing_id)}[,}}]', page)
    if not m:
        return {}
    start = page.rfind("{", 0, m.start())
    end = page.find("}", m.end() - 1)
    try:
        return json.loads(page[start : end + 1])
    except ValueError:
        return {}


def _description(page: str) -> str | None:
    m = re.search(r'data-title="([^"]{40,})"', page)
    if not m:
        return None
    t = htmllib.unescape(m.group(1))
    t = _BR.sub("\n", t)
    t = re.split(r"\n\s*REF\s*:", t, maxsplit=1)[0]
    t = "\n".join(re.sub(r"[ \t\xa0]+", " ", ln).strip() for ln in t.split("\n"))
    t = _INTRO.sub("", t.strip())
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    return t or None


@register
class LaforetConnector(SitemapConnector):
    key = "laforet"
    label = "Laforêt (réseau)"
    kind = "reseau"

    def _zone_slugs(self) -> set[str]:
        return {k[0] for k in self.zone.by_key} if self.zone else set()

    def discover(self) -> Iterable[ListingRef]:
        use_zone = self.config.get("zone_filter", True) and self.zone is not None
        slugs = self._zone_slugs() if use_zone else set()
        agences = set(self.config.get("agences") or [])
        limit = int(self.config.get("max_listings", 400))
        n = 0
        seen: set[str] = set()
        for sm in self._sitemap_urls():
            for url in self._walk(sm):
                if url in seen or not self.accepts(url):
                    continue
                m = _URL.search(url)
                if not m:
                    continue
                if use_zone and m["ville"] not in slugs and m["agence"] not in agences:
                    continue
                seen.add(url)
                yield ListingRef(url=url, external_id=m["id"])
                n += 1
                if n >= limit:
                    return

    def fetch(self, ref: ListingRef) -> ListingData | None:
        res = self.client.get(ref.url)
        if res.status in (404, 410):
            return None
        if res.status != 200:
            raise RuntimeError(f"HTTP {res.status} sur {ref.url}")
        return self.parse(res.text, ref)

    def parse(self, page: str, ref: ListingRef) -> ListingData | None:
        m = _URL.search(ref.url)
        lid = (m["id"] if m else None) or ref.external_id
        data = extract_listing(page, ref.url)  # base : titre, photos, etc. ; on corrige avec les données propres au site
        data.external_id = lid
        item = _item(page, lid) if lid else {}

        # commune réelle : fil d'Ariane « /ville/achat-maison-<commune>-<cp> », sinon dataLayer
        crumb = re.search(r'href="/ville/achat-[a-z-]+?-(\d{5})"[^>]*>\s*([^<]+?)\s*</a>', page)
        postal = (crumb.group(1) if crumb else None) or item.get("itemZipcode")
        name = htmllib.unescape(crumb.group(2)) if crumb else (item.get("itemCity") or "").title() or None
        hit = None
        if self.zone:
            hit = self.zone.match(name, postal) or self.zone.match(item.get("itemCity"), item.get("itemZipcode"))
            if not hit:
                return None  # commune réelle hors zone
        data.commune_name = hit.commune_name if hit else name
        data.postal_code = postal
        if hit:
            data.extra["commune_code"] = hit.commune_code

        t = re.sub(r"\s+", " ", htmllib.unescape(meta(page, "og:title") or "")).strip()
        data.title = t or data.title
        if item.get("itemType"):
            data.property_type = str(item["itemType"]).lower()
        data.price = to_int(item.get("itemPrice")) or data.price
        data.surface = to_float(item.get("itemSize")) or data.surface
        data.rooms = to_int(item.get("itemRoomsNb")) or data.rooms

        text = htmllib.unescape(page)
        land = re.search(r"Surf\.\s*terrain\s*:\s*([\d\s ]+?)\s*m²", text)
        data.land = to_float(land.group(1).replace(" ", "").replace(" ", "")) if land else None
        ch = re.search(r"(\d+)\s*chbres?", text) or re.search(r"(\d+)\s*chambres", item.get("itemCriteria") or "")
        data.bedrooms = int(ch.group(1)) if ch else data.bedrooms
        heat = re.search(r"<span>\s*Chauffage\s+([^<]+?)\s*</span>", text)
        data.heating = heat.group(1) if heat else None
        fees = re.search(r"Honoraires à la charge (?:du vendeur|de l'acquéreur)", text)
        data.fees = fees.group(0) if fees else None

        desc = _description(page)
        data.description = desc or data.description
        data.year_built = None
        if desc:
            y = re.search(r"construit[e]?\s+en\s+((?:1[5-9]|20)\d{2})", desc, re.I)
            data.year_built = int(y.group(1)) if y else None

        # photos de CETTE annonce uniquement (les annonces similaires ont d'autres identifiants)
        og = [htmllib.unescape(x) for x in re.findall(r'<meta property="og:image(?:_\d+)?" content="([^"]+)"', page)]
        own = [u for u in dict.fromkeys(og) if lid and lid in u]
        data.photos = own or [p for p in data.photos if lid and lid in p]

        center = re.search(r'data-map-center-value="\{"lat":([\d.]+),"lng":(-?[\d.]+)\}"', text)
        if center:  # centre de la zone d'affichage (position approximative, volontairement floue)
            data.extra["map_center"] = [float(center.group(1)), float(center.group(2))]
        agence = re.search(r"\|\s*(Laforêt [^⇔<|]+?)\s*⇔", text)
        if agence:
            data.contact = {"agence": agence.group(1)}
        return data
