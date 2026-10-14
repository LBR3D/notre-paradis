import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, dateFr, euros, m2, REACTIONS, scoreColor, STATUTS } from "../api.js";

const EVENTS = { apparition: "Mise en ligne", baisse: "Baisse de prix", hausse: "Hausse de prix", retrait: "Retrait", republication: "Republication" };

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
        <div className="alert">Éliminé : {p.raisons_elimination.map((r) => r.raison || r).join(" · ")}</div>
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
          <dt>Position</dt><dd>confiance {p.confiance_position} {p.methode_position ? `(${p.methode_position})` : ""}</dd>
        </dl>
        {a0.description && <p className="desc">{a0.description}</p>}
      </section>

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
        <p>Notes détaillées et explications (étape 3), données du territoire (étape 2), comparables DVF (étape 1), analyse des photos et questions à poser (étape 3), fiche PDF (étape 4).</p>
      </section>
    </div>
  );
}
