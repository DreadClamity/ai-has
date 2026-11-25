"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from "recharts";
import Header from "../../components/Header";
import { useRequireRole } from "../../lib/auth";
import { api } from "../../lib/api";

const SECTIONS = ["Overview", "Knowledge base", "Activity"];
const FRIENDLY_NAMES = {
  login_rate_limited: "Repeated login attempts",
  refused_low_confidence: "Insufficient source evidence",
  escalate_to_agent: "Human handoff",
  pii_redacted: "Personal information removed",
  injection_blocked: "Unsafe instruction blocked",
  out_of_scope: "Outside helpdesk scope",
  success: "Completed",
};

function readable(value) {
  if (FRIENDLY_NAMES[value]) return FRIENDLY_NAMES[value];
  return String(value || "Unknown").replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
}

function format(value, suffix = "") {
  return value == null ? "No data" : `${Number(value).toLocaleString()}${suffix}`;
}

function seconds(ms) {
  return format(ms == null ? null : Math.round(ms / 100) / 10, " s");
}

function Kpi({ label, value, detail }) {
  return (
    <div className="card kpi">
      <span className="muted">{label}</span>
      <strong>{value}</strong>
      {detail && <span className="muted small">{detail}</span>}
    </div>
  );
}

function ChartCard({ title, children }) {
  return (
    <section className="card chart-card">
      <h3>{title}</h3>
      <div className="chart-area">
        <ResponsiveContainer minWidth={0}>{children}</ResponsiveContainer>
      </div>
    </section>
  );
}

function DataTable({ headings, rows, empty = "No activity in this period." }) {
  return (
    <div className="table-wrap">
      <table className="table">
        <thead><tr>{headings.map((heading) => <th scope="col" key={heading}>{heading}</th>)}</tr></thead>
        <tbody>
          {rows.map(({ key, cells }) => <tr key={key}>{cells.map((cell, index) => <td key={headings[index]}>{cell}</td>)}</tr>)}
          {rows.length === 0 && <tr><td colSpan={headings.length} className="muted">{empty}</td></tr>}
        </tbody>
      </table>
    </div>
  );
}

