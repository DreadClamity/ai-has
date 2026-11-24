"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Header from "../../components/Header";
import { useRequireRole } from "../../lib/auth";
import { api, streamChat } from "../../lib/api";

const toView = (rows) => rows.map((r) => ({ id: r.id, role: r.role, content: r.content }));

const ROLE_LABEL = { user: "You", assistant: "AI Assistant", agent: "IT Agent" };

export default function ChatPage() {
  const user = useRequireRole(["employee", "agent", "admin"]);
  const [conversations, setConversations] = useState([]);
  const [conversationId, setConversationId] = useState(null);
  const [status, setStatus] = useState("active");
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const bottomRef = useRef(null);

  const loadConversations = useCallback(async () => {
    try {
      setConversations(await api("/chat/conversations"));
    } catch (e) {
      setError(e.message);
    }
  }, []);

  useEffect(() => {
    if (user) loadConversations();
  }, [user, loadConversations]);

  useEffect(() => {
    if (bottomRef.current) bottomRef.current.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    if (!conversationId || status !== "escalated") return undefined;
    const timer = setInterval(async () => {
      try {
        const rows = await api(`/chat/conversations/${conversationId}/messages`);
        setMessages(toView(rows));
        const convs = await api("/chat/conversations");
        setConversations(convs);
        const current = convs.find((c) => c.id === conversationId);
        if (current) setStatus(current.status);
      } catch (e) {
        /* ignore polling errors */
      }
    }, 4000);
    return () => clearInterval(timer);
  }, [conversationId, status]);

  const resetChat = () => {
    setConversationId(null);
    setStatus("active");
    setMessages([]);
    setError("");
  };

  const openConversation = async (conv) => {
    try {
      setError("");
      const rows = await api(`/chat/conversations/${conv.id}/messages`);
      setConversationId(conv.id);
      setStatus(conv.status);
      setMessages(toView(rows));
    } catch (e) {
      setError(e.message);
    }
  };

  const updateLast = (fn) =>
    setMessages((prev) => {
      const copy = [...prev];
      copy[copy.length - 1] = fn(copy[copy.length - 1]);
      return copy;
    });

  const send = async () => {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setError("");
    setBusy(true);
    setMessages((prev) => [...prev, { role: "user", content: text }]);

    try {
      if (status === "escalated" && conversationId) {
        await api(`/chat/conversations/${conversationId}/agent-message`, {
          method: "POST",
          body: { content: text },
        });
      } else {
        setMessages((prev) => [...prev, { role: "assistant", content: "", streaming: true }]);
        await streamChat(
          { message: text, conversation_id: conversationId },
          {
            onMeta: (m) => setConversationId(m.conversation_id),
            onToken: (t) => updateLast((last) => ({ ...last, content: last.content + t })),
            onDone: (d) => {
              setConversationId(d.conversation_id);
              setStatus(d.conversation_status);
              updateLast(() => ({
                id: d.message_id,
                role: "assistant",
                content: d.answer,
                citations: d.citations,
                pending: d.pending_action,
                suggestEscalation: d.suggest_escalation,
              }));
            },
          }
        );
      }
      loadConversations();
    } catch (e) {
      setError(e.message);
      setMessages((prev) => {
        const last = prev[prev.length - 1];
        return last && last.streaming && !last.content ? prev.slice(0, -1) : prev;
      });
    } finally {
      setBusy(false);
    }
  };

  const decide = async (index, toolCallId, approve) => {
    try {
      const res = await api(`/chat/tool-calls/${toolCallId}/${approve ? "confirm" : "deny"}`, {
        method: "POST",
      });
      setMessages((prev) => [
        ...prev.map((m, i) => (i === index ? { ...m, pending: null } : m)),
        { role: "assistant", content: res.message },
      ]);
      setStatus(res.conversation_status);
      loadConversations();
    } catch (e) {
      setError(e.message);
    }
  };

  const escalate = async () => {
    try {
      const res = await api(`/chat/conversations/${conversationId}/escalate`, {
        method: "POST",
        body: { reason: "User requested a human agent" },
      });
      setMessages((prev) => [...prev, { role: "assistant", content: res.message }]);
      setStatus(res.conversation_status);
      loadConversations();
    } catch (e) {
      setError(e.message);
    }
  };

  const resolve = async () => {
    try {
      await api(`/chat/conversations/${conversationId}/resolve`, { method: "POST" });
      setStatus("resolved_by_ai");
      loadConversations();
    } catch (e) {
      setError(e.message);
    }
  };

  const rate = async (id, rating) => {
    try {
      await api("/chat/feedback", { method: "POST", body: { message_id: id, rating } });
      setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, rated: rating } : m)));
    } catch (e) {
      setError(e.message);
    }
  };

  if (!user) return <p style={{ padding: 24 }}>Loading...</p>;

  const closed = status === "resolved_by_ai" || status === "closed";

  return (
    <>
      <Header user={user} />
      <div className="container">
        <div className="chat-layout">
          <aside className="card sidebar">
            <button className="btn btn-primary" onClick={resetChat}>
              + New chat
            </button>
            <div className="conv-list">
              {conversations.map((c) => (
                <div
                  key={c.id}
                  className={`conv-item ${c.id === conversationId ? "active" : ""}`}
                  onClick={() => openConversation(c)}
                >
                  <div>{new Date(c.started_at).toLocaleString()}</div>
                  <span className={`badge ${c.status}`}>{c.status.replace(/_/g, " ")}</span>
                </div>
              ))}
            </div>
          </aside>

          <section className="card chat-main">
            {status === "escalated" && (
              <div className="banner">
                This conversation is with a human IT agent. Replies appear here automatically.
              </div>
            )}
            {closed && <div className="banner ok">This conversation is closed.</div>}

            <div className="messages">
              {messages.length === 0 && (
                <p className="muted">
                  Ask about passwords, VPN, Wi-Fi, printers, MFA or software access. I can also
                  reset your password or open a ticket for you.
                </p>
              )}
              {messages.map((m, i) => (
                <div key={i} className={`msg ${m.role}`}>
                  <div className="msg-role">{ROLE_LABEL[m.role] || m.role}</div>
                  {m.streaming && !m.content ? "Thinking..." : m.content}

                  {m.citations && m.citations.length > 0 && (
                    <div className="cites">
                      {m.citations.map((c) => (
                        <details key={c.chunk_id} className="cite">
                          <summary>
                            [{c.index}] {c.title} &rsaquo; {c.section}
                          </summary>
                          <div>{c.snippet}</div>
                        </details>
                      ))}
                    </div>
                  )}

                  {m.pending && (
                    <div className="actions">
                      <button
                        className="btn btn-primary"
                        onClick={() => decide(i, m.pending.tool_call_id, true)}
                      >
                        Confirm
                      </button>
                      <button className="btn" onClick={() => decide(i, m.pending.tool_call_id, false)}>
                        Cancel
                      </button>
                    </div>
                  )}

                  {m.suggestEscalation && status === "active" && conversationId && (
                    <div className="actions">
                      <button className="btn" onClick={escalate}>
                        Talk to a human
                      </button>
                    </div>
                  )}

                  {m.role === "assistant" && m.id && (
                    <div className="feedback">
                      <button
                        className={`btn-icon ${m.rated === 1 ? "on" : ""}`}
                        onClick={() => rate(m.id, 1)}
                        title="Helpful"
                      >
                        &#128077;
                      </button>
                      <button
                        className={`btn-icon ${m.rated === -1 ? "on" : ""}`}
                        onClick={() => rate(m.id, -1)}
                        title="Not helpful"
                      >
                        &#128078;
                      </button>
                    </div>
                  )}
                </div>
              ))}
              <div ref={bottomRef} />
            </div>

            {error && <div className="error">{error}</div>}

            <div className="toolbar">
              {conversationId && status === "active" && (
                <>
                  <button className="btn" onClick={resolve}>
                    Mark as resolved
                  </button>
                  <button className="btn btn-danger" onClick={escalate}>
                    Talk to a human
                  </button>
                </>
              )}
            </div>

            <div className="composer">
              <textarea
                rows={2}
                value={input}
                disabled={closed}
                placeholder={closed ? "This conversation is closed" : "Type your message..."}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    send();
                  }
                }}
              />
              <button className="btn btn-primary" onClick={send} disabled={busy || closed}>
                Send
              </button>
            </div>
          </section>
        </div>
      </div>
    </>
  );
}