"use client";

import { useCallback, useEffect, useState } from "react";
import Header from "../../components/Header";
import { useRequireRole } from "../../lib/auth";
import { api } from "../../lib/api";

const FILTERS = ["", "escalated", "open", "in_progress", "resolved"];

export default function AgentPage() {
  const user = useRequireRole(["agent", "admin"]);
  const [tickets, setTickets] = useState([]);
  const [filter, setFilter] = useState("");
  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [reply, setReply] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");

  const loadTickets = useCallback(async () => {
    try {
      setTickets(await api(`/agent/tickets${filter ? `?status=${filter}` : ""}`));
    } catch (e) {
      setError(e.message);
    }
  }, [filter]);

  const loadDetail = useCallback(async (id) => {
    try {
      setDetail(await api(`/agent/tickets/${id}`));
    } catch (e) {
      setError(e.message);
    }
  }, []);

  useEffect(() => {
    if (!user) return undefined;
    loadTickets();
    const timer = setInterval(loadTickets, 8000);
    return () => clearInterval(timer);
  }, [user, loadTickets]);

  useEffect(() => {
    if (!selectedId) return undefined;
    loadDetail(selectedId);
    const timer = setInterval(() => loadDetail(selectedId), 4000);
    return () => clearInterval(timer);
  }, [selectedId, loadDetail]);

  const act = async (path, body) => {
    try {
      setError("");
      await api(`/agent/tickets/${selectedId}/${path}`, { method: "POST", body });
      await loadDetail(selectedId);
      await loadTickets();
    } catch (e) {
      setError(e.message);
    }
  };

  const sendReply = async () => {
    if (!reply.trim()) return;
    await act("reply", { content: reply.trim() });
    setReply("");
  };

  const resolveTicket = async () => {
    await act("resolve", { note });
    setNote("");
  };

  if (!user) return <p style={{ padding: 24 }}>Loading...</p>;

  const ticket = detail ? detail.ticket : null;
  const canAct = ticket && (ticket.assignee_id === user.id || user.role === "admin");
  const live = detail && detail.conversation_status === "escalated";
  const finished = ticket && (ticket.status === "resolved" || ticket.status === "closed");

  return (
    <>
      <Header user={user} />
      <div className="container">
        {error && <div className="error">{error}</div>}
        <div className="agent-layout">
          <section className="card">
            <div className="row-between">
              <h3>Ticket queue</h3>
              <select value={filter} onChange={(e) => setFilter(e.target.value)}>
                {FILTERS.map((f) => (
                  <option key={f} value={f}>
                    {f ? f.replace("_", " ") : "all statuses"}
                  </option>
                ))}
              </select>
            </div>
            <table className="table">
              <thead>
                <tr>
                  <th>Ticket</th>
                  <th>Requester</th>
                  <th>Priority</th>
                  <th>Status</th>
                  <th>Assignee</th>
                </tr>
              </thead>
              <tbody>
                {tickets.map((t) => (
                  <tr
                    key={t.id}
                    className={t.id === selectedId ? "row-selected" : "row-click"}
                    onClick={() => setSelectedId(t.id)}
                  >
                    <td>
                      <strong>{t.ticket_key}</strong>
                      <div className="muted small">{t.title}</div>
                    </td>
                    <td>{t.requester_name}</td>
                    <td>
                      <span className={`badge ${t.priority}`}>{t.priority}</span>
                    </td>
                    <td>
                      <span className={`badge ${t.status}`}>{t.status.replace("_", " ")}</span>
                    </td>
                    <td>{t.assignee_name || "-"}</td>
                  </tr>
                ))}
                {tickets.length === 0 && (
                  <tr>
                    <td colSpan={5} className="muted">
                      No tickets
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </section>

          <section className="card">
            {!ticket && <p className="muted">Select a ticket to see the conversation.</p>}
            {ticket && (
              <>
                <div className="row-between">
                  <h3>
                    {ticket.ticket_key} {ticket.external_ref ? `(${ticket.external_ref})` : ""}
                  </h3>
                  <span className={`badge ${ticket.status}`}>{ticket.status.replace("_", " ")}</span>
                </div>
                <p>
                  <strong>{ticket.title}</strong>
                  <br />
                  <span className="muted small">
                    {ticket.requester_name} ({ticket.requester_email}) &middot; {ticket.category || "general"}
                  </span>
                </p>

                <div className="transcript">
                  {detail.messages.length === 0 && <p className="muted">No conversation attached.</p>}
                  {detail.messages.map((m) => (
                    <div key={m.id} className={`msg small-msg ${m.role}`}>
                      <div className="msg-role">
                        {m.role === "user" ? ticket.requester_name : m.role === "agent" ? "IT Agent" : "AI Assistant"}
                      </div>
                      {m.content}
                    </div>
                  ))}
                </div>

                <div className="actions">
                  {ticket.assignee_id === null && !finished && (
                    <button className="btn btn-primary" onClick={() => act("claim")}>
                      Claim ticket
                    </button>
                  )}
                </div>

                {canAct && live && (
                  <div className="composer">
                    <textarea
                      rows={2}
                      value={reply}
                      placeholder="Reply to the employee..."
                      onChange={(e) => setReply(e.target.value)}
                    />
                    <button className="btn btn-primary" onClick={sendReply}>
                      Send
                    </button>
                  </div>
                )}

                {canAct && !finished && ticket.assignee_id && (
                  <div className="composer">
                    <input
                      value={note}
                      placeholder="Resolution note (optional)"
                      onChange={(e) => setNote(e.target.value)}
                    />
                    <button className="btn btn-danger" onClick={resolveTicket}>
                      Resolve ticket
                    </button>
                  </div>
                )}
              </>
            )}
          </section>
        </div>
      </div>
    </>
  );
}