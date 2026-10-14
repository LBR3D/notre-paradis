import { useEffect, useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { api } from "./api.js";
import CartePage from "./pages/CartePage.jsx";
import ListePage from "./pages/ListePage.jsx";
import BienPage from "./pages/BienPage.jsx";
import NouveautesPage from "./pages/NouveautesPage.jsx";
import ReglagesPage from "./pages/ReglagesPage.jsx";
import JournauxPage from "./pages/JournauxPage.jsx";

export default function App() {
  const [nouveautes, setNouveautes] = useState(0);
  useEffect(() => {
    const load = () => api.get("/api/nouveautes/count").then((d) => setNouveautes(d.count)).catch(() => {});
    load();
    const t = setInterval(load, 60000);
    return () => clearInterval(t);
  }, []);

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <svg viewBox="0 0 32 32" width="22" height="22" aria-hidden="true">
            <path d="M4 16 16 5l12 11v12H4z" fill="currentColor" />
            <rect x="13" y="19" width="6" height="9" fill="var(--bg)" />
          </svg>
          Notre paradis
        </div>
        <nav>
          <NavLink to="/" end>Carte</NavLink>
          <NavLink to="/liste">Liste</NavLink>
          <NavLink to="/nouveautes">
            Nouveautés{nouveautes > 0 && <span className="badge">{nouveautes}</span>}
          </NavLink>
          <NavLink to="/reglages">Réglages</NavLink>
          <NavLink to="/journaux">Journaux</NavLink>
        </nav>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<CartePage />} />
          <Route path="/liste" element={<ListePage />} />
          <Route path="/bien/:id" element={<BienPage />} />
          <Route path="/nouveautes" element={<NouveautesPage onChange={setNouveautes} />} />
          <Route path="/reglages" element={<ReglagesPage />} />
          <Route path="/journaux" element={<JournauxPage />} />
        </Routes>
      </main>
    </div>
  );
}
