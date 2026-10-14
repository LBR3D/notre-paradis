"""API HTTP consommée par l'interface."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.datasources import REGISTRY as DATASOURCES
from app.datasources.communes import update_zone_flags
from app.jobs import scheduler
from app.jobs.runner import JOBS, is_running, run_job_async
from app.models import (
    ApiUsage,
    DataSourceStatus,
    Enrichment,
    Listing,
    PriceEvent,
    Property,
    Reaction,
    RunLog,
    Source,
)
from app.services.eliminate import evaluate_all
from app.services.settings_service import load_settings, reset_section, save_settings
from app.settings_schema import CRITERES, UserSettings

router = APIRouter(prefix="/api")


# ------------------------------------------------------------------ santé
@router.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"ok": True, "heure": datetime.now(timezone.utc).isoformat()}


# ---------------------------------------------------------------- réglages
@router.get("/settings")
def get_settings(db: Session = Depends(get_db)):
    return {"values": load_settings(db).model_dump(), "schema": UserSettings.model_json_schema(), "criteres": CRITERES}


@router.put("/settings")
def put_settings(payload: dict, db: Session = Depends(get_db)):
    before = load_settings(db)
    try:
        saved = save_settings(db, payload)
    except ValidationError as e:
        raise HTTPException(422, detail=json.loads(e.json())) from e
    if saved.zone.epci != before.zone.epci:
        update_zone_flags(db, saved)
    scheduler.reschedule()
    stats = evaluate_all(db, saved)  # nouveaux seuils appliqués tout de suite aux biens déjà collectés
    return {"values": saved.model_dump(), "recalcul": stats}


@router.post("/settings/reset/{section}")
def post_reset(section: str, db: Session = Depends(get_db)):
    try:
        saved = reset_section(db, section)
    except KeyError as e:
        raise HTTPException(404, "Section inconnue") from e
    update_zone_flags(db, saved)
    scheduler.reschedule()
    return {"values": saved.model_dump(), "recalcul": evaluate_all(db, saved)}


# -------------------------------------------------------------- géographie
@router.get("/zone")
def get_zone(db: Session = Depends(get_db)):
    """Communes de la zone (GeoJSON), avec l'indication « pénalisée »."""
    s = load_settings(db)
    rows = db.execute(
        text("""
        SELECT code, nom, departement, ST_AsGeoJSON(ST_SimplifyPreserveTopology(geom, 0.0005), 5) AS g
        FROM commune WHERE in_zone OR code = ANY(:pen)
        """),
        {"pen": s.zone.communes_penalisees},
    ).all()
    pen = set(s.zone.communes_penalisees)
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": json.loads(r.g),
                "properties": {"code": r.code, "nom": r.nom, "departement": r.departement, "penalisee": r.code in pen},
            }
            for r in rows
        ],
    }


@router.get("/communes")
def search_communes(q: str = "", codes: str = "", db: Session = Depends(get_db)):
    if codes:
        rows = db.execute(
            text("SELECT code, nom, departement FROM commune WHERE code = ANY(:c) ORDER BY nom"),
            {"c": codes.split(",")},
        ).all()
    else:
        rows = db.execute(
            text("""SELECT code, nom, departement FROM commune
                    WHERE norm_txt(nom) LIKE '%' || norm_txt(:q) || '%' ORDER BY in_zone DESC, nom LIMIT 20"""),
            {"q": q},
        ).all()
    return [{"code": r.code, "nom": r.nom, "departement": r.departement} for r in rows]


@router.get("/epci")
def search_epci(q: str = "", codes: str = "", db: Session = Depends(get_db)):
    if codes:
        rows = db.execute(text("SELECT code, nom FROM epci WHERE code = ANY(:c) ORDER BY nom"), {"c": codes.split(",")}).all()
    else:
        rows = db.execute(
            text("SELECT code, nom FROM epci WHERE norm_txt(nom) LIKE '%' || norm_txt(:q) || '%' ORDER BY nom LIMIT 20"),
            {"q": q},
        ).all()
    return [{"code": r.code, "nom": r.nom} for r in rows]


# -------------------------------------------------------------------- biens
def _prop_summary(p: Property, lonlat: tuple | None, enr: dict | None = None) -> dict:
    enr = enr or {}
    route = enr.get("route") or {}
    dvf = enr.get("dvf") or {}
    return {
        "route_min": route.get("duree_min"),
        "route_vendredi": route.get("vendredi_soir_min"),
        "ecart_marche_pct": dvf.get("ecart_pct"),
        "nb_annonces": len(p.listings),
        "id": p.id,
        "titre": p.title,
        "type": p.property_type,
        "prix": p.price,
        "prix_initial": p.price_initial,
        "surface": p.surface,
        "terrain": p.land,
        "chambres": p.bedrooms,
        "dpe": p.dpe,
        "commune_code": p.commune_code,
        "photo": p.main_photo_url,
        "score": p.score_total,
        "elimine": p.eliminated,
        "raisons_elimination": [r for r in (p.elimination_reasons or []) if not isinstance(r, dict) or r.get("certitude") == "certaine"],
        "a_verifier": [r for r in (p.elimination_reasons or []) if isinstance(r, dict) and r.get("certitude") == "a_verifier"],
        "statut": p.status,
        "reaction": p.reaction,
        "vu": p.seen,
        "actif": p.is_active,
        "confiance_position": p.geo_confidence,
        "premiere_apparition": p.first_seen.isoformat() if p.first_seen else None,
        "lon": lonlat[0] if lonlat else None,
        "lat": lonlat[1] if lonlat else None,
    }


