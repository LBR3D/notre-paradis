"""Guy Hoquet (guy-hoquet.com) : pages de liste par commune (sitemap) puis pages détail.

- robots.txt : `/achat-vente/…` n'est pas interdit (ni `?page=n`) ; sont interdits `/biens/search-properties`,
  `/transaction-vente`, `/bien/print/*`… que le connecteur n'utilise pas.
- Le sitemap des annonces n'existe pas : le sitemap `sitemap/sitemap-1` ne liste que les pages
  « annonces de <commune> » (`/achat-vente/annonces-<commune>-<codepostal>`). On retient celles des communes de la
  zone (ZoneIndex.match_url), on lit leurs pages de liste (pagination `?page=n`) et on relève les liens de maisons.
  Les adresses de détail contiennent commune et code postal (`/achat-vente/maison-5-pieces-touques-14800-1896690`) :
  filtre par la zone avant d'ouvrir la page.
- La page détail est lisible sans JavaScript : prix, surface, pièces/chambres, fiche technique, DPE/GES, photos.

Configuration (en plus de celle de `sitemap`) :
  list_regex     adresses de pages de liste à parcourir (défaut : /achat-vente/annonces-)
  detail_types   début de l'identifiant de type retenu (défaut : maison, propriété, villa, ferme, château, manoir…)
  max_pages      pages de liste lues par commune (défaut 6)
"""
from __future__ import annotations

import html as htmllib
import re
from collections.abc import Iterable

from app.connectors.base import ListingData, ListingRef, register
from app.connectors.sitemap import SitemapConnector
from app.extract.html import extract_listing, to_float, to_int, visible_text

_DETAIL = re.compile(r"""href=["'](?:https://www\.guy-hoquet\.com)?(/achat-vente/(?P<slug>(?P<type>[a-z-]+?)-(?:\d+-pieces?-)?[a-z0-9-]+?-(?P<cp>\d{5})-(?P<id>\d+)))["']""")
DEFAULT_TYPES = r"^(?:maison|propriete|villa|ferme|chateau|manoir|longere|moulin|chaumiere|corps-de-ferme|batisse|hotel-particulier)"


def detail_links(page: str) -> list[str]:
    """Adresses (relatives) des annonces d'une page de liste, sans doublon, dans l'ordre."""
    out: dict[str, None] = {}
    for m in _DETAIL.finditer(page):
        if "/achat-vente/annonces-" in m.group(1):
            continue
        out[m.group(1)] = None
    return list(out)


def _fiche(lines: list[str]) -> dict[str, str]:
    """Paires libellé / valeur de « Fiche technique du bien » (une ligne chacune dans le texte visible)."""
    try:
        i = lines.index("Fiche technique du bien") + 1
    except ValueError:
        return {}
    out: dict[str, str] = {}
    while i + 1 < len(lines) and not lines[i].startswith("Bilan énergétique"):
        out[lines[i]] = lines[i + 1]
        i += 2
    return out


