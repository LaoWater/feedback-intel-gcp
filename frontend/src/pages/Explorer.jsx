import { useState, useEffect } from "react";
import { api } from "../api";

function SentimentBadge({ sentiment }) {
  return <span className={`badge badge-${sentiment || "neutral"}`}>{sentiment || "—"}</span>;
}

export default function Explorer() {
  const [feedback, setFeedback] = useState([]);
  const [departments, setDepartments] = useState([]);
  const [filters, setFilters] = useState({
    department: "",
    sentiment: "",
    source: "",
  });
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(null);

  useEffect(() => {
    api.departments().then(setDepartments);
  }, []);

  useEffect(() => {
    setLoading(true);
    api.feedback(filters).then((data) => {
      setFeedback(data);
      setLoading(false);
    });
  }, [filters]);

  const updateFilter = (key, value) => {
    setFilters((prev) => ({ ...prev, [key]: value }));
    setSelected(null);
  };

  return (
    <div>
      <h2 style={{ marginBottom: 24 }}>Classification Explorer</h2>

      {/* Filters */}
      <div className="filter-bar">
        <select
          value={filters.department}
          onChange={(e) => updateFilter("department", e.target.value)}
        >
          <option value="">All Departments</option>
          {departments.map((d) => (
            <option key={d.department} value={d.department}>
              {d.department} ({d.count})
            </option>
          ))}
        </select>

        <select
          value={filters.sentiment}
          onChange={(e) => updateFilter("sentiment", e.target.value)}
        >
          <option value="">All Sentiments</option>
          <option value="positive">Positive</option>
          <option value="negative">Negative</option>
          <option value="neutral">Neutral</option>
        </select>

        <select
          value={filters.source}
          onChange={(e) => updateFilter("source", e.target.value)}
        >
          <option value="">All Sources</option>
          <option value="ticket">Ticket</option>
          <option value="review">Review</option>
          <option value="survey">Survey</option>
          <option value="call">Call</option>
        </select>
      </div>

      {/* Detail panel */}
      {selected && (
        <div className="card" style={{ marginBottom: 20 }}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}>
            <h3>Feedback Detail</h3>
            <button
              onClick={() => setSelected(null)}
              style={{ background: "var(--bg-elevated)", color: "var(--text)" }}
            >
              Close
            </button>
          </div>
          <div style={{ display: "flex", gap: 16, marginBottom: 12, flexWrap: "wrap" }}>
            <div>
              <span className="stat-label">Department</span>
              <div style={{ fontWeight: 600 }}>{selected.department}</div>
            </div>
            <div>
              <span className="stat-label">Sentiment</span>
              <div><SentimentBadge sentiment={selected.sentiment} /></div>
            </div>
            <div>
              <span className="stat-label">Tone</span>
              <div>{selected.tone}</div>
            </div>
            <div>
              <span className="stat-label">Source</span>
              <div><span className="badge badge-source">{selected.source}</span></div>
            </div>
            <div>
              <span className="stat-label">Confidence</span>
              <div className="mono" style={{ fontWeight: 600 }}>{selected.confidence}</div>
            </div>
          </div>
          <div className="stat-label">Full Text</div>
          <div className="transcript-text">{selected.text}</div>
        </div>
      )}

      {/* Table */}
      {loading ? (
        <div className="loading">Loading...</div>
      ) : (
        <div className="card">
          <div className="card-title">{feedback.length} records</div>
          <table className="data-table">
            <thead>
              <tr>
                <th>Source</th>
                <th>Department</th>
                <th>Sentiment</th>
                <th>Confidence</th>
                <th>Text</th>
              </tr>
            </thead>
            <tbody>
              {feedback.map((f) => (
                <tr
                  key={f.id}
                  onClick={() => setSelected(f)}
                  style={{ cursor: "pointer" }}
                >
                  <td><span className="badge badge-source">{f.source}</span></td>
                  <td>{f.department}</td>
                  <td><SentimentBadge sentiment={f.sentiment} /></td>
                  <td className="mono">{f.confidence?.toFixed(3)}</td>
                  <td className="text-preview">{f.text}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
