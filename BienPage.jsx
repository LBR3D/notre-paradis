import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, dateFr, euros, m2, REACTIONS, scoreColor, STATUTS } from "../api.js";

const EVENTS = { apparition: "Mise en ligne", baisse: "Baisse de prix", hausse: "Hausse de prix", retrait: "Retrait", republication: "Republication" };

const km = (m) => (m == null ? "aucun à moins de 10 km" : m >= 1000 ? `${(m / 1000).toFixed(1).replace(".", ",")} km` : `${m} m`);

export default function BienPage() {
  const { id } = useParams();
  const [p, setP] = useState(null);
  const [photo, setPhoto] = useState(0);
  const [notes, setNotes] = useState("");
  const [missing, setMissing] = useState(false);

  const load = () =>
    api.get(`/api/properties/${id}`)
      .then((d) => { setP(d); setNotes(d.notes || ""); })
      .catch(() => setMissing(true));
  useEffect(() => {
    load();
    api.patch(`/api/properties/${id}`, { vu: true }).catch(() => {});
  }, [id]);

  if (missing) return <div className="page"><div className="empty">Ce bien n'existe pas (ou plus).</div></div>;
  if (!p) return <div className="page">Chargement…</div>;
  const photos = [...new Set(p.annonces.flatMap((a) => a.photos))];
  const a0 = p.annonces[0] || {};

  const react = async (r) => { await api.post(`/api/properties/${id}/reaction`, { reaction: r }); load(); };
  const setStatut = async (s) => { await api.patch(`/api/properties/${id}`, { statut: s }); load(); };

  return (
    <div className="page bien">
      <div className="bien-head">
        <div>
          <h1>{p.titre || "Bien"}</h1>
          <div className="bien-price">{euros(p.prix)} {p.prix_initial && p.prix < p.prix_initial && <span className="drop">(initialement {euros(p.prix_initial)})</span>}</div>
          <div className="pcard-meta">{m2(p.surface)} · terrain {m2(p.terrain)} · {p.chambres ?? "?"} chambres · DPE {p.dpe || "?"}</div>
        </div>
        <div className="score big" style={{ background: scoreColor(p.score, p.elimine) }}>{p.score != null ? p.score.toFixed(1) : "–"}</div>
      </div>

      {p.elimine && (
        <div className="alert">Éliminé : {p.raisons_elimination.map((r) => r.raison || r).join(" · ")}<br /><small>Vous pouvez modifier les seuils dans Réglages ; le bien reste consultable.</small></div>
      )}

      {p.a_verifier?.length > 0 && (
        <div className="alert warn">
          <b>À vérifier sur place ou sur plan :</b>
          <ul className="plain">{p.a_verifier.map((r, i) => <li key={i}>{r.raison}</li>)}</ul>
        </div>
      )}

      <div className="actions">
        <div className="seg">
          {Object.entries(REACTIONS).map(([k, v]) => (
            <button key={k} className={p.reaction === k ? `on r-${k}` : ""} onClick={() => react(k)}>{v}</button>
          ))}
        </div>
        <select value={p.statut} onChange={(e) => setStatut(e.target.value)}>
          {Object.entries(STATUTS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </div>

      {photos.length > 0 && (
        <div className="gallery">
          <img src={photos[photo]} alt="" />
          <div className="thumbs">
            {photos.map((u, i) => <img key={u} src={u} alt="" className={i === photo ? "on" : ""} onClick={() => setPhoto(i)} />)}
          </div>
        </div>
      )}

      <section className="card">
        <h3>Caractéristiques</h3>
        <dl className="kv">
          <dt>Honoraires</dt><dd>{a0.honoraires || "—"}</dd>
          <dt>DPE / GES</dt><dd>{a0.dpe || "?"} / {a0.ges || "?"}</dd>
          <dt>Chauffage</dt><dd>{a0.chauffage || "—"}</dd>
          <dt>Assainissement</dt><dd>{a0.assainissement || "—"}</dd>
          <dt>Dépendances</dt><dd>{a0.dependances || "—"}</dd>
          <dt>Taxe foncière</dt><dd>{a0.taxe_fonciere ? euros(a0.taxe_fonciere) : "—"}</dd>
          <dt>État déclaré</dt><dd>{a0.etat || "—"}</dd>
          <dt>Position</dt><dd>confiance {p.confiance_position} — {p.methode_position || "inconnue"}</dd>
        </dl>
        {a0.description && <p className="desc">{a0.description}</p>}
      </section>

      {p.enrichissements?.route && (
        <section className="card">
          <h3>Trajet depuis chez vous</h3>
          <dl className="kv">
            <dt>Durée</dt><dd>{Math.floor(p.enrichissements.route.valeur.duree_min / 60)} h {String(p.enrichissements.route.valeur.duree_min % 60).padStart(2, "0")} — {p.enrichissements.route.valeur.source_duree}</dd>
            <dt>Distance</dt><dd>{p.enrichissements.route.valeur.distance_km} km</dd>
          </dl>
          <p className="src">Source : {p.enrichissements.route.source} — {dateFr(p.enrichissements.route.calcule_le)}</p>
        </section>
      )}

      {(p.enrichissements?.bruit || p.enrichissements?.elevage || p.enrichissements?.agriculture || p.enrichissements?.bocage) && (
        <section className="card">
          <h3>Environnement et nuisances</h3>
          <p className="src">Position {p.confiance_position === "A" || p.confiance_position === "B" ? "précise" : "approximative"} (niveau {p.confiance_position}) : les distances sont à prendre avec cette marge.</p>
          {p.enrichissements.bruit && (
            <dl className="kv">
              <dt>Autoroute / voie rapide</dt><dd>{km(p.enrichissements.bruit.valeur.autoroute_m)}</dd>
              <dt>Route importante</dt><dd>{km(p.enrichissements.bruit.valeur.route_chargee_m)}</dd>
              <dt>Voie ferrée en service</dt><dd>{km(p.enrichissements.bruit.valeur.voie_ferree_m)}</dd>
              <dt>Aérodrome</dt><dd>{km(p.enrichissements.bruit.valeur.aerodrome_m)}</dd>
            </dl>
          )}
          {p.enrichissements.elevage && (
            <dl className="kv">
              <dt>Élevages classés proches</dt>
              <dd>{p.enrichissements.elevage.valeur.elevages.length ? p.enrichissements.elevage.valeur.elevages.map((x) => `${x.nom} (${km(x.distance_m)}${x.au_vent ? ", au vent" : ""})`).join(" · ") : "aucun à moins de 10 km"}</dd>
              <dt>Méthaniseurs</dt>
              <dd>{p.enrichissements.elevage.valeur.methaniseurs.length ? p.enrichissements.elevage.valeur.methaniseurs.map((x) => `${x.nom} (${km(x.distance_m)})`).join(" · ") : "aucun à moins de 10 km"}</dd>
              <dt>Éoliennes</dt>
              <dd>{p.enrichissements.elevage.valeur.eoliennes.length ? p.enrichissements.elevage.valeur.eoliennes.map((x) => `${x.nom} (${km(x.distance_m)})`).join(" · ") : "aucune à moins de 10 km"}</dd>
            </dl>
          )}
          {p.enrichissements.agriculture?.valeur.disponible && (
            <>
              <div className="stack">
                <span style={{ width: `${p.enrichissements.agriculture.valeur.prairies}%`, background: "#7cb342" }} title="Prairies" />
                <span style={{ width: `${p.enrichissements.agriculture.valeur.grandes_cultures}%`, background: "#e0b84c" }} title="Grandes cultures" />
                <span style={{ width: `${p.enrichissements.agriculture.valeur.vergers}%`, background: "#d9534f" }} title="Vergers" />
                <span style={{ width: `${p.enrichissements.agriculture.valeur.autres}%`, background: "#9aa" }} title="Autres cultures" />
              </div>
              <p className="src">Dans {p.enrichissements.agriculture.valeur.rayon_m} m : prairies {p.enrichissements.agriculture.valeur.prairies} % · grandes cultures {p.enrichissements.agriculture.valeur.grandes_cultures} % · vergers {p.enrichissements.agriculture.valeur.vergers} % · autres {p.enrichissements.agriculture.valeur.autres} % · hors parcelles agricoles {p.enrichissements.agriculture.valeur.non_declare} % (RPG {p.enrichissements.agriculture.valeur.annee_rpg})</p>
            </>
          )}
          {p.enrichissements.bocage?.valeur.disponible && (
            <dl className="kv">
              <dt>Haies (500 m)</dt><dd>{p.enrichissements.bocage.valeur.haies_m} m linéaires, soit {p.enrichissements.bocage.valeur.haies_m_par_ha} m/ha</dd>
              <dt>Voisin le plus proche</dt><dd>{p.enrichissements.bocage.valeur.voisin_le_plus_proche_m != null ? `${p.enrichissements.bocage.valeur.voisin_le_plus_proche_m} m` : "aucun à moins de 500 m"} · {p.enrichissements.bocage.valeur.batiments_250m} bâtiments à moins de 250 m</dd>
            </dl>
          )}
          <p className="src">Sources : IGN BD TOPO, Géorisques, RPG. Les routes « importantes » sont celles d'importance 1-2 de l'IGN (pas de comptage de trafic) ; les élevages listés sont ceux soumis à déclaration/enregistrement/autorisation.</p>
        </section>
      )}

      {p.enrichissements?.dvf && (
        <section className="card">
          <h3>Prix du marché (ventes réelles)</h3>
          {p.enrichissements.dvf.valeur.estimation ? (
            <>
              <dl className="kv">
                <dt>Estimation</dt><dd>{euros(p.enrichissements.dvf.valeur.estimation)} ({Math.round(p.enrichissements.dvf.valeur.prix_m2_median)} €/m² médian, {p.enrichissements.dvf.valeur.n} ventes, rayon {p.enrichissements.dvf.valeur.rayon_km} km)</dd>
                <dt>Écart</dt><dd>{p.enrichissements.dvf.valeur.ecart_pct > 0 ? "+" : ""}{p.enrichissements.dvf.valeur.ecart_pct} % — marge de négociation théorique {euros(p.enrichissements.dvf.valeur.marge_negociation)}</dd>
              </dl>
              <ul className="plain">
                {p.enrichissements.dvf.valeur.ventes.map((v, i) => <li key={i}>{dateFr(v.date)} — {euros(v.prix)} — {m2(v.surface)}{v.terrain ? ` · terrain ${m2(v.terrain)}` : ""} — {v.adresse}</li>)}
              </ul>
            </>
          ) : <p>{p.enrichissements.dvf.valeur.message}</p>}
          <p className="src">Source : {p.enrichissements.dvf.source} — données jusqu'au {dateFr(p.enrichissements.dvf.date_donnees)}. Estimation indicative : elle ne tient pas compte de l'état ni du terrain.</p>
        </section>
      )}

      <section className="card">
        <h3>Annonces ({p.annonces.length})</h3>
        <ul className="plain">
          {p.annonces.map((a) => (
            <li key={a.id}><a href={a.url} target="_blank" rel="noreferrer">{a.source}</a> — {euros(a.prix)} — {a.statut} — en ligne depuis le {dateFr(a.premiere_apparition)}</li>
          ))}
        </ul>
      </section>

      <section className="card">
        <h3>Historique</h3>
        <ul className="plain">
          {p.historique.map((h, i) => (
            <li key={i}>{dateFr(h.date)} — {EVENTS[h.evenement] || h.evenement} {h.prix ? `— ${euros(h.prix)}` : ""}</li>
          ))}
        </ul>
      </section>

      <section className="card">
        <h3>Mes notes</h3>
        <textarea rows="4" value={notes} onChange={(e) => setNotes(e.target.value)} />
        <button onClick={() => api.patch(`/api/properties/${id}`, { notes })}>Enregistrer</button>
      </section>

      <section className="card muted">
        <h3>À venir</h3>
        <p>Notes détaillées et explications (étape 3), données du territoire (étape 2), analyse des photos et questions à poser (étape 3), fiche PDF (étape 4).</p>
      </section>
    </div>
  );
}
