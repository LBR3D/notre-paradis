"""Connecteur iad France (www.iadfrance.fr).

Pourquoi un connecteur dédié : les sitemaps `propertylisting*.xml` de iad ne contiennent que des
pages de recherche (par région, département, ville), pas les annonces. Les adresses d'annonces
(`/annonce/maison-vente-5-pieces-pont-l-eveque-103m2/r2130950`) portent la commune mais pas le
code postal, ce qui ne permet pas le filtrage par `ZoneIndex.match_url`.

Principe (aucun contournement, robots.txt respecté par le client poli) :
1. on parcourt les pages de recherche publiques d'un département
   (`/annonces/calvados-14/vente/maison?page=N`) jusqu'à la première page vide ;
2. chaque page contient, dans ses données intégrées (`__NUXT_DATA__`), la commune et le code postal
   de chaque annonce : on ne garde que celles de la zone (`ZoneIndex.match`) ;
3. la page détail est lue à partir des mêmes données intégrées (prix, surfaces, terrain, pièces,
   chambres, DPE, galerie complète de photos), avec l'extracteur générique en filet de sécurité.

Configuration d'une source (JSON) :
  departements   liste de segments de département (défaut : calvados-14, eure-27, orne-61)
  types          types de biens à parcourir (défaut : ["maison"])
  max_pages      garde-fou de pagination par département et par type (défaut 40)
  max_listings   garde-fou global (défaut 400)
  zone_filter    false pour désactiver le filtre par commune
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterable

from app.connectors.base import Connector, ListingData, ListingRef, register
from app.extract.html import extract_listing, parse_property_type, to_float, to_int
from app.services.zone import ZoneIndex

_NUXT = re.compile(r"""<script[^>]*id=["']__NUXT_DATA__["'][^>]*>(.*?)</script>""", re.S)
_WRAPPERS = {"Reactive", "ShallowReactive", "Ref", "ShallowRef", "Set"}
DEFAULT_DEPARTMENTS = ["calvados-14", "eure-27", "orne-61"]

_HEATING = {
    "electricity": "électrique",
    "gas": "gaz",
    "fuel": "fioul",
    "oil": "fioul",
    "wood": "bois",
    "heat_pump": "pompe à chaleur",
    "geothermal": "géothermie",
    "solar": "solaire",
}
_DISPLAY_TYPES = {
    "country-house": "maison de campagne",
    "town-house": "maison de ville",
    "castle": "château",
    "chateau": "château",
    "manor": "manoir",
    "farm": "ferme",
    "farmhouse": "ferme",
    "mill": "moulin",
    "villa": "villa",
}
_LEGAL_TAIL = re.compile(r"\n+\s*(?:Honoraires d.agence|La présentation d.une pièce d.identité|Les informations sur les risques|La présente annonce immobilière a été rédigée)", re.I)


class _Nuxt:
    """Lecteur minimal du format « devalue » de Nuxt : un tableau dont les valeurs sont des indices."""

    def __init__(self, data: list):
        self.d = data

    @classmethod
    def from_page(cls, page: str) -> _Nuxt | None:
        m = _NUXT.search(page)
        if not m:
            return None
        try:
            data = json.loads(m.group(1))
        except ValueError:
            return None
        return cls(data) if isinstance(data, list) else None

    def resolve(self, i, depth: int = 0, max_depth: int = 7):
        if depth > max_depth or not isinstance(i, int) or not 0 <= i < len(self.d):
            return None
        x = self.d[i]
        if isinstance(x, dict):
            return {k: self.resolve(v, depth + 1, max_depth) for k, v in x.items()}
        if isinstance(x, list):
            if len(x) == 2 and isinstance(x[0], str) and x[0] in _WRAPPERS:
                return self.resolve(x[1], depth + 1, max_depth)
            return [self.resolve(v, depth + 1, max_depth) for v in x]
        return x

    def objects_with(self, *keys: str) -> Iterable[dict]:
        for i, x in enumerate(self.d):
            if isinstance(x, dict) and all(k in x for k in keys):
                yield self.resolve(i)


def listing_url(base_url: str, item: dict) -> str | None:
    slug = (item.get("slugs") or {}).get("fr")
    ref = item.get("propertyListingRef")
    if not slug or not ref:
        return None
    return f"{base_url.rstrip('/')}/annonce/{slug}/r{ref}"


def parse_list_page(page: str, base_url: str = "https://www.iadfrance.fr") -> list[dict]:
    """Annonces d'une page de recherche : url, référence, commune, code postal, prix."""
    nuxt = _Nuxt.from_page(page)
    if not nuxt:
        return []
    out: list[dict] = []
    for it in nuxt.objects_with("propertyListingRef", "slugs", "location"):
        if (it.get("transactionType") or "sale") != "sale":
            continue
        url = listing_url(base_url, it)
        if not url:
            continue
        loc = it.get("location") or {}
        out.append({
            "url": url,
            "ref": str(it["propertyListingRef"]),
            "place": loc.get("place"),
            "postcode": loc.get("postcode"),
            "price": (it.get("price") or {}).get("main"),
            "signed": bool(it.get("isContractSigned")),
        })
    return out


def _surface(surfaces: list, kind: str) -> float | None:
    for s in surfaces or []:
        if isinstance(s, dict) and s.get("type") == kind:
            return to_float(s.get("value"))
    return None


def _room(rooms: list, kind: str) -> int | None:
    for r in rooms or []:
        if isinstance(r, dict) and r.get("type") == kind:
            return to_int(r.get("value"))
    return None


def parse_detail(page: str, url: str) -> ListingData:
    """Page détail iad -> ListingData. Les données intégrées priment ; l'extracteur générique complète."""
    data = extract_listing(page, url)
    nuxt = _Nuxt.from_page(page)
    main = next(iter(nuxt.objects_with("propertyListingRef", "mandateNumber")), None) if nuxt else None
    # le titre générique est tronqué sur « Pont-l'Évêque » (coupe au tiret) : on le refait
    og = re.search(r"""<meta[^>]+property=["']og:title["'][^>]+content=["']([^"']+)""", page)
    if og:
        data.title = og.group(1).replace("&#x27;", "'").replace("&#39;", "'")
    if not main:
        return data

    data.external_id = str(main.get("propertyListingRef") or "") or data.external_id
    seo = main.get("seo") or {}
    data.title = seo.get("metaTitle") or main.get("title") or data.title
    desc = main.get("description")
    if desc:
        data.description = _LEGAL_TAIL.split(desc.strip())[0].strip()
    prices = main.get("prices") or {}
    data.price = to_int(prices.get("formattedMain")) or data.price
    if prices.get("feesCharge") == "seller":
        data.fees = "Honoraires à la charge du vendeur"
    elif prices.get("feesCharge"):
        data.fees = "Honoraires à la charge de l'acquéreur"
    data.surface = to_float(main.get("mainSurface")) or _surface(main.get("surfaceList"), "living-area") or data.surface
    data.land = _surface(main.get("surfaceList"), "plot-area") or data.land
    data.rooms = to_int(main.get("roomsCount")) or _room(main.get("rooms"), "rooms") or data.rooms
    data.bedrooms = to_int(main.get("bedroomsCount")) or _room(main.get("rooms"), "bedrooms") or data.bedrooms
    data.year_built = to_int(main.get("constructionYear")) or data.year_built

    epc = main.get("epcGes") or {}
    for field, key in (("dpe", "epc"), ("ges", "ges")):
        cls = ((epc.get(key) or {}).get("class") or "").upper()
        if cls in list("ABCDEFG"):
            setattr(data, field, cls)
    if (epc.get("epc") or {}).get("consumption") is not None:
        data.extra["dpe_kwh_m2_an"] = epc["epc"]["consumption"]
    if (epc.get("amount") or {}).get("min") is not None:
        data.extra["energie_cout_annuel"] = [epc["amount"].get("min"), epc["amount"].get("max")]

    loc = main.get("location") or {}
    data.commune_name = loc.get("place") or data.commune_name
    data.postal_code = loc.get("postcode") or data.postal_code
    crumbs = [c.get("text") for c in main.get("breadcrumbs") or [] if isinstance(c, dict) and c.get("text")]
    for c in crumbs:
        if re.search(r"\(\d{5}\)$", c):
            data.extra["localite_affichee"] = c  # commune du fil d'Ariane (peut différer de la commune d'affichage)

    ptype = _DISPLAY_TYPES.get(main.get("propertyDisplayType") or "")
    data.property_type = ptype or parse_property_type(f"{data.title or ''} {(data.description or '')[:150]}") or "maison"

    feats = [f.get("text") for f in (main.get("mainFeatures") or []) + (main.get("secondaryFeatures") or []) if isinstance(f, dict) and f.get("text")]
    feats = [f for f in feats if not f.startswith("property.feature.")]
    if feats:
        data.extra["caracteristiques"] = feats
        data.outbuildings = ", ".join(f for f in feats if re.search(r"garage|cave|d[ée]pendance|grange|atelier|piscine|abri|parking", f, re.I)) or None
    for f in main.get("secondaryFeatures") or []:
        for key in (f.get("translationKey") or []) if isinstance(f, dict) else []:
            if "heating" in key:
                kind = key.rsplit(".", 1)[-1]
                data.heating = _HEATING.get(kind, kind)
    agent = main.get("agent") or {}
    if agent.get("fullName"):
        data.contact = {"conseiller": agent["fullName"]}
    if main.get("firstPublishDate"):
        data.extra["publie_le"] = main["firstPublishDate"]
    if main.get("isContractSigned"):
        data.extra["compromis_signe"] = True

    photos = []
    for u in (main.get("media") or {}).get("photos") or []:
        if isinstance(u, str) and u not in photos:
            photos.append(u)
    if photos:
        data.photos = photos[:40]
    data.extraction_method = "parser"
    return data


@register
class IadConnector(Connector):
    key = "iad"
    label = "iad France (réseau)"
    kind = "reseau"

    zone: ZoneIndex | None = None  # injecté par le job de collecte

    def _base(self) -> str:
        return (self.config.get("base_url") or "https://www.iadfrance.fr").rstrip("/")

    def _list_url(self, dept: str, ptype: str, page: int) -> str:
        url = f"{self._base()}/annonces/{dept}/vente/{ptype}"
        return url if page <= 1 else f"{url}?page={page}"

    def discover(self) -> Iterable[ListingRef]:
        zone = self.zone
        use_zone = self.config.get("zone_filter", True) and zone is not None
        limit = int(self.config.get("max_listings", 400))
        max_pages = int(self.config.get("max_pages", 40))
        seen: set[str] = set()
        n = 0
        for dept in self.config.get("departements") or DEFAULT_DEPARTMENTS:
            for ptype in self.config.get("types") or ["maison"]:
                for page in range(1, max_pages + 1):
                    res = self.client.get(self._list_url(dept, ptype, page))
                    if res.status in (404, 410):
                        break
                    if res.status != 200:
                        raise RuntimeError(f"HTTP {res.status} sur {res.url}")
                    items = parse_list_page(res.text, self._base())
                    if not items:
                        break
                    if all(it["url"] in seen for it in items):
                        break  # le site renvoie la dernière page en boucle : fin de la pagination
                    for it in items:
                        if it["url"] in seen:
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
        data.commune_name = data.commune_name or h.get("commune_name")
        data.postal_code = data.postal_code or h.get("postal_code")
        if h.get("commune_code"):
            data.extra["commune_code"] = h["commune_code"]
        data.external_id = data.external_id or ref.external_id
        return data
