"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import Header from "../../components/Header";
import { useRequireRole } from "../../lib/auth";
import { api } from "../../lib/api";

const fmt = (value, suffix = "") => (value === null || value === undefined ? "-" : `${value}${suffix}`);

function Kpi({ label, value, hint }) {
  return (
    <div className="card kpi" title={hint}>
      <div className="muted small">{label}</div>
      <div className="value">{value}</div>
    </div>
  );
}

function ChartCard({ title, children }) {
  return (
    <div className="card">
      <h4>{title}</h4>
      <div style={{ width: "100%", height: 220 }}>
        <ResponsiveContainer>{children}</ResponsiveContainer>
      </div>
    </div>
  );
}

export default function AdminPage() {
  const user = useRequireRole(["admin"]);
  const [days, setDays] = useState(14);
  const [data, setData] = useState(null);
  const [docs, setDocs] = useState([]);
  const [reindexMsg, setReindexMsg] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      setData(await api(`/metrics/dashboard?days=${days}`));
      setDocs(await api("/kb/documents"));
    } catch (e) {
      setError(e.message);
    }
  }, [days]);

  useEffect(() => {
    if (user) load();
  }, [user, load]);

  const reindex = async () => {
    setReindexMsg("Re-indexing...");
    try {
      const r = await api("/kb/reindex", { method: "POST" });
      setReindexMsg(
        `Done: ${r.added} added, ${r.updated} updated, ${r.skipped} unchanged, ${r.chunks_added} chunks embedded`
      );
      load();
    } catch (e) {
      setReindexMsg(e.message);
    }
  };

  if (!user) return <p style={{ padding: 24 }}>Loading...</p>;

  const s = data ? data.summary : null;
  const daily = data ? data.daily.map((d) => ({ ...d, label: d.day.slice(5) })) : [];
  const satisfaction =
    s && s.feedback_up + s.feedback_down > 0
      ? Math.round((100 * s.feedback_up) / (s.feedback_up + s.feedback_down))
      : null;

  return (
    <>
      <Header user={user} />
      <div className="container">
        <div className="row-between">
          <h2>Operations dashboard</h2>
          <select value={days} onChange={(e) => setDays(Number(e.target.value))}>
            <option value={7}>Last 7 days</option>
            <option value={14}>Last 14 days</option>
            <option value={30}>Last 30 days</option>
          </select>
        </div>
        {error && <div className="error">{error}</div>}

        {s && (
          <>
            <div className="kpis">
              <Kpi label="Conversations" value={fmt(s.total_conversations)} />
              <Kpi
                label="Ticket deflection"
                value={fmt(s.deflection_rate_pct, "%")}
                hint="Share of conversations the user marked as resolved by the assistant"
              />
              <Kpi label="Avg latency" value={fmt(s.avg_latency_ms, " ms")} />
              <Kpi label="P95 latency" value={fmt(s.p95_latency_ms, " ms")} />
              <Kpi label="MTTR" value={fmt(s.mttr_minutes, " min")} hint="Mean time to resolution of tickets" />
              <Kpi label="Open backlog" value={fmt(s.open_backlog)} />
              <Kpi label="Tickets resolved" value={fmt(s.tickets_resolved)} />
              <Kpi label="User satisfaction" value={fmt(satisfaction, "%")} hint="Thumbs up share" />
            </div>

            <div className="grid2">
              <ChartCard title="Conversations per day">
                <BarChart data={daily}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="label" />
                  <YAxis allowDecimals={false} />
                  <Tooltip />
                  <Legend />
                  <Bar dataKey="resolved_by_ai" stackId="a" fill="#12805c" name="Resolved by AI" />
                  <Bar dataKey="escalated" stackId="a" fill="#d92d20" name="Human handled" />
                </BarChart>
              </ChartCard>

              <ChartCard title="Deflection rate (%)">
                <LineChart data={daily}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="label" />
                  <YAxis domain={[0, 100]} />
                  <Tooltip />
                  <Line type="monotone" dataKey="deflection_rate_pct" stroke="#2f5bea" name="Deflection %" connectNulls />
                </LineChart>
              </ChartCard>

              <ChartCard title="Response latency (ms)">
                <LineChart data={daily}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="label" />
                  <YAxis />
                  <Tooltip />
                  <Legend />
                  <Line type="monotone" dataKey="avg_latency_ms" stroke="#2f5bea" name="Average" connectNulls />
                  <Line type="monotone" dataKey="p95_latency_ms" stroke="#b54708" name="P95" connectNulls />
                </LineChart>
              </ChartCard>

              <ChartCard title="MTTR (minutes)">
                <BarChart data={daily}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="label" />
                  <YAxis />
                  <Tooltip />
                  <Bar dataKey="mttr_minutes" fill="#7a5af8" name="MTTR (min)" />
                </BarChart>
              </ChartCard>
            </div>

            <div className="grid2">
              <div className="card">
                <h4>Guardrail events</h4>
                <table className="table">
                  <thead>
                    <tr>
                      <th>Event</th>
                      <th>Severity</th>
                      <th>Count</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.guardrails.map((g, i) => (
                      <tr key={i}>
                        <td>{g.event_type}</td>
                        <td>
                          <span className={`badge ${g.severity}`}>{g.severity}</span>
                        </td>
                        <td>{g.count}</td>
                      </tr>
                    ))}
                    {data.guardrails.length === 0 && (
                      <tr>
                        <td colSpan={3} className="muted">
                          None in this period
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>

              <div className="card">
                <h4>Automation (tool calls)</h4>
                <table className="table">
                  <thead>
                    <tr>
                      <th>Tool</th>
                      <th>Status</th>
                      <th>Count</th>
                      <th>Avg ms</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.tools.map((t, i) => (
                      <tr key={i}>
                        <td>{t.tool_name}</td>
                        <td>{t.status.replace("_", " ")}</td>
                        <td>{t.count}</td>
                        <td>{fmt(t.avg_ms)}</td>
                      </tr>
                    ))}
                    {data.tools.length === 0 && (
                      <tr>
                        <td colSpan={4} className="muted">
                          None in this period
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>

              <div className="card">
                <h4>Intent mix</h4>
                <table className="table">
                  <thead>
                    <tr>
                      <th>Intent</th>
                      <th>Replies</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.intents.map((i) => (
                      <tr key={i.intent}>
                        <td>{i.intent}</td>
                        <td>{i.count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="card">
                <div className="row-between">
                  <h4>Knowledge base</h4>
                  <button className="btn btn-primary" onClick={reindex}>
                    Re-index
                  </button>
                </div>
                {reindexMsg && <p className="muted small">{reindexMsg}</p>}
                <table className="table">
                  <thead>
                    <tr>
                      <th>Document</th>
                      <th>Category</th>
                      <th>Chunks</th>
                    </tr>
                  </thead>
                  <tbody>
                    {docs.map((d) => (
                      <tr key={d.id}>
                        <td>{d.title}</td>
                        <td>{d.category}</td>
                        <td>{d.chunk_count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </>
        )}
      </div>
    </>
  );
}