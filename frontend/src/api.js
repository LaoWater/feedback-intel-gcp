const BASE = import.meta.env.VITE_API_URL || "";

async function get(path) {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export const api = {
  stats: () => get("/api/stats"),
  chirpStats: () => get("/api/chirp-stats"),
  transcripts: (limit = 20) => get(`/api/transcripts?limit=${limit}`),
  transcript: (id) => get(`/api/transcript/${id}`),
  feedback: (params = {}) => {
    const qs = new URLSearchParams();
    if (params.department) qs.set("department", params.department);
    if (params.sentiment) qs.set("sentiment", params.sentiment);
    if (params.source) qs.set("source", params.source);
    if (params.min_confidence) qs.set("min_confidence", params.min_confidence);
    if (params.limit) qs.set("limit", params.limit);
    return get(`/api/feedback?${qs}`);
  },
  departments: () => get("/api/departments"),
  search: (q, department, source) => {
    const qs = new URLSearchParams({ q });
    if (department) qs.set("department", department);
    if (source) qs.set("source", source);
    return get(`/api/search?${qs}`);
  },
};