@router.get("/properties")
def list_properties(
    inclure_elimines: bool = True,
    inclure_inactifs: bool = False,
    tri: Literal["score", "prix", "recent"] = "score",
    db: Session = Depends(get_db),
):
    q = select(Property, func.ST_X(Property.geom), func.ST_Y(Property.geom))
    if not inclure_elimines:
        q = q.where(Property.eliminated.is_(False))
    if not inclure_inactifs:
        q = q.where(Property.is_active.is_(True))
    order = {
        "score": Property.score_total.desc().nulls_last(),
        "prix": Property.price.asc().nulls_last(),
        "recent": Property.first_seen.desc(),
    }[tri]
    rows = db.execute(q.order_by(order).limit(2000)).all()
    enr: dict[int, dict] = {}
    for e in db.scalars(select(Enrichment).where(Enrichment.key.in_(["route", "dvf"]))):
        enr.setdefault(e.property_id, {})[e.key] = e.value
    return [_prop_summary(p, (x, y) if x is not None else None, enr.get(p.id)) for p, x, y in rows]


@router.get("/properties/{pid}")
def get_property(pid: int, db: Session = Depends(get_db)):
    row = db.execute(
        select(Property, func.ST_X(Property.geom), func.ST_Y(Property.geom)).where(Property.id == pid)
    ).first()
    if not row:
        raise HTTPException(404, "Bien introuvable")
    p, x, y = row
    enrs = {e.key: {"valeur": e.value, "source": e.source, "date_donnees": e.source_date, "calcule_le": e.computed_at.isoformat()}
            for e in db.scalars(select(Enrichment).where(Enrichment.property_id == pid))}
    out = _prop_summary(p, (x, y) if x is not None else None, {k: v["valeur"] for k, v in enrs.items()})
    out["enrichissements"] = enrs
    out["candidats_position"] = p.geo_candidates
    out["scores"] = p.scores
    out["analyse"] = p.analysis
    out["notes"] = p.notes
    out["methode_position"] = p.geo_method
    out["annonces"] = [
        {
            "id": li.id, "url": li.url, "source": db.get(Source, li.source_id).name, "prix": li.price,
            "statut": li.status, "premiere_apparition": li.first_seen.isoformat(), "description": li.description,
            "honoraires": li.fees, "dpe": li.dpe, "ges": li.ges, "chauffage": li.heating,
            "assainissement": li.sewage, "dependances": li.outbuildings, "taxe_fonciere": li.property_tax,
            "etat": li.condition, "visite_virtuelle": li.virtual_tour_url, "contact": li.contact,
            "photos": [ph.url for ph in li.photos],
        }
        for li in p.listings
    ]
    ids = [li.id for li in p.listings]
    out["historique"] = [
        {"date": e.observed_at.isoformat(), "evenement": e.event, "prix": e.price, "prix_precedent": e.previous_price}
        for e in db.scalars(select(PriceEvent).where(PriceEvent.listing_id.in_(ids)).order_by(PriceEvent.observed_at))
    ] if ids else []
    return out


class ReactionIn(BaseModel):
    reaction: Literal["aime", "bof", "non"]
    tags: list[str] = []
    comment: str | None = None


@router.post("/properties/{pid}/reaction")
def post_reaction(pid: int, body: ReactionIn, db: Session = Depends(get_db)):
    p = db.get(Property, pid)
    if not p:
        raise HTTPException(404, "Bien introuvable")
    db.add(Reaction(property_id=pid, reaction=body.reaction, tags=body.tags, comment=body.comment))
    p.reaction = body.reaction
    p.seen = True
    db.commit()
    return {"ok": True}


class PropertyPatch(BaseModel):
    statut: Literal["nouveau", "a_voir", "visite", "ecarte"] | None = None
    notes: str | None = None
    vu: bool | None = None


@router.patch("/properties/{pid}")
def patch_property(pid: int, body: PropertyPatch, db: Session = Depends(get_db)):
    p = db.get(Property, pid)
    if not p:
        raise HTTPException(404, "Bien introuvable")
    if body.statut is not None:
        p.status = body.statut
    if body.notes is not None:
        p.notes = body.notes
    if body.vu is not None:
        p.seen = body.vu
    db.commit()
    return {"ok": True}


