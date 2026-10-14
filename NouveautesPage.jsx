import { useEffect, useState } from "react";
import { api } from "../api.js";
import PropertyCard from "../components/PropertyCard.jsx";

export default function NouveautesPage({ onChange }) {
  const [items, setItems] = useState(null);
  const load = () =>
    api.get("/api/properties?tri=recent").then((all) => setItems(all.filter((p) => !p.vu && !p.elimine)));
  useEffect(() => { load(); }, []);

  const toutVu = async () => {
    await Promise.all(items.map((p) => api.patch(`/api/properties/${p.id}`, { vu: true })));
    onChange?.(0);
    load();
  };

  return (
    <div className="page">
      <div className="toolbar">
        <h2>Nouveautés</h2>
        <span className="hint">Nouveaux biens et baisses de prix au-dessus de votre score minimum.</span>
        {items?.length > 0 && <button onClick={toutVu}>Tout marquer comme vu</button>}
      </div>
      {items == null ? <p>Chargement…</p> : items.length === 0 ? (
        <div className="empty">Rien de nouveau.</div>
      ) : (
        <div className="grid">{items.map((p) => <PropertyCard key={p.id} p={p} />)}</div>
      )}
    </div>
  );
}
