import { NavLink, Outlet } from "react-router-dom";

const NAV = [
  { to: "/", label: "Dashboard", icon: "📊" },
  { to: "/transcripts", label: "Transcripts", icon: "🎙" },
  { to: "/explorer", label: "Explorer", icon: "🔍" },
  { to: "/search", label: "Search", icon: "🧠" },
];

export default function Layout() {
  return (
    <div className="app-layout">
      <nav className="sidebar">
        <div className="sidebar-logo">
          feedback<span>-intel</span>
        </div>
        {NAV.map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            end={n.to === "/"}
            className={({ isActive }) =>
              `nav-link ${isActive ? "active" : ""}`
            }
          >
            <span>{n.icon}</span>
            {n.label}
          </NavLink>
        ))}
        <div style={{ flex: 1 }} />
        <div
          style={{
            fontSize: 11,
            color: "var(--text-dim)",
            padding: "0 8px",
            lineHeight: 1.5,
          }}
        >
          GCP Portfolio Project
          <br />
          <span className="mono" style={{ fontSize: 10 }}>
            feedback-intel-demo
          </span>
        </div>
      </nav>
      <main className="main-content">
        <Outlet />
      </main>
    </div>
  );
}
