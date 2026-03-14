import { useState, useEffect } from "react";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend,
} from "recharts";
import { api } from "../api";

const COLORS = {
  positive: "#00e5a0",
  negative: "#ff6b6b",
  neutral: "#6b7394",
};

function StatCard({ value, label, color }) {
  return (
    <div className="stat-card">
      <div className="stat-value" style={{ color: color || "var(--text)" }}>
        {value ?? "—"}
      </div>
      <div className="stat-label">{label}</div>
    </div>
  );
}

export default function Dashboard() {
  const [stats, setStats] = useState(null);
  const [chirp, setChirp] = useState(null);
  const [depts, setDepts] = useState([]);
  const [error, setError] = useState(null);

  useEffect(() => {
    Promise.all([api.stats(), api.chirpStats(), api.departments()])
      .then(([s, c, d]) => {
        setStats(s);
        setChirp(c);
        setDepts(d);
      })
      .catch((e) => setError(e.message));
  }, []);

  if (error) return <div className="error">{error}</div>;
  if (!stats) return <div className="loading">Loading dashboard...</div>;

  const sentimentData = [
    { name: "Positive", value: stats.positive, color: COLORS.positive },
    { name: "Negative", value: stats.negative, color: COLORS.negative },
    { name: "Neutral", value: stats.neutral, color: COLORS.neutral },
  ];

  return (
    <div>
      <h2 style={{ marginBottom: 24 }}>Pipeline Dashboard</h2>

      {/* Overview stats */}
      <div className="stat-grid">
        <StatCard value={stats.total?.toLocaleString()} label="Total Records" color="var(--accent)" />
        <StatCard value={stats.from_calls} label="From Calls" color="var(--info)" />
        <StatCard value={stats.from_text} label="From Text" color="var(--accent2)" />
        <StatCard value={stats.avg_confidence} label="Avg Confidence" color="var(--warn)" />
        <StatCard value={stats.low_confidence} label="Low Confidence (<0.7)" color="var(--negative)" />
      </div>

      {/* Chirp pipeline health */}
      {chirp && (
        <>
          <h3 style={{ marginBottom: 16, marginTop: 8 }}>Chirp STT Pipeline</h3>
          <div className="stat-grid">
            <StatCard value={chirp.total_calls} label="Total Calls" color="var(--info)" />
            <StatCard value={chirp.successful} label="Transcribed" color="var(--positive)" />
            <StatCard value={chirp.failed} label="Failed" color="var(--negative)" />
            <StatCard value={chirp.avg_confidence} label="Avg Chirp Confidence" color="var(--warn)" />
            <StatCard
              value={chirp.avg_duration_sec ? `${chirp.avg_duration_sec}s` : "—"}
              label="Avg Duration"
            />
            <StatCard
              value={chirp.avg_processing_ms ? `${chirp.avg_processing_ms}ms` : "—"}
              label="Avg Processing"
            />
          </div>
        </>
      )}

      {/* Charts */}
      <div className="charts-grid">
        {/* Sentiment distribution */}
        <div className="card">
          <div className="card-title">Sentiment Distribution</div>
          <ResponsiveContainer width="100%" height={250}>
            <PieChart>
              <Pie
                data={sentimentData}
                cx="50%"
                cy="50%"
                innerRadius={60}
                outerRadius={90}
                dataKey="value"
                label={({ name, percent }) =>
                  `${name} ${(percent * 100).toFixed(0)}%`
                }
              >
                {sentimentData.map((entry) => (
                  <Cell key={entry.name} fill={entry.color} />
                ))}
              </Pie>
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
        </div>

        {/* Department breakdown */}
        <div className="card">
          <div className="card-title">Records by Department</div>
          <ResponsiveContainer width="100%" height={250}>
            <BarChart data={depts} layout="vertical">
              <XAxis type="number" stroke="var(--text-dim)" fontSize={11} />
              <YAxis
                type="category"
                dataKey="department"
                width={100}
                stroke="var(--text-dim)"
                fontSize={11}
              />
              <Tooltip
                contentStyle={{
                  background: "var(--bg-elevated)",
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                }}
              />
              <Bar dataKey="count" fill="var(--accent2)" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
