"""Century 21 (century21.fr) : pages de liste « maisons à vendre » par département, puis pages détail.

- robots.txt (respecté à la lettre) : sont interdits les pages de recherche par code postal
  (`/annonces/achat-maison/cp-…`), `/annonces/f/…`, `/a/*/annonces/`, `/trouver_logement/detail_non_publie/`…
  Ne sont PAS interdits : les listes par département (`/annonces/achat-maison/d-14_calvados/`, pagination
  `page-N/`) et les pages `/trouver_logement/detail/<id>/`, seules utilisées ici.
- Le sitemap `sitemap-vente_detail.xml` (≈35 000 adresses nationales `/trouver_logement/detail/<id>/`) ne dit rien de
  la localisation : l'utiliser obligerait à ouvrir toutes les pages. On passe donc par les listes départementales,
  dont chaque fiche porte la commune et le département (« LISIEUX 14 ») : filtre par la zone avant d'ouvrir le détail.
- Le détail est lisible sans JavaScript (prix, surface, terrain, pièces, description, équipements, photos).

Configuration :
  departements   identifiants de département tels que dans l'adresse (défaut : 14_calvados, 27_eure, 61_orne)
  categorie      segment d'adresse de la catégorie (défaut : achat-maison)
  max_pages      pages de liste lues par département (défaut 40)
  max_listings   garde-fou (défaut 400)
"""
from __future__ import annotations

import html as htmllib
import re
from collections.abc import Iterable

from app.connectors.base import ListingData, ListingRef, register
from app.connectors.sitemap import SitemapConnector
from app.extract.html import extract_listing, meta, to_float, to_int
from app.services.zone import slugify

BASE = "https://www.century21.fr"
_CARD = re.compile(r'class="c-the-property-thumbnail-with-content[^"]*"\s+data-uid="(\d+)"')
_TAGS = re.compile(r"<(?:[^>\"']|\"[^\"]*\"|'[^']*')*>")


def _text(fragment: str) -> list[str]:
    t = re.sub(r"<(script|style|svg)\b.*?</\1>", " ", fragment, flags=re.S | re.I)
    t = _TAGS.sub("\n", t)
    t = htmllib.unescape(t).replace("\xa0", " ").replace(" ", " ")
    return [ln for ln in (re.sub(r"\s+", " ", x).strip() for x in t.split("\n")) if ln]


def parse_list(page: str) -> list[dict]:
    """Fiches d'une page de liste : uid, commune, département, prix, surface, pièces, référence."""
    starts = list(_CARD.finditer(page))
    out = []
    for a, b in zip(starts, starts[1:] + [None]):
        blk = page[a.end() : b.start() if b else a.end() + 15000]
        lines = _text(blk)
        item: dict = {"uid": a.group(1)}
        for ln in lines:
            m = re.fullmatch(r"(.+?)\s+(\d{2,3})", ln)
            if m and "commune" not in item and not ln.startswith("Ref") and not re.search(r"€|pièces?", ln):
                item["commune"], item["dep"] = m.group(1), m.group(2)
            elif re.fullmatch(r"[\d\s]+€", ln) and "price" not in item:
                item["price"] = to_int(ln)
            elif ln.startswith("Ref :"):
                item["ref"] = ln.split(":", 1)[1].strip()
        out.append(item)
    return out


def _variants(slug: str) -> list[str]:
    """« st-martin-de-la-lieue » -> aussi « saint-martin-de-la-lieue » (Century 21 abrège)."""
    full = re.sub(r"(^|-)st(-|$)", r"\1saint\2", slug)
    full = re.sub(r"(^|-)ste(-|$)", r"\1sainte\2", full)
    return list(dict.fromkeys([slug, full]))


def zone_hit(zone, commune: str, dep: str):
    for s in _variants(slugify(commune)):
        hit = zone.by_key.get((s, dep))
        if hit:
            return hit  # (code INSEE, nom)
    return None


