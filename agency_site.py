"""Connecteur pour les sites de petites agences locales (sitemap + extracteur générique).

Étend `SitemapConnector` pour les cas fréquents des sites d'agences :
- adresses sans code postal mais avec « <département>-<commune> » (plateforme LBI : `/vente/14-calvados/1-honfleur/…`) ;
- photos publiées en plusieurs tailles (même cliché 3 ou 4 fois) ou mêlées aux diagnostics énergétiques ;
- identifiant de l'annonce lisible dans l'adresse (Netty : `…-14170,VM502`).

Configuration (en plus de celle de `SitemapConnector`) :
  url_commune_regex   reconnaît la commune de la zone quand l'adresse n'a pas « commune-codepostal ». Deux formes :
                      groupes nommés `dep` + `slug` (département et commune), ou `cp` + `rest` (code postal suivi
                      de la commune et du titre : la commune est le début le plus long qui existe dans la zone)
  external_id_regex   expression dont le premier groupe est l'identifiant de l'annonce dans l'adresse
  photo_group_regex   expression dont le premier groupe identifie un cliché (pour regrouper ses tailles)
  photo_prefer_regex  taille préférée parmi les variantes d'un même cliché
  photo_exclude_regex photos à écarter (diagnostics, logos partenaires…)
"""
from __future__ import annotations

import re
from collections.abc import Iterable

from app.connectors.base import ListingData, ListingRef, register
from app.connectors.sitemap import SitemapConnector
from app.services.zone import slugify


def norm_slug(s: str) -> str:
    """« la-riviere-st-sauveur » et « La Rivière-Saint-Sauveur » -> « lariviere saintsauveur » (comparables)."""
    parts = [{"st": "saint", "ste": "sainte"}.get(w, w) for w in slugify(s).split("-") if w]
    return "".join(parts)


def dedupe_photos(photos: list[str], group_regex: str | None, prefer_regex: str | None = None, exclude_regex: str | None = None) -> list[str]:
    """Une seule adresse par cliché (la taille préférée), dans l'ordre de la page."""
    chosen: dict[str, str] = {}
    for p in photos:
        if exclude_regex and re.search(exclude_regex, p):
            continue
        m = re.search(group_regex, p) if group_regex else None
        key = m.group(1) if m else p.split("?")[0]
        if key not in chosen:
            chosen[key] = p
        elif prefer_regex and re.search(prefer_regex, p) and not re.search(prefer_regex, chosen[key]):
            chosen[key] = p
    return list(chosen.values())


@register
class AgencySiteConnector(SitemapConnector):
    key = "agency_site"
    label = "Site d'agence locale (sitemap)"
    kind = "agence"

    def _commune_index(self) -> dict[tuple[str, str], tuple[str, str]]:
        if not hasattr(self, "_cidx"):
            self._cidx = {(norm_slug(slug), dep): v for (slug, dep), v in (self.zone.by_key.items() if self.zone else [])}
        return self._cidx

    def _from_url(self, url: str) -> tuple[str, str] | None:
        """(département, slug de commune) lus dans l'adresse selon `url_commune_regex` (groupes `dep` et `slug`)."""
        rx = self.config.get("url_commune_regex")
        m = re.search(rx, url) if rx else None
        return (m.group("dep"), m.group("slug")) if m and "slug" in m.groupdict() else None

    def _zone_hit(self, url: str) -> dict | None:
        if self.zone is None:
            return None
        rx = self.config.get("url_commune_regex")
        m = re.search(rx, url) if rx else None
        gd = m.groupdict() if m else {}
        if "cp" in gd and "rest" in gd:
            # « /ventes/14270-belle-vie-en-auge-maison-de-maitre-18074/ » : commune juste après le code postal
            words = [w for w in gd["rest"].split("-") if w]
            for n in range(min(7, len(words)), 0, -1):
                hit = self._commune_index().get((norm_slug("-".join(words[:n])), gd["cp"][:2]))
                if hit:
                    return {"commune_code": hit[0], "commune_name": hit[1], "postal_code": gd["cp"]}
            return None
        if "dep" in gd and "slug" in gd:
            hit = self._commune_index().get((norm_slug(gd["slug"]), gd["dep"]))
            return {"commune_code": hit[0], "commune_name": hit[1]} if hit else None
        h = self.zone.match_url(url)
        return {"commune_code": h.commune_code, "commune_name": h.commune_name, "postal_code": h.postal_code} if h else None

    def _external_id(self, url: str) -> str | None:
        rx = self.config.get("external_id_regex")
        m = re.search(rx, url) if rx else None
        return m.group(1) if m else None

    def discover(self) -> Iterable[ListingRef]:
        use_zone = self.config.get("zone_filter", True) and self.zone is not None
        limit = int(self.config.get("max_listings", 400))
        n = 0
        seen: set[str] = set()
        for sm in self._sitemap_urls():
            for url in self._walk(sm):
                if url in seen or not self.accepts(url):
                    continue
                seen.add(url)
                hint = self._zone_hit(url) if use_zone else {}
                if use_zone and not hint:
                    continue
                yield ListingRef(url=url, external_id=self._external_id(url), hint=hint or {})
                n += 1
                if n >= limit:
                    return

    def fetch(self, ref: ListingRef) -> ListingData | None:
        data = super().fetch(ref)
        if data is None:
            return None
        data.external_id = data.external_id or ref.external_id or self._external_id(ref.url)
        if not data.commune_name:
            got = self._from_url(ref.url)
            if got:
                data.commune_name = got[1].replace("-", " ").title()
        if self.config.get("photo_group_regex") or self.config.get("photo_exclude_regex"):
            data.photos = dedupe_photos(
                data.photos, self.config.get("photo_group_regex"), self.config.get("photo_prefer_regex"), self.config.get("photo_exclude_regex")
            )
        return data
