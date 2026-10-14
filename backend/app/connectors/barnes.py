"""Barnes International (barnes-international.com) : connecteur dédié.

Constat (robots.txt relu le jour de l'écriture) :
- pas de sitemap publié (`/sitemap.xml` renvoie la page d'accueil, aucun `Sitemap:` dans robots.txt) ;
- robots.txt interdit les pages de recherche (`/*search*`, `/*?search`, `/*&search`, `/*modals*`, `/*/map.html*`)
  mais autorise les pages de « vitrine » par territoire (`/fr/vente/france/calvados.html`, paginées par `?page=N`)
  et les fiches (`/fr/vente/france/<commune>/ref-APM-<n>.html`).
- l'adresse d'une fiche contient la commune (sans code postal, et sans apostrophe : « pont-leveque »).

Principe : on parcourt les vitrines départementales (Calvados, Eure, Orne), on relève les adresses de fiches,
on garde celles dont la commune est dans la zone, puis on ouvre chaque fiche.

Attention : `urllib.robotparser` ignore les jokers (`*`) de robots.txt ; ce connecteur applique donc lui-même
les règles `search` / `modals` / `map.html` en plus du client poli (on ne suit jamais un lien qui les contient).

Configuration :
  listing_pages  liste de {"url": vitrine, "dep": "14"} (le département sert à reconnaître la commune)
  max_pages      pages de vitrine suivies au plus, par vitrine (défaut 12)
  max_listings   garde-fou (défaut 300)
  zone_filter    false pour ne pas filtrer par commune
"""
from __future__ import annotations

import html as htmllib
import re
from collections.abc import Iterable
from urllib.parse import urljoin

from app.connectors.base import ListingData, ListingRef, register
from app.connectors.sitemap import SitemapConnector
from app.extract.html import extract_listing

FICHE = re.compile(r"/fr/vente/france/([a-z0-9-]+)/ref-([A-Za-z0-9-]+)\.html")
NEXT_LINK = re.compile(r"""<a\b[^>]*\brel\s*=\s*["']next["'][^>]*>""", re.I)
HREF = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.I)
FORBIDDEN = re.compile(r"search|modals|/map\.html|/_archives/")  # règles de robots.txt avec jokers
PHOTO_FOLDER = re.compile(r"/bdata/property/[^/]+/([0-9a-f-]{36})/")


def _flat(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


@register
class BarnesConnector(SitemapConnector):
    key = "barnes"
    label = "Barnes International"
    kind = "reseau"

    # ------------------------------------------------------------ découverte
    def _page(self, url: str) -> str | None:
        if FORBIDDEN.search(url):
            return None
        res = self.client.get(url)
        return res.text if res.status == 200 else None

    def _lookup(self):
        """(slug sans tirets, département) -> (code INSEE, nom)."""
        if self.zone is None:
            return None
        return {(_flat(slug), dep): v for (slug, dep), v in self.zone.by_key.items()}

    def discover(self) -> Iterable[ListingRef]:
        limit = int(self.config.get("max_listings", 300))
        max_pages = int(self.config.get("max_pages", 12))
        use_zone = self.config.get("zone_filter", True) and self.zone is not None
        lookup = self._lookup() if use_zone else None
        seen: set[str] = set()
        n = 0
        for lp in self.config.get("listing_pages", []):
            dep = str(lp.get("dep", ""))
            url: str | None = lp["url"]
            for _ in range(max_pages):
                if not url:
                    break
                page = self._page(url)
                if not page:
                    break
                for m in FICHE.finditer(page):
                    slug, ref = m.group(1), m.group(2)
                    furl = urljoin(url, m.group(0))
                    if furl in seen or FORBIDDEN.search(furl):
                        continue
                    seen.add(furl)
                    hit = lookup.get((_flat(slug), dep)) if lookup is not None else None
                    if lookup is not None and not hit:
                        continue
                    hint = {"commune_code": hit[0], "commune_name": hit[1]} if hit else {}
                    yield ListingRef(url=furl, external_id=ref, hint=hint)
                    n += 1
                    if n >= limit:
                        return
                url = self._next_page(page, url)

    @staticmethod
    def _next_page(page: str, base: str) -> str | None:
        m = NEXT_LINK.search(page)
        if not m:
            return None
        h = HREF.search(m.group(0))
        if not h:
            return None
        nxt = urljoin(base, htmllib.unescape(h.group(1)))
        return None if FORBIDDEN.search(nxt) or nxt == base else nxt

    # ---------------------------------------------------------------- fiche
    def fetch(self, ref: ListingRef) -> ListingData | None:
        res = self.client.get(ref.url)
        if res.status in (404, 410):
            return None
        if res.status != 200:
            raise RuntimeError(f"HTTP {res.status} sur {ref.url}")
        data = extract_listing(res.text, ref.url)
        h = ref.hint or {}
        data.commune_name = h.get("commune_name") or data.commune_name
        if h.get("commune_code"):
            data.extra["commune_code"] = h["commune_code"]
        data.external_id = ref.external_id or data.external_id
        # ne garder que les photos du bien (dossier « property/<mois>/<uuid> »), pas le portrait du conseiller
        first = next((PHOTO_FOLDER.search(p) for p in data.photos if PHOTO_FOLDER.search(p)), None)
        if first:
            data.photos = [p for p in data.photos if first.group(1) in p]
        return data
