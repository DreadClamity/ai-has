"use client";

import { useEffect, useRef, useState } from "react";
import Header from "../../components/Header";
import { useRequireRole } from "../../lib/auth";
import { api } from "../../lib/api";

const FILTERS = [
  ["", "All statuses"],
  ["escalated", "Escalated"],
  ["open", "Open"],
  ["in_progress", "In progress"],
  ["resolved", "Resolved"],
  ["closed", "Closed"],
];

const labelFor = (status) => FILTERS.find(([value]) => value === status)?.[1] || status;

export default function AgentPage() {
  const user = useRequireRole(["agent", "admin"]);
  const [tickets, setTickets] = useState(null);
  const [filter, setFilter] = useState("");
  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [reply, setReply] = useState("");
  const [note, setNote] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [version, setVersion] = useState(0);
  const [queueError, setQueueError] = useState("");
  const [detailError, setDetailError] = useState("");
  const [actionError, setActionError] = useState("");
  const [notice, setNotice] = useState("");
  const detailRef = useRef(null);
  const actionRef = useRef(false);

  useEffect(() => {
    if (!user || busy) return;
    let obsolete = false;
    let loading = false;

    async function load() {
      if (loading) return;
      loading = true;
      try {
        const rows = await api(`/agent/tickets${filter ? `?status=${filter}` : ""}`);
        if (!obsolete) {
          setTickets(rows);
          setQueueError("");
        }
      } catch (error) {
        if (!obsolete) setQueueError(error.message);
      } finally {
        loading = false;
      }
    }

    load();
    const timer = setInterval(load, 8000);
    return () => { obsolete = true; clearInterval(timer); };
  }, [user, filter, busy, version]);

  useEffect(() => {
    if (!selectedId || busy) return;
    let obsolete = false;
    let loading = false;

    async function load() {
      if (loading) return;
      loading = true;
      try {
        const result = await api(`/agent/tickets/${selectedId}`);
        if (!obsolete) {
          setDetail(result);
          setDetailError("");
        }
      } catch (error) {
        if (!obsolete) setDetailError(error.message);
      } finally {
        loading = false;
      }
    }

    load();
    const timer = setInterval(load, 4000);
    return () => { obsolete = true; clearInterval(timer); };
  }, [selectedId, busy, version]);

  function selectTicket(id) {
    if (actionRef.current || id === selectedId) return;
    setSelectedId(id);
    setDetail(null);
    setReply("");
    setNote("");
    setConfirming(false);
    setActionError("");
    setDetailError("");
    setNotice("");
    if (window.matchMedia("(max-width: 780px)").matches) detailRef.current?.focus();
  }

  async function act(path, body, onSuccess, successMessage) {
    if (actionRef.current) return;
    actionRef.current = true;
    setBusy(true);
    setActionError("");
    setNotice("");
    try {
      await api(`/agent/tickets/${selectedId}/${path}`, { method: "POST", body });
      onSuccess?.();
      setNotice(successMessage);
      try {
        setDetail(await api(`/agent/tickets/${selectedId}`));
      } catch (error) {
        setDetailError(error.message);
      }
    } catch (error) {
      setActionError(error.message);
    } finally {
      actionRef.current = false;
      setBusy(false);
      setVersion((previous) => previous + 1);
    }
  }

  function sendReply(event) {
    event.preventDefault();
    if (reply.trim()) {
      act("reply", { content: reply.trim() }, () => setReply(""), "Reply sent.");
    }
  }

  function resolveTicket(event) {
    event.preventDefault();
    act("resolve", { note: note.trim() }, () => {
      setNote("");
      setConfirming(false);
    }, "Ticket resolved.");
  }

  if (!user) return <p className="loading" role="status">Loading your workspace…</p>;

  const ticket = detail?.ticket;
  const canAct = ticket && (ticket.assignee_id === user.id || user.role === "admin");
  const live = detail?.conversation_status === "escalated";
  const finished = ticket && ["resolved", "closed"].includes(ticket.status);

  return (
    <>
      <Header user={user} />
      <main className="container">
        <div className="page-heading">
          <h1>Ticket queue</h1>
          <p className="muted">Review requests, pick up tickets, and reply to employees.</p>
        </div>
        <div className="agent-layout">
          <section aria-label="Tickets">
            <div className="row-between queue-filter">
              <label htmlFor="status-filter">Filter by status</label>
              <select id="status-filter" value={filter} disabled={busy} onChange={(event) => { setTickets(null); setFilter(event.target.value); }}>
                {FILTERS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </div>
            {queueError && <p className="error" role="alert">{queueError}</p>}
            {!tickets && !queueError && <p className="muted" role="status">Loading tickets…</p>}
            {tickets?.length === 0 && <p className="card muted">{filter ? "No tickets match this status." : "No tickets yet. New requests will appear here."}</p>}
            <div className="ticket-list">
              {tickets?.map((item) => (
                <button key={item.id} className="card ticket-button" type="button" aria-current={item.id === selectedId ? "true" : undefined} disabled={busy} onClick={() => selectTicket(item.id)}>
                  <span className="row-between">
                    <span className="muted small">{item.ticket_key}</span>
                    <span className={`badge ${item.priority}`}>{item.priority} priority</span>
                  </span>
                  <strong>{item.title}</strong>
                  <span className="muted small">{item.requester_name} · {item.assignee_name || "Unassigned"}</span>
                  <span className={`badge ${item.status}`}>{labelFor(item.status)}</span>
                </button>
              ))}
            </div>
          </section>

          <section className="card ticket-detail" aria-label="Ticket details" ref={detailRef} tabIndex={-1} aria-busy={busy}>
            {detailError && <p className="error" role="alert">{detailError}</p>}
            {!selectedId && <p className="muted">Select a ticket to read its conversation and see available actions.</p>}
            {selectedId && !ticket && !detailError && <p className="muted" role="status">Loading ticket…</p>}
            {ticket && (
              <>
                <div className="row-between">
                  <p className="muted small">{ticket.ticket_key}{ticket.external_ref && ` · ${ticket.external_ref}`}</p>
                  <span className={`badge ${ticket.status}`}>{labelFor(ticket.status)}</span>
                </div>
                <h2>{ticket.title}</h2>
                <p className="muted">{ticket.requester_name} · {ticket.requester_email}</p>
                <p className="muted small">{ticket.category || "General"} · {ticket.assignee_name || "Unassigned"}</p>
                {ticket.description && ticket.description !== ticket.title && <p className="ticket-description">{ticket.description}</p>}
                <h3>Conversation</h3>
                <div className="transcript">
                  {detail.messages.length === 0 && <p className="muted">No conversation attached.</p>}
                  {detail.messages.map((message) => (
                    <article className={`msg ${message.role}`} key={message.id}>
                      <div className="msg-role">{message.role === "user" ? ticket.requester_name : message.role === "agent" ? "IT agent" : "AI assistant"}</div>
                      <div className="message-content">{message.content}</div>
                    </article>
                  ))}
                </div>
                {notice && <p className="banner ok" role="status">{notice}</p>}
                {actionError && <p className="error" role="alert">{actionError}</p>}
                {busy && <p className="muted small" role="status">Updating ticket…</p>}
                {!ticket.assignee_id && !finished && (
                  <button className="btn btn-primary" disabled={busy} onClick={() => act("claim", undefined, null, "Ticket assigned to you.")}>Assign to me</button>
                )}
                {canAct && live && (
                  <form className="ticket-form" onSubmit={sendReply}>
                    <label htmlFor="agent-reply">Reply to the employee</label>
                    <textarea id="agent-reply" rows={3} maxLength={2000} value={reply} onChange={(event) => setReply(event.target.value)} disabled={busy} />
                    <button className="btn btn-primary" type="submit" disabled={busy || !reply.trim()}>Send reply</button>
                  </form>
                )}
                {canAct && !finished && ticket.assignee_id && (
                  confirming ? (
                    <form className="ticket-form" onSubmit={resolveTicket}>
                      <label htmlFor="resolution">Resolution summary (optional)</label>
                      <input id="resolution" value={note} maxLength={500} onChange={(event) => setNote(event.target.value)} disabled={busy} autoFocus />
                      <div className="actions">
                        <button className="btn btn-primary" type="submit" disabled={busy}>Confirm resolution</button>
                        <button className="btn" type="button" disabled={busy} onClick={() => setConfirming(false)}>Keep working</button>
                      </div>
                    </form>
                  ) : <button className="btn resolve-ticket" disabled={busy} onClick={() => setConfirming(true)}>Resolve ticket</button>
                )}
              </>
            )}
          </section>
        </div>
      </main>
    </>
  );
}
