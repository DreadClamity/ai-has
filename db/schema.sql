CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ============ ENUM TYPES ============
CREATE TYPE user_role AS ENUM ('employee', 'agent', 'admin');
CREATE TYPE conversation_status AS ENUM ('active', 'resolved_by_ai', 'escalated', 'closed');
CREATE TYPE message_role AS ENUM ('user', 'assistant', 'system', 'agent');
CREATE TYPE ticket_status AS ENUM ('open', 'in_progress', 'escalated', 'resolved', 'closed');
CREATE TYPE ticket_priority AS ENUM ('low', 'medium', 'high', 'critical');
CREATE TYPE tool_status AS ENUM ('pending_confirmation', 'success', 'failed', 'denied');

-- ============ USERS (RBAC) ============
CREATE TABLE users (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email         VARCHAR(255) NOT NULL UNIQUE,
    full_name     VARCHAR(150) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role          user_role NOT NULL DEFAULT 'employee',
    department    VARCHAR(100),
    is_active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============ CONVERSATIONS & MESSAGES ============
CREATE TABLE conversations (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status            conversation_status NOT NULL DEFAULT 'active',
    assigned_agent_id UUID REFERENCES users(id),
    escalation_reason TEXT,
    started_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at       TIMESTAMPTZ
);

CREATE TABLE messages (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id   UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role              message_role NOT NULL,
    content           TEXT NOT NULL,              -- stored AFTER PII redaction
    intent            VARCHAR(60),
    pii_detected      BOOLEAN NOT NULL DEFAULT FALSE,
    latency_ms        INTEGER,
    prompt_tokens     INTEGER,
    completion_tokens INTEGER,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE message_feedback (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id UUID NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    rating     SMALLINT NOT NULL CHECK (rating IN (-1, 1)),
    comment    TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (message_id, user_id)
);

-- ============ KNOWLEDGE BASE ============
CREATE TABLE kb_documents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title           VARCHAR(255) NOT NULL,
    category        VARCHAR(80),
    source_filename VARCHAR(255) NOT NULL,
    content_hash    CHAR(64) NOT NULL UNIQUE,     -- SHA-256, prevents duplicate ingest
    chunk_count     INTEGER NOT NULL DEFAULT 0,
    uploaded_by     UUID REFERENCES users(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE message_citations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id      UUID NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    kb_document_id  UUID REFERENCES kb_documents(id) ON DELETE SET NULL,
    chunk_id        VARCHAR(120),
    relevance_score REAL,
    snippet         TEXT
);

-- ============ TICKETS ============
CREATE SEQUENCE ticket_number_seq START 1;

CREATE TABLE tickets (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_key      VARCHAR(20) NOT NULL UNIQUE
                    DEFAULT ('HD-' || LPAD(nextval('ticket_number_seq')::TEXT, 4, '0')),
    conversation_id UUID REFERENCES conversations(id) ON DELETE SET NULL,
    requester_id    UUID NOT NULL REFERENCES users(id),
    assignee_id     UUID REFERENCES users(id),
    category        VARCHAR(80),
    title           VARCHAR(255) NOT NULL,
    description     TEXT,
    priority        ticket_priority NOT NULL DEFAULT 'medium',
    status          ticket_status NOT NULL DEFAULT 'open',
    external_ref    VARCHAR(80),                  -- Jira/ServiceNow key
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at     TIMESTAMPTZ
);

CREATE TABLE ticket_events (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_id  UUID NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    actor_id   UUID REFERENCES users(id),
    event_type VARCHAR(60) NOT NULL,
    details    JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============ AUTOMATION AUDIT (FUNCTION CALLS) ============
CREATE TABLE tool_calls (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id       UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    message_id            UUID REFERENCES messages(id) ON DELETE SET NULL,
    tool_name             VARCHAR(80) NOT NULL,
    arguments             JSONB NOT NULL DEFAULT '{}',
    result                JSONB,
    status                tool_status NOT NULL DEFAULT 'pending_confirmation',
    requires_confirmation BOOLEAN NOT NULL DEFAULT TRUE,
    error                 TEXT,
    duration_ms           INTEGER,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============ GOVERNANCE ============
CREATE TABLE guardrail_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID REFERENCES conversations(id) ON DELETE CASCADE,
    message_id      UUID REFERENCES messages(id) ON DELETE SET NULL,
    event_type      VARCHAR(60) NOT NULL,         -- pii_redacted | injection_blocked | ungrounded_answer | unauthorized_tool
    severity        VARCHAR(20) NOT NULL DEFAULT 'low',
    details         JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============ EVALUATION ============
CREATE TABLE eval_runs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_name    VARCHAR(120) NOT NULL,
    run_type    VARCHAR(40) NOT NULL,             -- rag | pii | injection | load
    git_commit  VARCHAR(40),
    summary     JSONB NOT NULL DEFAULT '{}',
    started_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ
);

CREATE TABLE eval_results (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id        UUID NOT NULL REFERENCES eval_runs(id) ON DELETE CASCADE,
    test_case_id  VARCHAR(60) NOT NULL,
    question      TEXT NOT NULL,
    expected      TEXT,
    actual        TEXT,
    faithfulness  REAL,
    relevance     REAL,
    latency_ms    INTEGER,
    passed        BOOLEAN NOT NULL DEFAULT FALSE
);

-- ============ INDEXES ============
CREATE INDEX idx_messages_conv        ON messages(conversation_id, created_at);
CREATE INDEX idx_conversations_user   ON conversations(user_id, started_at DESC);
CREATE INDEX idx_conversations_status ON conversations(status);
CREATE INDEX idx_tickets_status       ON tickets(status, priority);
CREATE INDEX idx_tickets_requester    ON tickets(requester_id);
CREATE INDEX idx_toolcalls_conv       ON tool_calls(conversation_id);
CREATE INDEX idx_guardrail_type       ON guardrail_events(event_type, created_at);

-- ============ KPI VIEWS (feed the admin dashboard) ============
CREATE VIEW v_kpi_deflection_daily AS
SELECT
    started_at::DATE AS day,
    COUNT(*) AS total_conversations,
    COUNT(*) FILTER (WHERE status = 'resolved_by_ai') AS resolved_by_ai,
    COUNT(*) FILTER (WHERE status = 'escalated') AS escalated,
    ROUND(100.0 * COUNT(*) FILTER (WHERE status = 'resolved_by_ai')
          / NULLIF(COUNT(*), 0), 2) AS deflection_rate_pct
FROM conversations
GROUP BY started_at::DATE;

CREATE VIEW v_kpi_latency_daily AS
SELECT
    created_at::DATE AS day,
    COUNT(*) AS assistant_messages,
    ROUND(AVG(latency_ms)) AS avg_latency_ms,
    ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms)::NUMERIC) AS p95_latency_ms
FROM messages
WHERE role = 'assistant' AND latency_ms IS NOT NULL
GROUP BY created_at::DATE;

CREATE VIEW v_kpi_mttr_daily AS
SELECT
    resolved_at::DATE AS day,
    COUNT(*) AS tickets_resolved,
    ROUND(AVG(EXTRACT(EPOCH FROM (resolved_at - created_at)) / 60)::NUMERIC, 1) AS mttr_minutes
FROM tickets
WHERE resolved_at IS NOT NULL
GROUP BY resolved_at::DATE;