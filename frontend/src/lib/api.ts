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

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.detail || body.error || `${r.status}`);
  return body as T;
}

export const api = {
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
  provider: (token: string) => req<any>(`/api/provider/${token}`),
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