function Overview({ data }) {
  const summary = data.summary;
  const daily = data.daily.map((day) => ({
    ...day,
    label: day.day.slice(5),
    avg_seconds: day.avg_latency_ms == null ? null : day.avg_latency_ms / 1000,
    p95_seconds: day.p95_latency_ms == null ? null : day.p95_latency_ms / 1000,
  }));
  const feedbackCount = summary.feedback_up + summary.feedback_down;
  const satisfaction = feedbackCount ? Math.round(100 * summary.feedback_up / feedbackCount) : null;
  const axis = { fill: "var(--muted)", fontSize: 12 };
  const tooltip = { backgroundColor: "var(--card)", color: "var(--text)", borderColor: "var(--border)", borderRadius: 8 };

  return (
    <>
      <div className="kpis">
        <Kpi label="Conversations" value={format(summary.total_conversations)} detail="All conversations in this period" />
        <Kpi label="Resolved by AI" value={format(summary.resolved_by_ai)} detail={summary.deflection_rate_pct == null ? "No conversations in this period" : `${format(summary.deflection_rate_pct, "%")} of conversations`} />
        <Kpi label="No outcome yet" value={format(summary.no_outcome)} detail="Conversations without a resolution or handoff" />
      </div>
      <div className="grid2">
        <section className="card">
          <div className="row-between"><h2>Conversation outcomes</h2><Link className="btn" href="/agent">View ticket queue</Link></div>
          <dl className="stat-list">
            <div><dt>Resolved by AI</dt><dd>{format(summary.resolved_by_ai)}</dd></div>
            <div><dt>Handed to the service desk</dt><dd>{format(summary.escalated)}</dd></div>
            <div><dt>No outcome yet</dt><dd>{format(summary.no_outcome)}</dd></div>
            <div><dt>Open tickets now</dt><dd>{format(summary.open_backlog)}</dd></div>
            <div><dt>Tickets resolved in this period</dt><dd>{format(summary.tickets_resolved)}</dd></div>
          </dl>
        </section>
        <section className="card">
          <h2>Service performance</h2>
          <dl className="stat-list">
            <div><dt>Average AI response time</dt><dd>{seconds(summary.avg_latency_ms)}</dd></div>
            <div><dt>95% of AI responses took at most</dt><dd>{seconds(summary.p95_latency_ms)}</dd></div>
            <div><dt>Average ticket resolution time</dt><dd>{format(summary.mttr_minutes, " min")}</dd></div>
            <div><dt>Positive feedback</dt><dd>{format(satisfaction, "%")}</dd></div>
          </dl>
        </section>
      </div>
      <div className="grid2">
        <ChartCard title="Conversations per day">
          <BarChart data={daily} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid stroke="var(--border)" vertical={false} />
            <XAxis dataKey="label" tick={axis} minTickGap={22} />
            <YAxis width={36} allowDecimals={false} tick={axis} />
            <Tooltip contentStyle={tooltip} itemStyle={{ color: "var(--text)" }} />
            <Legend />
            <Bar dataKey="resolved_by_ai" stackId="outcomes" fill="var(--chart-green)" name="Resolved by AI" />
            <Bar dataKey="escalated" stackId="outcomes" fill="var(--chart-blue)" name="Handed to service desk" />
            <Bar dataKey="no_outcome" stackId="outcomes" fill="var(--chart-neutral)" name="No outcome yet" />
          </BarChart>
        </ChartCard>
        <ChartCard title="AI resolution rate (%)">
          <LineChart data={daily}>
            <CartesianGrid stroke="var(--border)" vertical={false} />
            <XAxis dataKey="label" tick={axis} minTickGap={22} />
            <YAxis width={42} domain={[0, 100]} tick={axis} />
            <Tooltip contentStyle={tooltip} itemStyle={{ color: "var(--text)" }} />
            <Line dataKey="deflection_rate_pct" stroke="var(--chart-blue)" name="AI resolution rate (%)" />
          </LineChart>
        </ChartCard>
        <ChartCard title="AI response time (seconds)">
          <LineChart data={daily}>
            <CartesianGrid stroke="var(--border)" vertical={false} />
            <XAxis dataKey="label" tick={axis} minTickGap={22} />
            <YAxis width={42} tick={axis} />
            <Tooltip contentStyle={tooltip} itemStyle={{ color: "var(--text)" }} />
            <Legend />
            <Line dataKey="avg_seconds" stroke="var(--chart-blue)" name="Average" />
            <Line dataKey="p95_seconds" stroke="var(--chart-amber)" name="95th percentile" />
          </LineChart>
        </ChartCard>
        <ChartCard title="Average ticket resolution time (minutes)">
          <BarChart data={daily}>
            <CartesianGrid stroke="var(--border)" vertical={false} />
            <XAxis dataKey="label" tick={axis} minTickGap={22} />
            <YAxis width={42} tick={axis} />
            <Tooltip contentStyle={tooltip} itemStyle={{ color: "var(--text)" }} />
            <Bar dataKey="mttr_minutes" fill="var(--chart-blue)" name="Resolution time (min)" />
          </BarChart>
        </ChartCard>
      </div>
    </>
  );
}

function Activity({ data }) {
  return (
    <div className="grid2">
      <section className="card">
        <h2>Protection events</h2>
        <DataTable headings={["Event", "Severity", "Count"]} rows={data.guardrails.map((event) => ({
          key: `${event.event_type}-${event.severity}`,
          cells: [readable(event.event_type), <span className={`badge ${event.severity}`}>{readable(event.severity)}</span>, event.count],
        }))} />
      </section>
      <section className="card">
        <h2>Automation results</h2>
        <DataTable headings={["Action", "Status", "Count", "Avg. time"]} rows={data.tools.map((tool) => ({
          key: `${tool.tool_name}-${tool.status}`,
          cells: [readable(tool.tool_name), readable(tool.status), tool.count, format(tool.avg_ms, " ms")],
        }))} />
      </section>
      <section className="card">
        <h2>Reply topics</h2>
        <DataTable headings={["Topic", "Replies"]} rows={data.intents.map((item) => ({
          key: item.intent,
          cells: [readable(item.intent), item.count],
        }))} />
      </section>
    </div>
  );
}

