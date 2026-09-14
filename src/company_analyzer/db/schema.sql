-- Company Analyzer Phase 1 schema (Postgres / Supabase).
-- Event != Evidence, and Duplicate-detection != Threading, are enforced structurally:
-- events/evidence_spans are separate tables; event_relationships is the single mechanism
-- that both duplicate-detection (same_event) and threading (related_distinct) apply from.
--
-- Table order matters here: unlike SQLite, Postgres validates FK targets at
-- CREATE TABLE time, so every REFERENCES target must already exist.

CREATE TABLE IF NOT EXISTS companies (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    dart_corp_code TEXT,
    aliases_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    source_type TEXT NOT NULL CHECK (source_type IN ('dart','ir','press_release','tech_blog','ceo_letter','news')),
    is_official BOOLEAN NOT NULL,
    title TEXT NOT NULL,
    url TEXT,
    published_date TEXT,
    external_id TEXT NOT NULL,
    file_path TEXT,
    raw_text TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    fetched_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(company_id, source_type, external_id)
);

CREATE TABLE IF NOT EXISTS document_snapshots (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id),
    version INTEGER NOT NULL,
    raw_text TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    UNIQUE(document_id, version)
);

CREATE TABLE IF NOT EXISTS ingestion_log (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source TEXT NOT NULL CHECK (source IN ('dart','news','manual')),
    company_id INTEGER NOT NULL REFERENCES companies(id),
    status TEXT NOT NULL CHECK (status IN ('success','failed')),
    detail TEXT,
    error_message TEXT,
    occurred_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id),
    chunk_index INTEGER NOT NULL,
    heading TEXT,
    text TEXT NOT NULL,
    start_offset INTEGER NOT NULL,
    end_offset INTEGER NOT NULL,
    UNIQUE(document_id, chunk_index)
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    chunk_id INTEGER NOT NULL REFERENCES chunks(id),
    event_type TEXT NOT NULL,
    subject TEXT,
    action TEXT,
    event_date TEXT,
    date_precision TEXT NOT NULL DEFAULT 'unknown' CHECK (date_precision IN ('day','month','quarter','year','unknown')),
    lifecycle_status TEXT NOT NULL DEFAULT 'unknown' CHECK (lifecycle_status IN ('planned','completed','cancelled','unknown')),
    domain TEXT,
    entity TEXT,
    raw_quote TEXT NOT NULL,
    extraction_model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    llm_raw_response_json TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence_spans (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id INTEGER NOT NULL UNIQUE REFERENCES events(id),
    chunk_id INTEGER NOT NULL REFERENCES chunks(id),
    raw_quote TEXT NOT NULL,
    matched_text TEXT,
    start_offset INTEGER,
    end_offset INTEGER,
    match_score REAL NOT NULL,
    match_method TEXT NOT NULL CHECK (match_method IN ('exact','fuzzy_rapidfuzz','rejected')),
    is_valid BOOLEAN NOT NULL,
    review_status TEXT NOT NULL DEFAULT 'auto_valid' CHECK (review_status IN ('auto_valid','pending','approved','rejected')),
    validated_at TEXT NOT NULL,
    embedding_json TEXT
);

-- evidence_spans predates embedding_json (added for JD matching) - the
-- CREATE TABLE above only fires on a brand new database, so an already-live
-- table needs this to actually gain the column. ADD COLUMN IF NOT EXISTS
-- makes this statement safe to re-run alongside the rest of this script.
ALTER TABLE evidence_spans ADD COLUMN IF NOT EXISTS embedding_json TEXT;

CREATE TABLE IF NOT EXISTS event_relationships (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_a_id INTEGER NOT NULL REFERENCES events(id),
    event_b_id INTEGER NOT NULL REFERENCES events(id),
    relationship_type TEXT NOT NULL CHECK (relationship_type IN ('same_event','related_distinct','unrelated','insufficient_info')),
    rationale TEXT,
    confidence REAL NOT NULL,
    decided_by TEXT NOT NULL CHECK (decided_by IN ('llm','human')),
    review_status TEXT NOT NULL DEFAULT 'pending' CHECK (review_status IN ('auto_applied','pending','approved','rejected')),
    created_at TEXT NOT NULL,
    UNIQUE(event_a_id, event_b_id)
);

