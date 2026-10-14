import { Link } from "react-router-dom";
import { euros, m2, scoreColor, STATUTS, REACTIONS } from "../api.js";

export default function PropertyCard({ p }) {
  return (
    <Link to={`/bien/${p.id}`} className={`pcard ${p.elimine ? "is-elim" : ""}`}>
      <div className="pcard-photo" style={p.photo ? { backgroundImage: `url(${p.photo})` } : {}}>
        {!p.photo && <span>Pas de photo</span>}
        <span className="score" style={{ background: scoreColor(p.score, p.elimine) }}>
          {p.score != null ? p.score.toFixed(1) : "–"}
        </span>
      </div>
      <div className="pcard-body">
        <div className="pcard-title">{p.titre || p.type || "Bien sans titre"}</div>
        <div className="pcard-price">
          {euros(p.prix)}
          {p.prix_initial && p.prix < p.prix_initial && (
            <span className="drop"> −{Math.round((1 - p.prix / p.prix_initial) * 100)} %</span>
          )}
        </div>
        <div className="pcard-meta">
          {m2(p.surface)} · terrain {m2(p.terrain)} · {p.chambres ?? "?"} ch.
        </div>
        <div className="pcard-meta">
          {p.route_min != null && <span>🚗 {Math.floor(p.route_min / 60)} h {String(p.route_min % 60).padStart(2, "0")}{p.route_vendredi ? " (vendredi soir)" : ""}</span>}
          {p.ecart_marche_pct != null && (
            <span className={p.ecart_marche_pct > 10 ? "drop-bad" : p.ecart_marche_pct < -10 ? "drop" : ""}>
              {" · "}{p.ecart_marche_pct > 0 ? "+" : ""}{Math.round(p.ecart_marche_pct)} % vs marché
            </span>
          )}
          {p.nb_annonces > 1 && <span> · {p.nb_annonces} agences</span>}
        </div>
        <div className="pcard-tags">
          {p.statut !== "nouveau" && <span className="tag">{STATUTS[p.statut]}</span>}
          {p.reaction && <span className={`tag r-${p.reaction}`}>{REACTIONS[p.reaction]}</span>}
          {p.elimine && <span className="tag tag-elim">Éliminé</span>}
        </div>
      </div>
    </Link>
  );
}