export default function AdminPage() {
  const user = useRequireRole(["admin"]);
  const [section, setSection] = useState("Overview");
  const [days, setDays] = useState(14);
  const [data, setData] = useState(null);
  const [docs, setDocs] = useState(null);
  const [reindexing, setReindexing] = useState(false);
  const [reindexMsg, setReindexMsg] = useState("");
  const [docsError, setDocsError] = useState("");
  const [metricsError, setMetricsError] = useState("");

  useEffect(() => {
    if (!user) return;
    let obsolete = false;
    api(`/metrics/dashboard?days=${days}`)
      .then((result) => { if (!obsolete) setData(result); })
      .catch((error) => { if (!obsolete) setMetricsError(error.message); });
    return () => { obsolete = true; };
  }, [user, days]);

  useEffect(() => {
    if (!user) return;
    let obsolete = false;
    api("/kb/documents")
      .then((result) => { if (!obsolete) setDocs(result); })
      .catch((error) => { if (!obsolete) setDocsError(error.message); });
    return () => { obsolete = true; };
  }, [user]);

  async function reindex() {
    setReindexing(true);
    setReindexMsg("");
    setDocsError("");
    try {
      const result = await api("/kb/reindex", { method: "POST" });
      setReindexMsg(`Index refreshed. ${result.added} added, ${result.updated} updated, ${result.skipped} unchanged, ${result.chunks_added} sections indexed.`);
      setDocs(await api("/kb/documents"));
    } catch (error) {
      setDocsError(error.message);
    } finally {
      setReindexing(false);
    }
  }

  if (!user) return <p className="loading" role="status">Loading your workspace…</p>;

  return (
    <>
      <Header user={user} />
      <main className="container">
        <div className="row-between page-heading">
          <div>
            <h1>Operations dashboard</h1>
            <p className="muted">Track support outcomes, manage documents, and review activity.</p>
          </div>
          {section !== "Knowledge base" && (
            <label className="period-select">
              Date range
              <select value={days} onChange={(event) => { setMetricsError(""); setData(null); setDays(Number(event.target.value)); }}>
                {[7, 14, 30].map((value) => <option key={value} value={value}>Last {value} days</option>)}
              </select>
            </label>
          )}
        </div>
        <nav className="section-nav" aria-label="Dashboard sections">
          {SECTIONS.map((name) => <button key={name} className="btn" aria-pressed={section === name} onClick={() => setSection(name)}>{name}</button>)}
        </nav>

        {section !== "Knowledge base" ? (
          <>
            {metricsError && <p className="error" role="alert">{metricsError}</p>}
            {!data && !metricsError && <p className="muted" role="status">Loading dashboard…</p>}
            {data && (section === "Overview" ? <Overview data={data} /> : <Activity data={data} />)}
          </>
        ) : (
          <section className="card">
            <div className="row-between">
              <div>
                <h2>Support documents</h2>
                {docs && <p className="muted">{docs.length} documents · {docs.reduce((total, doc) => total + doc.chunk_count, 0)} searchable sections</p>}
              </div>
              <button className="btn btn-primary" onClick={reindex} disabled={reindexing}>{reindexing ? "Refreshing…" : "Refresh search index"}</button>
            </div>
            {reindexMsg && <p className="banner ok" role="status">{reindexMsg}</p>}
            {docsError && <p className="error" role="alert">{docsError}</p>}
            {!docs && !docsError && <p className="muted" role="status">Loading documents…</p>}
            {docs && <DataTable headings={["Document", "Category", "Sections"]} empty="No documents have been indexed." rows={docs.map((doc) => ({
              key: doc.id,
              cells: [doc.title, doc.category, doc.chunk_count],
            }))} />}
          </section>
        )}
      </main>
    </>
  );
}
