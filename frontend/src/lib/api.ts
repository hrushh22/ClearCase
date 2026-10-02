export type Src = {
  fact_id?: string;
  source_type: string;
  source_id: string;
  page?: number | null;
  quote?: string | null;
  date?: string | null;
  title?: string | null;
};

export type Fact = Src & {
  fact_id: string;
  type: string;
  text: string;
  amount?: number | null;
  entity?: string | null;
  verify_status: string;
  verify_reason?: string;
  extractor: string;
  confidence?: number;
};

// The digest is a large generated document; typed loosely on purpose.
export type Digest = any;

// Where the backend lives. Empty = same origin (local: the backend serves this app).
// On GitHub Pages it is set at build time: VITE_API_BASE=https://<space>.hf.space
export const API_BASE = (import.meta.env.VITE_API_BASE || "").replace(/\/$/, "");

const TOKEN_KEY = "clearcase.session";
export const session = {
  get: (): string | null => { try { return localStorage.getItem(TOKEN_KEY); } catch { return null; } },
  set: (t: string | null) => { try { t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY); } catch { /* private mode */ } },
};

/** A backend URL with the session token attached, for links opened in a new tab or fetched by pdf.js. */
export const authedUrl = (path: string) => {
  const t = session.get();
  const [p, hash] = path.split("#");
  return `${API_BASE}${p}${t ? `${p.includes("?") ? "&" : "?"}t=${encodeURIComponent(t)}` : ""}${hash ? `#${hash}` : ""}`;
};

/** Absolute link to a page of this app (hash routes work on GitHub Pages without server rewrites). */
export const appUrl = (route: string) => `${window.location.origin}${window.location.pathname}#${route}`;

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const t = session.get();
  const r = await fetch(`${API_BASE}${path}`, {
    ...init, headers: { "Content-Type": "application/json", ...(t ? { Authorization: `Bearer ${t}` } : {}), ...(init?.headers || {}) },
  });
  const body = await r.json().catch(() => ({}));
  if (r.status === 401 && !path.startsWith("/api/provider/") && !path.startsWith("/api/login")) {
    session.set(null);
    window.dispatchEvent(new Event("clearcase:auth"));  // App shows the password screen
  }
  if (!r.ok) throw new Error(body.detail || body.error || `${r.status}`);
  return body as T;
}

export const api = {
  health: () => req<any>("/api/health"),
  login: (password: string) => req<any>("/api/login", { method: "POST", body: JSON.stringify({ password }) }),
  status: () => req<any>("/api/status"),
  sync: (force = false) => req<any>(`/api/sync?force=${force}`, { method: "POST" }),
  digest: () => req<Digest>("/api/digest?user=attorney"),
  seen: () => req<any>("/api/views/seen?user=attorney", { method: "POST" }),
  source: (t: string, id: string) => req<any>(`/api/source/${t}/${encodeURIComponent(id)}`),
  locate: (doc: string, quote: string, page?: number | null) =>
    req<any>(`/api/documents/${doc}/locate?quote=${encodeURIComponent(quote)}${page ? `&page=${page}` : ""}`),
  waterfallSettings: () => req<any>("/api/waterfall/settings"),
  waterfall: (body: any) => req<any>("/api/waterfall", { method: "POST", body: JSON.stringify(body) }),
  waterfallReset: () => req<any>("/api/waterfall/reset", { method: "POST" }),
  providers: () => req<any[]>("/api/providers"),
  proposal: (id: string) => req<any>(`/api/share/proposal/${id}`),
  createLink: (body: any) => req<any>("/api/share/links", { method: "POST", body: JSON.stringify(body) }),
  links: () => req<any[]>("/api/share/links"),
  revoke: (token: string) => req<any>(`/api/share/links/${token}/revoke`, { method: "POST" }),
  provider: (token: string, poll = false) => req<any>(`/api/provider/${token}${poll ? "?poll=true" : ""}`),
  refreshLinks: () => req<any>("/api/share/refresh", { method: "POST" }),
  subscribe: (token: string, email: string) =>
    req<any>(`/api/provider/${token}/subscribe`, { method: "POST", body: JSON.stringify({ email }) }),
  events: () => req<any[]>("/api/events"),
  xray: (asOf?: string) => req<any>(`/api/attorney/xray${asOf ? `?as_of=${asOf}` : ""}`),
  xrayAction: (issueId: string, action_type: string, content?: string) =>
    req<any>(`/api/attorney/xray/issues/${issueId}/actions`, { method: "POST", body: JSON.stringify({ action_type, content }) }),
  stressTest: (force = false) => req<any>(`/api/attorney/xray/stress-test?force=${force}`, { method: "POST" }),
};

export const money = (v?: number | null, digits = 0) =>
  v === null || v === undefined || Number.isNaN(v)
    ? "—"
    : v.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: digits, minimumFractionDigits: digits });

export const fmtDate = (d?: string | null) => {
  if (!d) return "—";
  const dt = new Date(d.length === 10 ? d + "T12:00:00" : d);
  return dt.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
};

export const fmtDateTime = (d?: string | null) =>
  d ? new Date(d).toLocaleString("en-US", { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" }) : "—";

export const daysFrom = (d?: string | null) => {
  if (!d) return null;
  const ms = new Date(d.slice(0, 10) + "T12:00:00").getTime() - new Date(new Date().toISOString().slice(0, 10) + "T12:00:00").getTime();
  return Math.round(ms / 86400000);
};

export const SOURCE_LABEL: Record<string, string> = {
  note: "Note", communication: "Email/Call", task: "Task", calendar: "Calendar", document: "Document",
  custom_field: "Clio field", expense: "Expense", matter: "Matter", contact: "Contact",
};
