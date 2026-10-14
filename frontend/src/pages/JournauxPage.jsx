import { Fragment, useEffect, useState } from "react";
import { api, dateFr } from "../api.js";

const STATUT = { succes: "Succès", partiel: "Partiel", erreur: "Erreur", en_cours: "En cours", ok: "OK", jamais: "Jamais" };

export default function JournauxPage() {
  const [jobs, setJobs] = useState([]);
  const [runs, setRuns] = useState([]);
  const [ds, setDs] = useState([]);
  const [sources, setSources] = useState([]);
  const [usage, setUsage] = useState(null);
  const [open, setOpen] = useState(null);

  const load = () => {
    api.get("/api/jobs").then(setJobs);
    api.get("/api/runs").then(setRuns);
    api.get("/api/datasources").then(setDs);
    api.get("/api/sources").then(setSources);
    api.get("/api/usage").then(setUsage);
  };
  useEffect(() => {
    load();
    const t = setInterval(load, 10000);
    return () => clearInterval(t);
  }, []);

  const run = async (name) => { await api.post(`/api/jobs/${encodeURIComponent(name)}/run`); setTimeout(load, 500); };

  return (
    <div className="page">
      <section className="card">
        <h3>Budget API du mois</h3>
        {usage && (
          <>
            <div className="meter"><div style={{ width: `${Math.min(100, (usage.claude_eur / usage.plafond_eur) * 100)}%` }} /></div>
            <p>Claude : {usage.claude_eur.toFixed(2)} € sur {usage.plafond_eur} € ·{" "}
              {usage.par_fournisseur.filter((f) => f.fournisseur !== "anthropic").map((f) => `${f.fournisseur} : ${f.requetes} requêtes`).join(" · ") || "aucune autre API utilisée"}
            </p>
          </>
        )}
      </section>

      <section className="card">
        <h3>Tâches</h3>
        <table>
          <thead><tr><th>Tâche</th><th>Prochaine exécution</th><th></th></tr></thead>
          <tbody>
            {jobs.map((j) => (
              <tr key={j.nom}>
                <td>{j.label}</td>
                <td>{j.prochaine_execution ? dateFr(j.prochaine_execution) : "manuelle"}</td>
                <td><button disabled={j.en_cours} onClick={() => run(j.nom)}>{j.en_cours ? "En cours…" : "Lancer"}</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="card">
        <h3>Journal des exécutions</h3>
        <table>
          <thead><tr><th>Début</th><th>Tâche</th><th>Statut</th><th>Résultat</th></tr></thead>
          <tbody>
            {runs.map((r) => (
              <Fragment key={r.id}>
                <tr onClick={() => setOpen(open === r.id ? null : r.id)} className="clickable">
                  <td>{dateFr(r.debut)}</td>
                  <td>{r.label}</td>
                  <td><span className={`st st-${r.statut}`}>{STATUT[r.statut] || r.statut}</span></td>
                  <td className="small">{Object.entries(r.stats || {}).map(([k, v]) => `${k} : ${v}`).join(" · ")}{r.erreurs?.length ? ` · ${r.erreurs.length} erreur(s)` : ""}</td>
                </tr>
                {open === r.id && (
                  <tr><td colSpan="4"><pre className="log">{[...(r.erreurs || []).map((e) => `⚠ ${e.ou} : ${e.erreur}`), r.message].filter(Boolean).join("\n")}</pre></td></tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </section>

      <section className="card">
        <h3>Données publiques en cache</h3>
        <table>
          <thead><tr><th>Données</th><th>Date des données</th><th>Mise à jour</th><th>Statut</th></tr></thead>
          <tbody>
            {ds.map((d) => (
              <tr key={d.cle}>
                <td><a href={d.url} target="_blank" rel="noreferrer">{d.nom}</a><div className="small">{d.licence}</div></td>
                <td>{d.date_donnees || "—"}</td>
                <td>{dateFr(d.derniere_maj)}</td>
                <td><span className={`st st-${d.statut}`}>{STATUT[d.statut] || d.statut}</span> {d.lignes ? `(${d.lignes.toLocaleString("fr-FR")})` : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="card">
        <h3>Sources d'annonces ({sources.length})</h3>
        {sources.length === 0 ? <p className="hint">Les agences de la zone seront découvertes à l'étape 1.</p> : (
          <table>
            <thead><tr><th>Source</th><th>Type</th><th>robots.txt</th><th>Annonces</th><th>Dernière collecte</th></tr></thead>
            <tbody>
              {sources.map((s) => (
                <tr key={s.id}>
                  <td><a href={s.url} target="_blank" rel="noreferrer">{s.nom}</a></td>
                  <td>{s.type}</td><td>{s.robots}</td><td>{s.annonces_actives}</td>
                  <td>{dateFr(s.derniere_collecte)} {s.dernier_statut ? `(${STATUT[s.dernier_statut] || s.dernier_statut})` : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