@register
class GuyHoquetConnector(SitemapConnector):
    key = "guyhoquet"
    label = "Guy Hoquet (réseau)"
    kind = "reseau"

    def _list_pages(self) -> Iterable[tuple[str, dict]]:
        rx = self.config.get("list_regex", r"/achat-vente/annonces-")
        zone = self.zone if self.config.get("zone_filter", True) else None
        seen: set[str] = set()
        for sm in self._sitemap_urls():
            for url in self._walk(sm):
                if url in seen or not re.search(rx, url):
                    continue
                seen.add(url)
                hit = zone.match_url(url) if zone else None
                if zone and not hit:
                    continue
                yield url, ({"commune_name": hit.commune_name} if hit else {})

    def discover(self) -> Iterable[ListingRef]:
        zone = self.zone if self.config.get("zone_filter", True) else None
        types = re.compile(self.config.get("detail_types", DEFAULT_TYPES))
        limit = int(self.config.get("max_listings", 400))
        max_pages = int(self.config.get("max_pages", 6))
        base = self.config.get("base_url", "https://www.guy-hoquet.com").rstrip("/")
        n = 0
        seen: set[str] = set()
        for list_url, _ in self._list_pages():
            for page_no in range(1, max_pages + 1):
                url = list_url if page_no == 1 else f"{list_url}?page={page_no}"
                res = self.client.get(url)
                if res.status != 200:
                    break
                for path in detail_links(res.text):
                    full = base + path
                    m = _DETAIL.search(f'href="{path}"')
                    if full in seen or not m or not types.search(m["type"]):
                        continue
                    hit = zone.match_url(full) if zone else None
                    if zone and not hit:
                        continue  # commune voisine, hors zone
                    seen.add(full)
                    hint = {"commune_code": hit.commune_code, "commune_name": hit.commune_name, "postal_code": hit.postal_code} if hit else {}
                    yield ListingRef(url=full, external_id=m["id"], hint=hint)
                    n += 1
                    if n >= limit:
                        return
                if f"?page={page_no + 1}" not in res.text:
                    break

    def fetch(self, ref: ListingRef) -> ListingData | None:
        res = self.client.get(ref.url)
        if res.status in (404, 410):
            return None
        if res.status != 200:
            raise RuntimeError(f"HTTP {res.status} sur {ref.url}")
        return self.parse(res.text, ref)

    def parse(self, page: str, ref: ListingRef) -> ListingData:
        data = extract_listing(page, ref.url)
        h = ref.hint or {}
        m = re.search(r"-(\d{5})-(\d+)/?$", ref.url.split("?")[0])
        data.external_id = ref.external_id or (m.group(2) if m else None)
        data.commune_name = h.get("commune_name") or data.commune_name
        data.postal_code = h.get("postal_code") or (m.group(1) if m else None) or data.postal_code
        if h.get("commune_code"):
            data.extra["commune_code"] = h["commune_code"]

        lines = visible_text(page).split("\n")
        h1 = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S)
        if h1:
            t = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", "", h1.group(1)))).strip()
            data.title = (t.capitalize() if t.isupper() else t) or data.title

        # commune telle qu'écrite sur la page (« TOUQUES 14800 ») si l'adresse ne l'a pas donnée
        if not data.commune_name:
            a = re.search(r'<div class="add">\s*([^<]+?)\s+(\d{5})\s*</div>', page)
            if a:
                data.commune_name, data.postal_code = a.group(1).title(), a.group(2)

        # prix et honoraires
        price = re.search(r'<div class="price">\s*([\d\s  ]+)€', page)
        if price:
            data.price = to_int(price.group(1)) or data.price
        hon = re.search(r"Honoraires\s*:\s*([^<]+?)\s*</p>", page)
        hors = re.search(r"([\d\s  ]+)€\s*Hors Honoraires", re.sub(r"<[^>]+>", " ", page))
        fees = [x for x in [re.sub(r"\s+", " ", hon.group(1)) if hon else None, f"prix hors honoraires {to_int(hors.group(1))} €" if hors else None] if x]
        data.fees = " ; ".join(fees) or None

        # description complète : entre « Voir plus » et « Voir moins » (le début est répété, tronqué, juste avant)
        if "Voir plus" in " ".join(lines) or any(ln.endswith("Voir plus") for ln in lines):
            try:
                a = next(i for i, ln in enumerate(lines) if ln.endswith("Voir plus")) + 1
                b = next(i for i in range(a, len(lines)) if lines[i].startswith("Voir moins"))
                data.description = "\n".join(lines[a:b]).strip() or data.description
            except StopIteration:
                pass

        # fiche technique
        fiche = _fiche(lines)
        if fiche:
            data.extra["fiche_technique"] = fiche
        data.year_built = None  # le texte libre cite des années de DPE : on ne garde que la fiche technique
        data.sewage = fiche.get("Assainissement")
        data.condition = fiche.get("Etat intérieur") or fiche.get("État intérieur")
        heat = [fiche[k] for k in ("Type Chauffage", "Mode Chauffage") if fiche.get(k)]
        data.heating = " - ".join(heat) or None
        for k, v in fiche.items():
            lk = k.lower()
            if "taxe" in lk and "fonc" in lk:
                data.property_tax = to_int(v)
            elif "construction" in lk or lk.startswith("année") or lk.startswith("annee"):
                y = re.search(r"(?:1[5-9]|20)\d{2}", v)
                data.year_built = int(y.group(0)) if y else data.year_built
            elif "terrain" in lk and not data.land:
                data.land = to_float(v)

        # DPE / GES : lettres des pictogrammes
        d = re.search(r"/dpe-ges/dpe/([a-g])\.svg", page)
        g = re.search(r"/dpe-ges/ges/([a-g])\.svg", page)
        data.dpe = d.group(1).upper() if d else None
        data.ges = g.group(1).upper() if g else None

        # photos de CETTE annonce (les « biens similaires » ont d'autres identifiants)
        main = re.search(r'property="og:image"\s+content="[^"]*/(\d+)[a-z]\.jpe?g', page)
        if main:
            seen: dict[str, None] = {}
            for u in re.findall(r"https://media\.immo-facile\.com/[^\"'\s?]+/" + main.group(1) + r"[a-z]\.jpe?g(?:\?v=\d+)?", page):
                seen.setdefault(u, None)
            data.photos = list(seen) or data.photos
        data.photos = [p for p in data.photos if "logo" not in p.lower() and "ARCHE" not in p]

        # agence
        contact = {}
        if "Proposé par votre agence :" in lines:
            i = lines.index("Proposé par votre agence :")
            contact["agence"] = lines[i + 1]
            contact["adresse"] = " ".join(lines[i + 2 : i + 4])
        tel = re.search(r"Tél\.\s*([\d\s.]{10,})", "\n".join(lines))
        if tel:
            contact["telephone"] = tel.group(1).strip()
        data.contact = contact
        return data
