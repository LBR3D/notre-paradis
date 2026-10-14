// Petit client pour l'API du back-end
async function req(method, url, body) {
  const r = await fetch(url, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await r.json().catch(() => null);
  if (!r.ok) {
    const err = new Error(`Erreur ${r.status}`);
    err.detail = data?.detail;
    throw err;
  }
  return data;
}

export const api = {
  get: (u) => req("GET", u),
  put: (u, b) => req("PUT", u, b),
  post: (u, b) => req("POST", u, b),
  patch: (u, b) => req("PATCH", u, b),
};

export const euros = (n) =>
  n == null ? "—" : n.toLocaleString("fr-FR", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });
export const m2 = (n) => (n == null ? "—" : `${Math.round(n).toLocaleString("fr-FR")} m²`);
export const dateFr = (s) =>
  s ? new Date(s).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—";

// Couleur selon le score (sur 5)
export function scoreColor(score, eliminated) {
  if (eliminated) return "#9b9b9b";
  if (score == null) return "#7a8a99";
  if (score >= 4) return "#2f7d32";
  if (score >= 3.3) return "#7cb342";
  if (score >= 2.5) return "#f2a93b";
  return "#d9534f";
}

export const STATUTS = { nouveau: "Nouveau", a_voir: "À voir", visite: "Visité", ecarte: "Écarté" };
export const REACTIONS = { aime: "J'aime", bof: "Bof", non: "Non" };
