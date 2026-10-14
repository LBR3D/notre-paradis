import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import * as maplibregl from "maplibre-gl";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url";
import { api, euros, scoreColor } from "../api.js";

// Le « worker » de MapLibre doit être servi comme fichier séparé une fois l'application compilée
maplibregl.setWorkerUrl(workerUrl);

const wmts = (layer, format) =>
  `https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=${layer}` +
  `&STYLE=normal&TILEMATRIXSET=PM&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&FORMAT=${format}`;

const STYLE = {
  version: 8,
  sources: {
    plan: { type: "raster", tiles: [wmts("GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2", "image/png")], tileSize: 256, attribution: "© IGN" },
    ortho: { type: "raster", tiles: [wmts("ORTHOIMAGERY.ORTHOPHOTOS", "image/jpeg")], tileSize: 256, attribution: "© IGN" },
  },
  layers: [
    { id: "plan", type: "raster", source: "plan" },
    { id: "ortho", type: "raster", source: "ortho", layout: { visibility: "none" } },
  ],
};

export default function CartePage() {
  const el = useRef(null);
  const map = useRef(null);
  const nav = useNavigate();
  const [fond, setFond] = useState("plan");
  const [showElim, setShowElim] = useState(false);
  const [props, setProps] = useState([]);
  const [layers, setLayers] = useState({ zone: true });

  useEffect(() => {
    const m = new maplibregl.Map({ container: el.current, style: STYLE, center: [0.2, 49.15], zoom: 9.2 });
    map.current = m;
    m.addControl(new maplibregl.NavigationControl(), "top-right");
    m.addControl(new maplibregl.ScaleControl({ unit: "metric" }));
    m.on("load", async () => {
      const zone = await api.get("/api/zone");
      m.addSource("zone", { type: "geojson", data: zone });
      m.addLayer({
        id: "zone-fill", type: "fill", source: "zone",
        paint: { "fill-color": ["case", ["get", "penalisee"], "#e08a2c", "#3f6b3a"], "fill-opacity": ["case", ["get", "penalisee"], 0.22, 0.07] },
      });
      m.addLayer({ id: "zone-line", type: "line", source: "zone", paint: { "line-color": "#3f6b3a", "line-width": 0.6, "line-opacity": 0.5 } });
      m.addSource("biens", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      m.addLayer({
        id: "biens", type: "circle", source: "biens",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 8, 5, 14, 10],
          "circle-color": ["get", "couleur"],
          "circle-stroke-color": "#fff",
          "circle-stroke-width": 1.5,
        },
      });
      m.on("click", "biens", (e) => {
        const f = e.features[0].properties;
        const html = `<div class="popup">
          ${f.photo ? `<img src="${f.photo}" alt="">` : ""}
          <b>${f.titre || "Bien"}</b><br>${f.prix}<br><a href="/bien/${f.id}" data-id="${f.id}">Voir la fiche →</a></div>`;
        const pop = new maplibregl.Popup({ maxWidth: "260px" }).setLngLat(e.lngLat).setHTML(html).addTo(m);
        pop.getElement().querySelector("a")?.addEventListener("click", (ev) => { ev.preventDefault(); nav(`/bien/${f.id}`); });
      });
      m.on("mouseenter", "biens", () => (m.getCanvas().style.cursor = "pointer"));
      m.on("mouseleave", "biens", () => (m.getCanvas().style.cursor = ""));
      m.on("click", "zone-fill", (e) => {
        if (m.queryRenderedFeatures(e.point, { layers: ["biens"] }).length) return;
        const f = e.features[0].properties;
        new maplibregl.Popup({ closeButton: false }).setLngLat(e.lngLat)
          .setHTML(`<div class="popup">${f.nom}${f.penalisee ? "<br><i>Commune pénalisée</i>" : ""}</div>`).addTo(m);
      });
      api.get("/api/properties?inclure_elimines=true").then(setProps);
    });
    return () => m.remove();
  }, [nav]);

  useEffect(() => {
    const m = map.current;
    if (!m?.getSource("biens")) return;
    const features = props
      .filter((p) => p.lon != null && (showElim || !p.elimine))
      .map((p) => ({
        type: "Feature",
        geometry: { type: "Point", coordinates: [p.lon, p.lat] },
        properties: { id: p.id, titre: p.titre, prix: euros(p.prix), photo: p.photo, couleur: scoreColor(p.score, p.elimine) },
      }));
    m.getSource("biens").setData({ type: "FeatureCollection", features });
  }, [props, showElim]);

  useEffect(() => {
    const m = map.current;
    if (!m?.getLayer("plan")) return;
    m.setLayoutProperty("plan", "visibility", fond === "plan" ? "visible" : "none");
    m.setLayoutProperty("ortho", "visibility", fond === "ortho" ? "visible" : "none");
  }, [fond]);

  useEffect(() => {
    const m = map.current;
    if (!m?.getLayer("zone-fill")) return;
    const v = layers.zone ? "visible" : "none";
    m.setLayoutProperty("zone-fill", "visibility", v);
    m.setLayoutProperty("zone-line", "visibility", v);
  }, [layers]);

  const located = props.filter((p) => p.lon != null).length;

  return (
    <div className="map-page">
      <div ref={el} className="map" />
      <div className="map-panel">
        <div className="seg">
          <button className={fond === "plan" ? "on" : ""} onClick={() => setFond("plan")}>Plan</button>
          <button className={fond === "ortho" ? "on" : ""} onClick={() => setFond("ortho")}>Photo aérienne</button>
        </div>
        <label><input type="checkbox" checked={layers.zone} onChange={(e) => setLayers({ ...layers, zone: e.target.checked })} /> Zone de recherche</label>
        <label><input type="checkbox" checked={showElim} onChange={(e) => setShowElim(e.target.checked)} /> Biens éliminés</label>
        <div className="hint">Calques à venir : isochrone 3 h, cultures (RPG), routes bruyantes, risques, éoliennes.</div>
        <div className="legend">
          <span><i style={{ background: "#2f7d32" }} />≥ 4</span>
          <span><i style={{ background: "#7cb342" }} />3,3–4</span>
          <span><i style={{ background: "#f2a93b" }} />2,5–3,3</span>
          <span><i style={{ background: "#d9534f" }} />&lt; 2,5</span>
          <span><i style={{ background: "#e08a2c", opacity: 0.5 }} />Côte fleurie</span>
        </div>
        <div className="hint">{props.length ? `${located} bien(s) localisé(s) sur ${props.length}` : "Aucun bien pour l'instant : la collecte arrive à l'étape 1."}</div>
      </div>
    </div>
  );
}
