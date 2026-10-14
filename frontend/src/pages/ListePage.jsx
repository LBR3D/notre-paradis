import { useEffect, useMemo, useState } from "react";
import { api } from "../api.js";
import PropertyCard from "../components/PropertyCard.jsx";

export default function ListePage() {
  const [items, setItems] = useState(null);
  const [tri, setTri] = useState("score");
  const [elim, setElim] = useState(false);
  const [inactifs, setInactifs] = useState(false);
  const [statut, setStatut] = useState("");
  const [prixMax, setPrixMax] = useState("");

  useEffect(() => {
    api.get(`/api/properties?tri=${tri}&inclure_elimines=${elim}&inclure_inactifs=${inactifs}`).then(setItems);
  }, [tri, elim, inactifs]);

  const shown = useMemo(
    () => (items || []).filter((p) => (!statut || p.statut === statut) && (!prixMax || (p.prix ?? 0) <= +prixMax)),
    [items, statut, prixMax]
  );

  return (
    <div className="page">
      <div className="toolbar">
        <label>Trier par{" "}
          <select value={tri} onChange={(e) => setTri(e.target.value)}>
            <option value="score">Score</option>
            <option value="prix">Prix</option>
            <option value="recent">Plus récents</option>
          </select>
        </label>
        <label>Statut{" "}
          <select value={statut} onChange={(e) => setStatut(e.target.value)}>
            <option value="">Tous</option>
            <option value="nouveau">Nouveau</option>
            <option value="a_voir">À voir</option>
            <option value="visite">Visité</option>
            <option value="ecarte">Écarté</option>
          </select>
        </label>
        <label>Prix max <input type="number" step="10000" value={prixMax} onChange={(e) => setPrixMax(e.target.value)} placeholder="€" /></label>
        <label><input type="checkbox" checked={elim} onChange={(e) => setElim(e.target.checked)} /> Éliminés</label>
        <label><input type="checkbox" checked={inactifs} onChange={(e) => setInactifs(e.target.checked)} /> Retirés du marché</label>
        <span className="count">{shown.length} bien(s)</span>
      </div>
      {items == null ? <p>Chargement…</p> : shown.length === 0 ? (
        <div className="empty">Aucun bien pour l'instant. La collecte automatique sera branchée à l'étape 1.</div>
      ) : (
        <div className="grid">{shown.map((p) => <PropertyCard key={p.id} p={p} />)}</div>
      )}
    </div>
  );
}
