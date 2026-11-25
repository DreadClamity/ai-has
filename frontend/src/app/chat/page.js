"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Header from "../../components/Header";
import { useRequireRole } from "../../lib/auth";
import { api, streamChat } from "../../lib/api";

const ROLE_LABEL = { user: "You", assistant: "AI assistant", agent: "IT agent" };
const STATUS_LABEL = { active: "Active", escalated: "With the service desk", resolved_by_ai: "Resolved", closed: "Closed" };
const TOPICS = [
  { title: "Account access", detail: "Passwords and MFA", prompt: "How do I reset my password?" },
  { title: "Connection issues", detail: "VPN and Wi-Fi", prompt: "How can I troubleshoot a dropped VPN connection?" },
  { title: "Apps and software", detail: "Installation and access", prompt: "How do I request access to software?" },
  { title: "Printers", detail: "Setup and troubleshooting", prompt: "How do I add a printer?" },
];

export default function ChatPage() {
  const user = useRequireRole(["employee", "agent", "admin"]);
  const [conversations, setConversations] = useState([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [conversationId, setConversationId] = useState(null);
  const [status, setStatus] = useState("active");
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [operation, setOperation] = useState(null);
  const [streaming, setStreaming] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const messagesRef = useRef(null);
  const inputRef = useRef(null);
  const streamRef = useRef(null);
  const operationRef = useRef(false);

  const loadConversations = useCallback(async () => {
    try {
      const rows = await api("/chat/conversations");
      setConversations(rows);
      return rows;
    } catch (e) {
      setError(e.message);
      return null;
    }
  }, []);

  useEffect(() => {
    if (user) loadConversations();
  }, [user, loadConversations]);

  useEffect(() => () => streamRef.current?.abort(), []);

  useEffect(() => {
    const pane = messagesRef.current;
    if (pane) pane.scrollTop = pane.scrollHeight;
  }, [messages]);

  useEffect(() => {
    if (!conversationId || status !== "escalated" || operation) return;
    let obsolete = false;
    let polling = false;

    const timer = setInterval(async () => {
      if (polling) return;
      polling = true;
      try {
        const [rows, convs] = await Promise.all([
          api(`/chat/conversations/${conversationId}/messages`),
          api("/chat/conversations"),
        ]);
        if (obsolete || operationRef.current) return;
        setMessages(rows);
        setConversations(convs);
        const current = convs.find((c) => c.id === conversationId);
        if (current) setStatus(current.status);
      } catch {
        // A later poll can recover from temporary connection failures.
      } finally {
        polling = false;
      }
    }, 4000);
    return () => {
      obsolete = true;
      clearInterval(timer);
    };
  }, [conversationId, status, operation]);

  async function run(label, action) {
    if (operationRef.current) return;
    operationRef.current = true;
    setOperation(label);
    setError("");
    setNotice("");
    try {
      await action();
    } catch (e) {
      setError(e.message);
    } finally {
      operationRef.current = false;
      setOperation(null);
    }
  }

  function resetChat() {
    if (operationRef.current) return;
    setConversationId(null);
    setStatus("active");
    setInput("");
    setMessages([]);
    setError("");
    setNotice("");
    setHistoryOpen(false);
    inputRef.current?.focus();
  }

  function openConversation(conversation) {
    run("Opening conversation…", async () => {
      const rows = await api(`/chat/conversations/${conversation.id}/messages`);
      setConversationId(conversation.id);
      setStatus(conversation.status);
      setMessages(rows);
      setHistoryOpen(false);
    });
  }

  function replaceStreamingMessage(transform) {
    setMessages((previous) => previous.map((message) => message.streaming ? transform(message) : message));
  }

  function send(event) {
    event.preventDefault();
    const text = input.trim();
    if (!text || closed) return;

    run("Sending message…", async () => {
      setInput("");
      if (status === "escalated" && conversationId) {
        try {
          await api(`/chat/conversations/${conversationId}/agent-message`, {
            method: "POST",
            body: { content: text },
          });
          setMessages(await api(`/chat/conversations/${conversationId}/messages`));
        } catch (error) {
          setInput((draft) => draft || text);
          throw error;
        }
        return;
      }

      const controller = new AbortController();
      streamRef.current = controller;
      setStreaming(true);
      setMessages((previous) => [
        ...previous,
        { role: "user", content: text },
        { role: "assistant", content: "", streaming: true },
      ]);

      try {
        await streamChat(
          { message: text, conversation_id: conversationId },
          {
            signal: controller.signal,
            onMeta: (meta) => setConversationId(meta.conversation_id),
            onToken: (token) => replaceStreamingMessage((message) => ({ ...message, content: message.content + token })),
            onDone: (reply) => {
              setConversationId(reply.conversation_id);
              setStatus(reply.conversation_status);
              replaceStreamingMessage(() => ({
                id: reply.message_id,
                role: "assistant",
                content: reply.answer,
                citations: reply.citations,
                pending: reply.pending_action,
              }));
            },
          }
        );
      } catch (error) {
        setMessages((previous) => previous.filter((message) => !message.streaming));
        if (!controller.signal.aborted) throw error;
        setNotice("Stopped waiting. The reply may still appear in your conversations.");
      } finally {
        streamRef.current = null;
        setStreaming(false);
        loadConversations();
      }
    });
  }

  function decide(toolCallId, approve) {
    run("Updating action…", async () => {
      const result = await api(`/chat/tool-calls/${toolCallId}/${approve ? "confirm" : "deny"}`, {
        method: "POST",
      });
      setStatus(result.conversation_status);
      setMessages(await api(`/chat/conversations/${conversationId}/messages`));
      loadConversations();
    });
  }

  function escalate() {
    run("Contacting the service desk…", async () => {
      const result = await api(`/chat/conversations/${conversationId}/escalate`, {
        method: "POST",
        body: { reason: "User requested a human agent" },
      });
      setStatus(result.conversation_status);
      setMessages(await api(`/chat/conversations/${conversationId}/messages`));
      loadConversations();
    });
  }

  function resolve() {
    run("Closing conversation…", async () => {
      await api(`/chat/conversations/${conversationId}/resolve`, { method: "POST" });
      setStatus("resolved_by_ai");
      loadConversations();
    });
  }

  function rate(id, rating) {
    run("Saving feedback…", async () => {
      await api("/chat/feedback", { method: "POST", body: { message_id: id, rating } });
      setMessages((previous) => previous.map((message) => message.id === id ? { ...message, rating } : message));
    });
  }

  if (!user) return <p className="loading" role="status">Loading your workspace…</p>;

  const closed = status === "resolved_by_ai" || status === "closed";
  const title = conversations.find((c) => c.id === conversationId)?.title;
  const busy = Boolean(operation);

  return (
    <>
      <Header user={user} />
      <main className="container">
        <div className="page-heading row-between">
          <h1>Get IT help</h1>
          <button className="btn" onClick={resetChat} disabled={busy}>+ New chat</button>
        </div>
        <div className="chat-layout">
          <aside className="card sidebar" data-expanded={historyOpen}>
            <div className="row-between history-heading">
              <h2>Conversations</h2>
              <button className="btn history-toggle" aria-expanded={historyOpen} aria-controls="chat-history" onClick={() => setHistoryOpen(!historyOpen)}>
                {historyOpen ? "Hide" : "Show"}
              </button>
            </div>
            <div id="chat-history" className="conv-list">
              {conversations.length === 0 && <p className="muted small">Your chats will appear here.</p>}
              {conversations.map((conversation) => (
                <button
                  type="button"
                  key={conversation.id}
                  className="conv-item"
                  aria-current={conversation.id === conversationId ? "true" : undefined}
                  disabled={busy}
                  onClick={() => openConversation(conversation)}
                >
                  <strong>{conversation.title || "Untitled conversation"}</strong>
                  <span className="small muted">{new Date(conversation.started_at).toLocaleDateString()}</span>
                  <span className={`badge ${conversation.status}`}>{STATUS_LABEL[conversation.status]}</span>
                </button>
              ))}
              <button className="btn refresh-history" onClick={loadConversations} disabled={busy}>Refresh history</button>
            </div>
          </aside>

          <section className="card chat-main" aria-label="Chat">
            {conversationId && (
              <div className="panel-heading row-between">
                <h2>{title || "Conversation"}</h2>
                <span className={`badge ${status}`}>{STATUS_LABEL[status]}</span>
              </div>
            )}
            {status === "escalated" && <p className="banner">The service desk has this conversation. Replies appear here automatically.</p>}
            {closed && <p className="banner ok">This conversation is closed.</p>}

            <div className="messages" ref={messagesRef}>
              {messages.length === 0 && (
                <div className="chat-welcome">
                  <h2>Hi {user.full_name.split(" ")[0]}, how can we help?</h2>
                  <p className="muted">Describe the issue or pick a common topic to start.</p>
                  <div className="topics">
                    {TOPICS.map((topic) => (
                      <button className="topic" key={topic.title} disabled={busy} onClick={() => { setInput(topic.prompt); inputRef.current?.focus(); }}>
                        <strong>{topic.title}</strong>
                        <span className="small muted">{topic.detail}</span>
                      </button>
                    ))}
                  </div>
                </div>
              )}
              {messages.map((message, index) => (
                <article key={message.id || index} className={`msg ${message.role}`}>
                  <div className="msg-role">{ROLE_LABEL[message.role] || message.role}</div>
                  <div className="message-content">{message.streaming && !message.content ? "Searching the knowledge base…" : message.content}</div>
                  {message.citations?.length > 0 && (
                    <div className="cites" aria-label="Sources">
                      {message.citations.map((source) => (
                        <details key={source.chunk_id} className="cite">
                          <summary>
                            {source.index != null && `[${source.index}] `}
                            {source.title || source.source_filename || "Knowledge base source"}
                            {source.section && ` · ${source.section}`}
                          </summary>
                          <p>{source.snippet}</p>
                        </details>
                      ))}
                    </div>
                  )}
                  {message.pending && status === "active" && (
                    <div className="actions">
                      <button className="btn btn-primary" disabled={busy} onClick={() => decide(message.pending.tool_call_id, true)}>Confirm action</button>
                      <button className="btn" disabled={busy} onClick={() => decide(message.pending.tool_call_id, false)}>Cancel action</button>
                    </div>
                  )}
                  {message.role === "assistant" && message.id && (
                    <div className="actions feedback">
                      {[[1, "Helpful"], [-1, "Not helpful"]].map(([rating, label]) => (
                        <button key={rating} className="btn btn-small" disabled={busy} aria-pressed={message.rating === rating} onClick={() => rate(message.id, rating)}>{label}</button>
                      ))}
                    </div>
                  )}
                </article>
              ))}
            </div>

            <div className="chat-controls">
              {error && <p className="error" role="alert">{error}</p>}
              {notice && <p className="muted" role="status">{notice}</p>}
              {operation && <p className="muted small" role="status">{streaming ? "Waiting for the assistant’s reply…" : operation}</p>}
              {conversationId && status === "active" && (
                <div className="actions">
                  <button className="btn" onClick={resolve} disabled={busy}>This solved my issue</button>
                  <button className="btn" onClick={escalate} disabled={busy}>Talk to a person</button>
                </div>
              )}
              <form className="chat-form" onSubmit={send}>
                <label className="sr-only" htmlFor="chat-message">Your message</label>
                <textarea
                  id="chat-message"
                  ref={inputRef}
                  rows={2}
                  maxLength={2000}
                  value={input}
                  disabled={closed}
                  placeholder={closed ? "This conversation is closed" : "Tell us what you need help with…"}
                  onChange={(event) => setInput(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                      event.preventDefault();
                      event.currentTarget.form.requestSubmit();
                    }
                  }}
                />
                <div className="row-between">
                  <small className="muted">Keep passwords and verification codes private.</small>
                  {streaming
                    ? <button type="button" className="btn" onClick={() => streamRef.current?.abort()}>Stop waiting</button>
                    : <button type="submit" className="btn btn-primary" disabled={busy || closed || !input.trim()}>Send message</button>}
                </div>
              </form>
            </div>
          </section>
        </div>
      </main>
    </>
  );
}
