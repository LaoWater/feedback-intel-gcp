import { useState, useEffect } from "react";
import { api } from "../api";

function SentimentBadge({ sentiment }) {
  const cls = `badge badge-${sentiment || "neutral"}`;
  return <span className={cls}>{sentiment || "—"}</span>;
}

function TranscriptDetail({ id, onClose }) {
  const [data, setData] = useState(null);

  useEffect(() => {
    api.transcript(id).then(setData);
  }, [id]);

  if (!data) return <div className="loading">Loading transcript...</div>;

  return (
    <div className="card" style={{ marginBottom: 20 }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 16 }}>
        <h3>Transcript Detail</h3>
        <button onClick={onClose} style={{ background: "var(--bg-elevated)", color: "var(--text)" }}>
          Close
        </button>
      </div>

      <div className="stat-grid" style={{ marginBottom: 16 }}>
        <div>
          <span className="stat-label">Department</span>
          <div style={{ fontWeight: 600 }}>{data.department || "—"}</div>
        </div>
        <div>
          <span className="stat-label">Sentiment</span>
          <div><SentimentBadge sentiment={data.sentiment} /></div>
        </div>
        <div>
          <span className="stat-label">Tone</span>
          <div style={{ fontWeight: 600 }}>{data.tone || "—"}</div>
        </div>
        <div>
          <span className="stat-label">Chirp Confidence</span>
          <div className="mono" style={{ fontWeight: 600 }}>{data.confidence_avg}</div>
        </div>
        <div>
          <span className="stat-label">Duration</span>
          <div className="mono">{data.duration_seconds}s</div>
        </div>
        <div>
          <span className="stat-label">Speakers</span>
          <div className="mono">{data.speaker_count}</div>
        </div>
      </div>

      {data.key_issues && data.key_issues.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <span className="stat-label">Key Issues</span>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 4 }}>
            {data.key_issues.map((issue) => (
              <span key={issue} className="badge badge-source">{issue}</span>
            ))}
          </div>
        </div>
      )}

      <div className="stat-label">Full Transcript</div>
      <div className="transcript-text">{data.transcript_full}</div>
    </div>
  );
}

export default function Transcripts() {
  const [transcripts, setTranscripts] = useState([]);
  const [selected, setSelected] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.transcripts(50).then((data) => {
      setTranscripts(data);
      setLoading(false);
    });
  }, []);

  if (loading) return <div className="loading">Loading transcripts...</div>;

  return (
    <div>
      <h2 style={{ marginBottom: 24 }}>Transcript Viewer</h2>

      {selected && (
        <TranscriptDetail id={selected} onClose={() => setSelected(null)} />
      )}

      <div className="card">
        <table className="data-table">
          <thead>
            <tr>
              <th>Department</th>
              <th>Sentiment</th>
              <th>Confidence</th>
              <th>Duration</th>
              <th>Speakers</th>
              <th>Preview</th>
            </tr>
          </thead>
          <tbody>
            {transcripts.map((t) => (
              <tr
                key={t.id}
                onClick={() => setSelected(t.id)}
                style={{ cursor: "pointer" }}
              >
                <td>{t.department || "—"}</td>
                <td><SentimentBadge sentiment={t.sentiment} /></td>
                <td className="mono">{t.confidence_avg?.toFixed(3)}</td>
                <td className="mono">{t.duration_seconds?.toFixed(1)}s</td>
                <td className="mono">{t.speaker_count}</td>
                <td className="text-preview">{t.transcript_preview}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
