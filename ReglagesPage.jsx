import { useEffect, useMemo, useState } from "react";
import { api } from "../api.js";

// Formulaire généré automatiquement à partir du schéma des réglages (back-end).
// Ajouter un réglage côté Python suffit : il apparaît ici.

function RefPicker({ kind, value, onChange }) {
  const [names, setNames] = useState({});
  const [q, setQ] = useState("");
  const [sugg, setSugg] = useState([]);

  useEffect(() => {
    const missing = value.filter((c) => !names[c]);
    if (!missing.length) return;
    api.get(`/api/${kind}?codes=${missing.join(",")}`).then((rows) =>
      setNames((n) => ({ ...n, ...Object.fromEntries(rows.map((r) => [r.code, r.nom + (r.departement ? ` (${r.departement})` : "")])) }))
    );
  }, [value, kind]);

  useEffect(() => {
    if (q.length < 2) return setSugg([]);
    const t = setTimeout(() => api.get(`/api/${kind}?q=${encodeURIComponent(q)}`).then(setSugg), 250);
    return () => clearTimeout(t);
  }, [q, kind]);

  return (
    <div className="refpicker">
      <div className="chips">
        {value.map((c) => (
          <span key={c} className="chip on">
            {names[c] || c}
            <button type="button" aria-label="Retirer" onClick={() => onChange(value.filter((x) => x !== c))}>×</button>
          </span>
        ))}
      </div>
      <input placeholder={kind === "epci" ? "Ajouter une intercommunalité…" : "Ajouter une commune…"} value={q} onChange={(e) => setQ(e.target.value)} />
      {sugg.length > 0 && (
        <ul className="sugg">
          {sugg.filter((s) => !value.includes(s.code)).map((s) => (
            <li key={s.code} onClick={() => { onChange([...value, s.code]); setNames((n) => ({ ...n, [s.code]: s.nom })); setQ(""); }}>
              {s.nom}{s.departement ? ` (${s.departement})` : ""}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Field({ name, sch, value, onChange, error }) {
  const label = sch.title || name;
  let input;
  const isNum = sch.type === "integer" || sch.type === "number";

  if (sch.type === "boolean") {
    return (
      <label className="field field-bool">
        <input type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} />
        <span>{label}</span>
        {sch.description && <small>{sch.description}</small>}
      </label>
    );
  }
  if (isNum && sch.minimum != null && sch.maximum != null && sch.maximum - sch.minimum <= 100) {
    input = (
      <div className="range">
        <input type="range" min={sch.minimum} max={sch.maximum} step={sch.step || (sch.type === "integer" ? 1 : 0.5)}
          value={value} onChange={(e) => onChange(Number(e.target.value))} />
        <output>{value}</output>
      </div>
    );
  } else if (isNum) {
    input = <input type="number" min={sch.minimum} max={sch.maximum} step={sch.step || "any"} value={value ?? ""}
      onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))} />;
  } else if (sch.type === "array" && sch.items?.enum) {
    input = (
      <div className="chips">
        {sch.items.enum.map((opt) => {
          const on = value.includes(opt);
          return (
            <button type="button" key={opt} className={`chip ${on ? "on" : ""}`}
              onClick={() => onChange(on ? value.filter((v) => v !== opt) : [...value, opt])}>{opt}</button>
          );
        })}
      </div>
    );
  } else if (sch.type === "array" && sch.widget === "heures") {
    input = (
      <div className="chips">
        {Array.from({ length: 24 }, (_, h) => {
          const on = value.includes(h);
          return (
            <button type="button" key={h} className={`chip small ${on ? "on" : ""}`}
              onClick={() => onChange(on ? value.filter((v) => v !== h) : [...value, h].sort((a, b) => a - b))}>{h}h</button>
          );
        })}
      </div>
    );
  } else if (sch.type === "array" && (sch.widget === "epci" || sch.widget === "communes")) {
    input = <RefPicker kind={sch.widget === "epci" ? "epci" : "communes"} value={value} onChange={onChange} />;
  } else {
    input = <input type="text" value={value ?? ""} onChange={(e) => onChange(e.target.value)} />;
  }
  return (
    <div className={`field ${error ? "has-error" : ""}`}>
      <span className="field-label">{label}</span>
      {input}
      {sch.description && <small>{sch.description}</small>}
      {error && <small className="err">{error}</small>}
    </div>
  );
}

export default function ReglagesPage() {
  const [data, setData] = useState(null);
  const [values, setValues] = useState(null);
  const [errors, setErrors] = useState({});
  const [saved, setSaved] = useState("");

  useEffect(() => {
    api.get("/api/settings").then((d) => { setData(d); setValues(d.values); });
  }, []);

  const dirty = useMemo(() => data && JSON.stringify(values) !== JSON.stringify(data.values), [data, values]);

  if (!data) return <div className="page">Chargement…</div>;
  const defs = data.schema.$defs;

  const save = async () => {
    try {
      const r = await api.put("/api/settings", values);
      setData({ ...data, values: r.values });
      setValues(r.values);
      setErrors({});
      setSaved("Réglages enregistrés.");
      setTimeout(() => setSaved(""), 3000);
    } catch (e) {
      const errs = {};
      (e.detail || []).forEach((d) => (errs[d.loc.join(".")] = d.msg));
      setErrors(errs);
      setSaved("Certaines valeurs sont invalides.");
    }
  };

  const reset = async (section) => {
    const r = await api.post(`/api/settings/reset/${section}`);
    setData({ ...data, values: r.values });
    setValues(r.values);
  };

  return (
    <div className="page reglages">
      <div className="toolbar sticky">
        <h2>Réglages</h2>
        <span className="hint">{saved || (dirty ? "Modifications non enregistrées" : "")}</span>
        <button className="primary" disabled={!dirty} onClick={save}>Enregistrer</button>
      </div>
      {Object.entries(data.schema.properties).map(([section, ref]) => {
        const def = defs[ref.$ref.split("/").pop()];
        return (
          <details key={section} className="card" open={section === "criteres"}>
            <summary>
              <h3>{ref.title || def.title || section}</h3>
              {def.description && <span className="hint">{def.description}</span>}
            </summary>
            <div className="fields">
              {Object.entries(def.properties).map(([name, sch]) => (
                <Field key={name} name={name} sch={sch} value={values[section][name]} error={errors[`${section}.${name}`]}
                  onChange={(v) => setValues({ ...values, [section]: { ...values[section], [name]: v } })} />
              ))}
            </div>
            <button className="link" onClick={() => reset(section)}>Revenir aux valeurs par défaut</button>
          </details>
        );
      })}
    </div>
  );
}
