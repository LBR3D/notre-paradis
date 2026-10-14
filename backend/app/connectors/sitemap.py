"""Connecteur générique par sitemap, pour les sites d'agences et de réseaux.

Principe : le site publie un sitemap listant toutes ses annonces. Les adresses contiennent
presque toujours « commune-codepostal » : on ne retient que celles de la zone (ZoneIndex),
puis on ouvre chacune avec l'extracteur générique. Aucun contournement : le client poli
respecte robots.txt et le délai du site.

Configuration d'une source (JSON) :
  sitemaps       liste d'adresses de sitemaps (ou index de sitemaps) ; défaut : <site>/sitemap.xml
  url_regex      expression qui doit correspondre à l'adresse d'une annonce de vente
  exclude_regex  adresses à ignorer (location, programmes neufs…)
  max_listings   garde-fou (défaut 400)
  photo_filter_uuid  ne garder que les photos dont l'adresse contient l'identifiant (UUID) de l'annonce
  zone_filter    false pour désactiver le filtre par commune (petites agences locales)
"""
from __future__ import annotations

import gzip
import re
from collections.abc import Iterable
from xml.etree import ElementTree as ET

from app.connectors.base import Connector, ListingData, ListingRef, register
from app.extract.html import extract_listing
from app.services.zone import ZoneIndex

_NS = re.compile(r"\{[^}]+\}")


def parse_sitemap(raw: bytes) -> tuple[list[str], list[str]]:
    """Renvoie (sous-sitemaps, adresses de pages)."""
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return [], []
    subs: list[str] = []
    pages: list[str] = []
    kind = _NS.sub("", root.tag)
    for el in root.iter():
        if _NS.sub("", el.tag) == "loc" and el.text:
            (subs if kind == "sitemapindex" else pages).append(el.text.strip())
    return subs, pages


@register
class SitemapConnector(Connector):
    key = "sitemap"
    label = "Site d'agence (sitemap)"
    kind = "agence"

    zone: ZoneIndex | None = None  # injecté par le job de collecte

    def _sitemap_urls(self) -> list[str]:
        if self.config.get("sitemaps"):
            return list(self.config["sitemaps"])
        base = self.config["base_url"].rstrip("/")
        return [f"{base}/sitemap.xml"]

    def _walk(self, url: str, depth: int = 0) -> Iterable[str]:
        if depth > 3:
            return
        raw = self.client.get_bytes(url)
        if not raw:
            return
        subs, pages = parse_sitemap(raw)
        sub_filter = self.config.get("sitemap_regex")
        for s in subs:
            if sub_filter and not re.search(sub_filter, s):
                continue
            yield from self._walk(s, depth + 1)
        yield from pages

    def accepts(self, url: str) -> bool:
        rx = self.config.get("url_regex")
        ex = self.config.get("exclude_regex")
        if rx and not re.search(rx, url):
            return False
        return not (ex and re.search(ex, url))

    def discover(self) -> Iterable[ListingRef]:
        zone = self.zone
        use_zone = self.config.get("zone_filter", True) and zone is not None
        limit = int(self.config.get("max_listings", 400))
        n = 0
        seen: set[str] = set()
        for sm in self._sitemap_urls():
            for url in self._walk(sm):
                if url in seen or not self.accepts(url):
                    continue
                seen.add(url)
                hit = zone.match_url(url) if use_zone else None
                if use_zone and not hit:
                    continue
                yield ListingRef(url=url, hint={"commune_code": hit.commune_code, "commune_name": hit.commune_name, "postal_code": hit.postal_code} if hit else {})
                n += 1
                if n >= limit:
                    return

    def fetch(self, ref: ListingRef) -> ListingData | None:
        res = self.client.get(ref.url)
        if res.status == 404 or res.status == 410:
            return None
        if res.status != 200:
            raise RuntimeError(f"HTTP {res.status} sur {ref.url}")
        data = extract_listing(res.text, ref.url)
        h = ref.hint or {}
        data.commune_name = data.commune_name or h.get("commune_name")
        data.postal_code = h.get("postal_code") or data.postal_code
        if h.get("commune_code"):
            data.extra["commune_code"] = h["commune_code"]
        data.external_id = data.external_id or ref.external_id
        if self.config.get("photo_filter_uuid"):
            m = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", ref.url)
            if m:
                data.external_id = data.external_id or m.group(1)
                own = [p for p in data.photos if m.group(1) in p]
                if own:
                    data.photos = own
        return data