@router.get("/couches/{nom}")
def couche(nom: str, db: Session = Depends(get_db)):
    """Couches de la carte (GeoJSON) : installations classées, routes importantes, voies ferrées."""
    queries = {
        "icpe": ("SELECT ST_AsGeoJSON(geom) g, jsonb_build_object('nom', name, 'type', kinds[1], 'regime', regime) p FROM icpe_site WHERE kinds && ARRAY['elevage','methaniseur','eolienne']", None),
        "routes": ("SELECT ST_AsGeoJSON(ST_SimplifyPreserveTopology(geom, 0.0003)) g, jsonb_build_object('importance', importance, 'nature', nature) p FROM terr_road WHERE importance IN ('1','2')", None),
        "rail": ("SELECT ST_AsGeoJSON(ST_SimplifyPreserveTopology(geom, 0.0003)) g, jsonb_build_object('nature', nature) p FROM terr_rail", None),
    }
    if nom not in queries:
        raise HTTPException(404, "Couche inconnue")
    rows = db.execute(text(queries[nom][0])).all()
    return {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": json.loads(r.g), "properties": r.p} for r in rows]}


@router.get("/nouveautes/count")
def nouveautes_count(db: Session = Depends(get_db)):
    s = load_settings(db)
    n = db.scalar(
        select(func.count(Property.id)).where(
            Property.seen.is_(False),
            Property.is_active.is_(True),
            Property.eliminated.is_(False),
            (Property.score_total.is_(None)) | (Property.score_total >= s.alertes.score_min),
        )
    )
    return {"count": n}


# -------------------------------------------------- journaux, tâches, sources
@router.get("/runs")
def list_runs(limit: int = 50, db: Session = Depends(get_db)):
    runs = db.scalars(select(RunLog).order_by(RunLog.started_at.desc()).limit(limit))
    return [
        {
            "id": r.id, "tache": r.job, "label": JOBS[r.job].label if r.job in JOBS else r.job,
            "debut": r.started_at.isoformat(), "fin": r.finished_at.isoformat() if r.finished_at else None,
            "statut": r.status, "stats": r.stats, "erreurs": r.errors, "message": r.message,
        }
        for r in runs
    ]


@router.get("/jobs")
def list_jobs():
    nxt = scheduler.next_runs()
    return [
        {"nom": j.name, "label": j.label, "en_cours": is_running(j.name), "prochaine_execution": nxt.get(j.name)}
        for j in JOBS.values()
    ]


@router.post("/jobs/{name}/run")
def trigger_job(name: str):
    if name not in JOBS:
        raise HTTPException(404, "Tâche inconnue")
    started = run_job_async(name)
    return {"lancee": started, "deja_en_cours": not started}


@router.get("/datasources")
def list_datasources(db: Session = Depends(get_db)):
    out = []
    for key, ds in DATASOURCES.items():
        st = db.get(DataSourceStatus, key)
        out.append({
            "cle": key, "nom": ds.name, "url": ds.url, "licence": ds.licence,
            "date_donnees": st.source_date if st else None,
            "derniere_maj": st.last_refresh_at.isoformat() if st and st.last_refresh_at else None,
            "statut": st.status if st else "jamais", "lignes": st.rows if st else None,
            "message": st.message if st else None,
        })
    return out


@router.get("/sources")
def list_sources(db: Session = Depends(get_db)):
    counts = dict(db.execute(select(Listing.source_id, func.count()).where(Listing.status == "active").group_by(Listing.source_id)).all())
    return [
        {
            "id": s.id, "cle": s.key, "nom": s.name, "type": s.kind, "connecteur": s.connector, "url": s.base_url,
            "active": s.enabled, "robots": s.robots_status, "note": s.note, "annonces_actives": counts.get(s.id, 0),
            "derniere_collecte": s.last_run_at.isoformat() if s.last_run_at else None, "dernier_statut": s.last_status,
        }
        for s in db.scalars(select(Source).order_by(Source.kind, Source.name))
    ]


@router.get("/usage")
def api_usage(db: Session = Depends(get_db)):
    s = load_settings(db)
    start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    rows = db.execute(
        select(ApiUsage.provider, func.sum(ApiUsage.cost_eur), func.sum(ApiUsage.requests))
        .where(ApiUsage.ts >= start).group_by(ApiUsage.provider)
    ).all()
    claude = sum(r[1] or 0 for r in rows if r[0] == "anthropic")
    return {
        "mois": start.strftime("%Y-%m"),
        "par_fournisseur": [{"fournisseur": r[0], "cout_eur": round(r[1] or 0, 2), "requetes": r[2]} for r in rows],
        "claude_eur": round(claude, 2),
        "plafond_eur": s.budget_api.plafond_mensuel_eur,
    }
