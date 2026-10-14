"""Espaces Atypiques (espaces-atypiques.com) : biens de caractère (manoirs, longères, moulins…).

Constat (robots.txt relu le jour de l'écriture) :
- `Disallow: /*?*` : AUCUNE adresse avec paramètre de requête (filtres, tris) ; `/*/page/1/` et `/*/page/6…20` interdits ;
  `/biens-vendus/` et `/en/sold/` interdits.
- les sitemaps (Yoast, 28 fichiers « vente-sitemapN.xml ») mêlent annonces actives, biens vendus depuis des années et
  doublons anglais : trop lourds (≈ 28 000 adresses) et sans tri utile. Le connecteur lit à la place les pages de
  « vitrine » par département et type de bien, autorisées et ne listant que les annonces en cours :
  `/ventes/maison/14-calvados/` puis `/ventes/maison/14-calvados/page/2/` (suivie par le lien rel="next").
- l'adresse d'une annonce est `/ventes/<code postal>-<commune>-<titre>-<n°>/` : commune et code postal y figurent.
- les fiches vendues restent en ligne : la classe `statut-offre-vendu` de la page permet de les écarter.

Ce connecteur n'ouvre jamais d'adresse contenant « ? » ni une page de pagination interdite par robots.txt
(`urllib.robotparser` ignore les jokers : la règle est appliquée ici en plus du client poli).

Configuration :
  listing_pages  liste d'adresses de vitrines (ex. https://www.espaces-atypiques.com/ventes/maison/14-calvados/)
  max_pages      pages de vitrine suivies au plus, par vitrine (défaut 5, le maximum autorisé par robots.txt)
  + options d'`AgencySiteConnector` (url_commune_regex, photo_exclude_regex…)
"""
from __future__ import annotations

import html as htmllib
import re
from collections.abc import Iterable
from urllib.parse import urljoin

from app.connectors.agency_site import AgencySiteConnector, dedupe_photos
from app.connectors.base import ListingData, ListingRef, register
from app.extract.html import extract_listing

FICHE = re.compile(r"https://www\.espaces-atypiques\.com/ventes/\d{5}-[a-z0-9-]+/")
NEXT = re.compile(r"""<(?:link|a)\b[^>]*\brel\s*=\s*["']next["'][^>]*>""", re.I)
HREF = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.I)
FORBIDDEN = re.compile(r"\?|/page/(?:1|[6-9]|1\d|20)/|/biens-vendus/|/sold/")  # robots.txt (jokers)
STATUS = re.compile(r"\bstatut-offre-([a-z-]+)")
ACTIVE_CLASS = re.compile(r'class="classe-(cep|eges)\s+active"\s+id="(?:cep|eges)-([a-g])"')


@register
class EspacesAtypiquesConnector(AgencySiteConnector):
    key = "espaces_atypiques"
    label = "Espaces Atypiques"
    kind = "reseau"

    def _next(self, page: str, base: str) -> str | None:
        for m in NEXT.finditer(page):
            h = HREF.search(m.group(0))
            if h:
                nxt = urljoin(base, htmllib.unescape(h.group(1)))
                return None if FORBIDDEN.search(nxt) or nxt == base else nxt
        return None

    def discover(self) -> Iterable[ListingRef]:
        use_zone = self.config.get("zone_filter", True) and self.zone is not None
        limit = int(self.config.get("max_listings", 300))
        max_pages = int(self.config.get("max_pages", 5))
        seen: set[str] = set()
        n = 0
        for first in self.config.get("listing_pages", []):
            url: str | None = first
            for _ in range(max_pages):
                if not url or FORBIDDEN.search(url):
                    break
                res = self.client.get(url)
                if res.status != 200:
                    break
                for m in FICHE.finditer(res.text):
                    furl = m.group(0)
                    if furl in seen or not self.accepts(furl):
                        continue
                    seen.add(furl)
                    hint = self._zone_hit(furl) if use_zone else {}
                    if use_zone and not hint:
                        continue
                    yield ListingRef(url=furl, external_id=self._external_id(furl), hint=hint or {})
                    n += 1
                    if n >= limit:
                        return
                url = self._next(res.text, url)

    def fetch(self, ref: ListingRef) -> ListingData | None:
        res = self.client.get(ref.url)
        if res.status in (404, 410):
            return None
        if res.status != 200:
            raise RuntimeError(f"HTTP {res.status} sur {ref.url}")
        status = STATUS.search(res.text)
        if status and status.group(1) in ("vendu", "vendue", "loue"):
            return None  # bien vendu, laissé en ligne par le site
        return self._finish(ref, res)

    def _finish(self, ref: ListingRef, res) -> ListingData:
        data = extract_listing(res.text, ref.url)
        h = ref.hint or {}
        data.commune_name = h.get("commune_name") or data.commune_name
        data.postal_code = h.get("postal_code") or data.postal_code
        if h.get("commune_code"):
            data.extra["commune_code"] = h["commune_code"]
        data.external_id = ref.external_id or data.external_id
        for kind, letter in ACTIVE_CLASS.findall(res.text):
            if kind == "cep":
                data.dpe = data.dpe or letter.upper()
            else:
                data.ges = data.ges or letter.upper()
        data.photos = dedupe_photos(data.photos, self.config.get("photo_group_regex"), self.config.get("photo_prefer_regex"), self.config.get("photo_exclude_regex"))
        return data