@register
class Century21Connector(SitemapConnector):
    key = "century21"
    label = "Century 21 (réseau)"
    kind = "reseau"

    def _list_url(self, dep: str, page: int) -> str:
        cat = self.config.get("categorie", "achat-maison")
        suffix = "" if page == 1 else f"page-{page}/"
        return f"{BASE}/annonces/{cat}/d-{dep}/{suffix}"

    def discover(self) -> Iterable[ListingRef]:
        zone = self.zone if self.config.get("zone_filter", True) else None
        deps = self.config.get("departements") or ["14_calvados", "27_eure", "61_orne"]
        max_pages = int(self.config.get("max_pages", 40))
        limit = int(self.config.get("max_listings", 400))
        n = 0
        seen: set[str] = set()
        for dep in deps:
            code_dep = dep.split("_")[0]
            for page_no in range(1, max_pages + 1):
                res = self.client.get(self._list_url(dep, page_no))
                if res.status != 200:
                    break
                cards = parse_list(res.text)
                new = [c for c in cards if c["uid"] not in seen]
                if not new:
                    break
                for c in new:
                    seen.add(c["uid"])
                    hint: dict = {}
                    if zone:
                        hit = zone_hit(zone, c.get("commune", ""), c.get("dep") or code_dep)
                        if not hit:
                            continue
                        hint = {"commune_code": hit[0], "commune_name": hit[1]}
                    yield ListingRef(url=f"{BASE}/trouver_logement/detail/{c['uid']}/", external_id=c["uid"], hint=hint)
                    n += 1
                    if n >= limit:
                        return
                if f"page-{page_no + 1}/" not in res.text:
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
        data.external_id = ref.external_id or (re.search(r"/detail/(\d+)", ref.url) or [None, None])[1]
        if h.get("commune_code"):
            data.extra["commune_code"] = h["commune_code"]

        main = re.search(r"<main\b.*?</main>", page, re.S | re.I)
        body = main.group(0) if main else page
        lines = _text(body)
        flat = "\n".join(lines)

        # commune et code postal : fil d'Ariane « Achat Maison BEAUMONT EN AUGE (14950) »
        crumb = re.search(r"Achat [A-Za-zéèêàç ]+? ([A-ZÉÈÊÀÂÎÔÛÇ0-9' \-]+) \((\d{5})\)", flat)
        if crumb:
            data.postal_code = crumb.group(2)
            data.commune_name = h.get("commune_name") or crumb.group(1).title()
        else:
            data.commune_name = h.get("commune_name") or data.commune_name

        # titre / type / pièces / surface : bloc <h1>
        h1 = re.search(r"<h1[^>]*>(.*?)</h1>", body, re.S)
        if h1:
            parts = _text(h1.group(1))
            if parts:
                data.property_type = (re.match(r"\w+", parts[0]).group(0).lower()) if re.match(r"\w+", parts[0]) else data.property_type
            for ln in parts:
                m = re.search(r"(\d+)\s*pièces?\s*-\s*([\d,]+)\s*m", ln)
                if m:
                    data.rooms, data.surface = int(m.group(1)), to_float(m.group(2))
        og = meta(page, "og:title")
        data.title = og or data.title

        # prix et honoraires (après le <h1>)
        after = body[h1.end() :] if h1 else body
        price = re.search(r"<p[^>]*>\s*([\d\s\xa0]+?)(?:&nbsp;)?\s*(?:&euro;|€)", after)
        if price:
            data.price = to_int(re.sub(r"(&nbsp;|\s)", "", price.group(1))) or data.price
        fees = [htmllib.unescape(x).strip() for x in re.findall(r"<li[^>]*>\s*((?:Honoraires|Prix hors honoraires)[^<]*?)\s*</li>", after[:6000])]
        data.fees = " ; ".join(fees) or None

        # « Vue globale », « Équipements », « À savoir »
        land = re.search(r"Surface terrain\s*:\s*([\d ]+(?:,\d+)?)\s*m", flat)
        data.land = to_float(land.group(1).replace(" ", "")) if land else None
        hab = re.search(r"Surface habitable\s*:\s*([\d ]+(?:,\d+)?)\s*m", flat)
        if hab and not data.surface:
            data.surface = to_float(hab.group(1).replace(" ", ""))
        rooms = re.search(r"Nombre de pièces\s*:\s*(\d+)", flat)
        data.rooms = int(rooms.group(1)) if rooms else data.rooms
        piece_names = []
        if "Nombre de pièces" in flat:
            seg = body[body.find("Nombre de pièces") :]
            seg = seg[: seg.find("</section>")]
            piece_names = [ln for ln in _text(seg) if not ln.startswith("Nombre")]
        beds = sum(1 for ln in piece_names if re.match(r"(chambre|suite)", ln, re.I))
        data.bedrooms = beds or None
        heat = re.search(r"Chauffage\s*:\s*(.+)", flat)
        data.heating = heat.group(1).strip() if heat else None
        tax = re.search(r"Taxe foncière\s*:\s*([\d ]+)", flat)
        data.property_tax = to_int(tax.group(1)) if tax else None
        cond = re.search(r"Travaux à prévoir\s*:\s*(.+)", flat)
        data.condition = f"Travaux à prévoir : {cond.group(1).strip()}" if cond else None
        year = re.search(r"Année de construction\s*:\s*((?:1[5-9]|20)\d{2})", flat)
        data.year_built = int(year.group(1)) if year else None

        # description de l'agence (sans le « Résumé AI » du site, reformulé automatiquement)
        d = re.search(r"<h2[^>]*>\s*Description\s*</h2>\s*<div[^>]*>(.*?)</div>", body, re.S)
        if d:
            txt = re.sub(r"<br\s*/?>", "\n", d.group(1), flags=re.I)
            txt = htmllib.unescape(_TAGS.sub("", txt))
            txt = "\n".join(re.sub(r"[ \t\xa0]+", " ", x).strip() for x in txt.split("\n"))
            data.description = re.sub(r"\n{3,}", "\n\n", txt).strip() or data.description
        if data.year_built is None and data.description:
            y = re.search(r"construit[e]?\s+en\s+((?:1[5-9]|20)\d{2})", data.description, re.I)
            data.year_built = int(y.group(1)) if y else None

        # DPE / GES : lus dans le résumé du site quand il les cite (les étiquettes sont des dessins)
        dpe = re.search(r"classe ([A-G]) \([\d,. ]+ ?kWh", flat)
        ges = re.search(r"classe ([A-G]) \([\d,. ]+ ?kgCO", flat)
        data.dpe = dpe.group(1) if dpe else None
        data.ges = ges.group(1) if ges else None

        # photos de CETTE annonce : « c21_<a>_<b>_<ref>_<n>_<UUID>.jpg » (les biens similaires ont d'autres références)
        cover = re.search(r"/(c21_\d+_\d+_\d+)_", meta(page, "og:image") or "")
        if cover:
            by_uuid: dict[str, str] = {}
            for u in re.findall(r"/imagesBien/[^\"'\s<>?]*" + cover.group(1) + r"_[^\"'\s<>?]+?\.jpe?g", page, re.I):
                uid = re.search(r"_([0-9A-Fa-f-]{36})\.", u)
                by_uuid.setdefault(uid.group(1) if uid else u, BASE + u)
            data.photos = list(by_uuid.values()) or data.photos
        else:
            data.photos = [p for p in data.photos if "/imagesBien/" in p]

        # agence
        if "Ce bien est proposé par l'agence" in lines:
            i = lines.index("Ce bien est proposé par l'agence")
            c = {"agence": lines[i + 1]}
            adr = [x for x in lines[i + 3 : i + 6] if re.search(r"\d{5}|^\d+ ", x) or x.lower().startswith(("rue", "avenue", "place"))]
            if adr:
                c["adresse"] = " ".join(adr)
            tel = next((x for x in lines[i : i + 40] if re.fullmatch(r"0\d(?: \d{2}){4}", x)), None)
            if tel:
                c["telephone"] = tel
            data.contact = c
        if (m := re.search(r"Ref\s*:\s*(\w+)", flat)):
            data.extra["ref_agence"] = m.group(1)
        return data
