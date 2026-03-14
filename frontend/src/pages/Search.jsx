import { useState } from "react";
import { api } from "../api";

function SentimentBadge({ sentiment }) {
  return <span className={`badge badge-${sentiment || "neutral"}`}>{sentiment || "—"}</span>;
}

export default function Search() {
  const [query, setQuery] = useState("");
  const [department, setDepartment] = useState("");
  const [source, setSource] = useState("");
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const doSearch = async (e) => {
    e.preventDefault();
    if (!query.trim()) return;

    setLoading(true);
    setError(null);
    try {
      const data = await api.search(query, department || null, source || null);
      setResults(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <h2 style={{ marginBottom: 8 }}>Semantic Search</h2>
      <p style={{ color: "var(--text-dim)", marginBottom: 24, fontSize: 13 }}>
        Powered by Vertex AI Search — natural language queries over all feedback
      </p>

      <form onSubmit={doSearch}>
        <div className="filter-bar">
          <input
            type="search"
            className="search-input"
            placeholder='Try "what are customers saying about login problems"'
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button type="submit" disabled={loading || !query.trim()}>
            {loading ? "Searching..." : "Search"}
          </button>
        </div>

        <div className="filter-bar">
          <select value={department} onChange={(e) => setDepartment(e.target.value)}>
            <option value="">All Departments</option>
            <option value="Engineering">Engineering</option>
            <option value="Product">Product</option>
            <option value="UX">UX</option>
            <option value="Support">Support</option>
            <option value="Sales">Sales</option>
            <option value="Marketing">Marketing</option>
            <option value="Security">Security</option>
            <option value="Data">Data</option>
          </select>

          <select value={source} onChange={(e) => setSource(e.target.value)}>
            <option value="">All Sources</option>
            <option value="ticket">Ticket</option>
            <option value="review">Review</option>
            <option value="survey">Survey</option>
            <option value="call">Call</option>
          </select>
        </div>
      </form>

      {error && <div className="error">{error}</div>}

      {results && (
        <div>
          {/* AI Summary */}
          {results.summary && (
            <div className="search-summary">
              <div className="card-title" style={{ color: "var(--accent)" }}>
                AI Summary
              </div>
              {results.summary}
            </div>
          )}

          {/* Results */}
          <div className="card">
            <div className="card-title">
              {results.total_results} results for "{results.query}"
            </div>

            {results.results.map((r, i) => (
              <div key={r.id || i} className="search-result">
                <div style={{ display: "flex", gap: 8, marginBottom: 8, alignItems: "center" }}>
                  <SentimentBadge sentiment={r.sentiment} />
                  <span className="badge badge-source">{r.source}</span>
                  <span style={{ color: "var(--text-dim)", fontSize: 12 }}>
                    {r.department}
                  </span>
                  <span className="mono" style={{ color: "var(--text-dim)", fontSize: 11, marginLeft: "auto" }}>
                    conf: {r.confidence?.toFixed(3)}
                  </span>
                </div>
                <div style={{ fontSize: 13, lineHeight: 1.6 }}>{r.text}</div>
              </div>
            ))}

            {results.total_results === 0 && (
              <div style={{ padding: 20, color: "var(--text-dim)", textAlign: "center" }}>
                No results found. Try a different query.
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