CREATE TABLE IF NOT EXISTS canonical_events (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    event_type TEXT NOT NULL,
    subject TEXT,
    action TEXT,
    canonical_date TEXT,
    date_precision TEXT NOT NULL DEFAULT 'unknown' CHECK (date_precision IN ('day','month','quarter','year','unknown')),
    lifecycle_status TEXT NOT NULL DEFAULT 'unknown' CHECK (lifecycle_status IN ('planned','completed','cancelled','unknown')),
    domain TEXT,
    entity TEXT,
    title TEXT NOT NULL,
    summary TEXT,
    stage TEXT CHECK (stage IN ('announce','build','pilot','launch','scale') OR stage IS NULL),
    review_status TEXT NOT NULL DEFAULT 'pending' CHECK (review_status IN ('auto_applied','pending','approved','rejected')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS event_cluster_members (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    canonical_event_id INTEGER NOT NULL REFERENCES canonical_events(id),
    event_id INTEGER NOT NULL UNIQUE REFERENCES events(id),
    is_seed BOOLEAN NOT NULL DEFAULT FALSE,
    relationship_id INTEGER REFERENCES event_relationships(id)
);

CREATE TABLE IF NOT EXISTS threads (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    title TEXT NOT NULL,
    domain TEXT,
    entity TEXT,
    review_status TEXT NOT NULL DEFAULT 'pending' CHECK (review_status IN ('auto_applied','pending','approved','rejected')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Mirrors event_relationships but between canonical_events, since threading
-- operates one level up from duplicate-detection (never on raw events).
CREATE TABLE IF NOT EXISTS canonical_event_relationships (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    canonical_event_a_id INTEGER NOT NULL REFERENCES canonical_events(id),
    canonical_event_b_id INTEGER NOT NULL REFERENCES canonical_events(id),
    relationship_type TEXT NOT NULL CHECK (relationship_type IN ('same_event','related_distinct','unrelated','insufficient_info')),
    rationale TEXT,
    confidence REAL NOT NULL,
    decided_by TEXT NOT NULL CHECK (decided_by IN ('llm','human')),
    review_status TEXT NOT NULL DEFAULT 'pending' CHECK (review_status IN ('auto_applied','pending','approved','rejected')),
    created_at TEXT NOT NULL,
    UNIQUE(canonical_event_a_id, canonical_event_b_id)
);

CREATE TABLE IF NOT EXISTS thread_events (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    thread_id INTEGER NOT NULL REFERENCES threads(id),
    canonical_event_id INTEGER NOT NULL REFERENCES canonical_events(id),
    sequence_index INTEGER NOT NULL,
    stage TEXT CHECK (stage IN ('announce','build','pilot','launch','scale') OR stage IS NULL),
    relationship_id INTEGER REFERENCES canonical_event_relationships(id),
    UNIQUE(thread_id, canonical_event_id),
    UNIQUE(thread_id, sequence_index)
);

-- JD matching: one row per pasted job description.
CREATE TABLE IF NOT EXISTS user_jds (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    raw_text TEXT NOT NULL,
    role TEXT,
    role_subtype TEXT,
    domain TEXT,
    entities_json TEXT NOT NULL DEFAULT '[]',
    tasks_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    table_name TEXT NOT NULL,
    record_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    actor TEXT NOT NULL,
    before_json TEXT,
    after_json TEXT,
    occurred_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_documents_company_source ON documents(company_id, source_type);
CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_events_chunk ON events(chunk_id);
CREATE INDEX IF NOT EXISTS idx_evidence_spans_review ON evidence_spans(review_status);
CREATE INDEX IF NOT EXISTS idx_event_relationships_review ON event_relationships(review_status);
CREATE INDEX IF NOT EXISTS idx_canonical_event_relationships_review ON canonical_event_relationships(review_status);
CREATE INDEX IF NOT EXISTS idx_canonical_events_company_date ON canonical_events(company_id, canonical_date);
CREATE INDEX IF NOT EXISTS idx_thread_events_thread ON thread_events(thread_id, sequence_index);
CREATE INDEX IF NOT EXISTS idx_audit_log_record ON audit_log(table_name, record_id);
