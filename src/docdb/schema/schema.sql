-- DocDB schema v2
-- All tables intended for the agentic search layer are defined here.
-- Virtual tables (FTS5, sqlite-vec) require the respective extensions
-- to be loaded on the connection before this DDL is applied.
--
-- Embedding dimension is fixed at 1024 (bge-m3). Changing it requires a
-- schema migration plus full re-ingestion.

CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- Documents
-- ============================================================
CREATE TABLE IF NOT EXISTS documents (
    id            TEXT PRIMARY KEY,
    source_path   TEXT,
    source_uri    TEXT,
    source_type   TEXT NOT NULL,       -- 'md' | 'pdf' | 'docx' | 'pptx' | 'xlsx' | 'html' | 'txt'
    title         TEXT,
    doc_type      TEXT,                -- 'memo' | 'meeting' | 'journal' | 'reference' | 'spec' | 'other'
    author        TEXT,
    created_at    TEXT,                -- ISO 8601 (document content date, not row date)
    summary       TEXT,
    raw_text      TEXT,
    content_hash  TEXT NOT NULL UNIQUE,
    language      TEXT,                -- 'ja' | 'en' | 'mixed' | 'other'
    metadata      TEXT,                -- JSON blob (use json_extract to query)
    created_ts    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_ts    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_documents_doc_type   ON documents(doc_type);
CREATE INDEX IF NOT EXISTS idx_documents_created_at ON documents(created_at);
CREATE INDEX IF NOT EXISTS idx_documents_source_path ON documents(source_path);

-- ============================================================
-- Type registry (Stage 1 of property-graph redesign)
-- ============================================================
-- entity_types and relation_types are user-editable at runtime.
-- fields_schema is a JSON FieldSpec[]; see docdb.typing.field_spec.
-- These coexist with the legacy `entities`/`todos` tables until Stage 2.
CREATE TABLE IF NOT EXISTS entity_types (
    slug             TEXT PRIMARY KEY,
    label            TEXT NOT NULL,
    description      TEXT,
    icon             TEXT,
    color            TEXT,
    fields_schema    TEXT NOT NULL DEFAULT '[]',
    extraction_hint  TEXT,
    is_builtin       INTEGER NOT NULL DEFAULT 0,
    created_ts       TEXT NOT NULL DEFAULT (datetime('now')),
    updated_ts       TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK (json_valid(fields_schema))
);

CREATE TABLE IF NOT EXISTS relation_types (
    slug              TEXT PRIMARY KEY,
    label             TEXT NOT NULL,
    description       TEXT,
    inverse_label     TEXT,
    source_type_slug  TEXT,                     -- NULL = any
    target_type_slug  TEXT,
    fields_schema     TEXT NOT NULL DEFAULT '[]',
    extraction_hint   TEXT,
    is_builtin        INTEGER NOT NULL DEFAULT 0,
    created_ts        TEXT NOT NULL DEFAULT (datetime('now')),
    updated_ts        TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK (json_valid(fields_schema)),
    FOREIGN KEY(source_type_slug) REFERENCES entity_types(slug) ON DELETE SET NULL,
    FOREIGN KEY(target_type_slug) REFERENCES entity_types(slug) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_relation_types_src ON relation_types(source_type_slug);
CREATE INDEX IF NOT EXISTS idx_relation_types_dst ON relation_types(target_type_slug);

-- ============================================================
-- Entities (LEGACY — to be dropped in Stage 2)
-- Current shape uses a fixed entity_type enum. Property-graph entities
-- replace this table in Stage 2 once the type registry is in place.
-- ============================================================
CREATE TABLE IF NOT EXISTS entities (
    id              TEXT PRIMARY KEY,
    canonical_name  TEXT NOT NULL,
    entity_type     TEXT NOT NULL,     -- 'person' | 'org' | 'product' | 'tech' | 'place' | 'other'
    aliases         TEXT,              -- JSON array of strings
    description     TEXT,
    metadata        TEXT,
    created_ts      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(canonical_name, entity_type)
);

CREATE INDEX IF NOT EXISTS idx_entities_canonical ON entities(canonical_name);
CREATE INDEX IF NOT EXISTS idx_entities_type      ON entities(entity_type);

-- ============================================================
-- Tags
-- ============================================================
CREATE TABLE IF NOT EXISTS tags (
    id              TEXT PRIMARY KEY,
    canonical_name  TEXT NOT NULL UNIQUE,
    aliases         TEXT,
    category        TEXT
);

CREATE INDEX IF NOT EXISTS idx_tags_category ON tags(category);

-- ============================================================
-- Junction tables
-- ============================================================
CREATE TABLE IF NOT EXISTS document_entities (
    document_id    TEXT NOT NULL,
    entity_id      TEXT NOT NULL,
    mention_count  INTEGER NOT NULL DEFAULT 1,
    contexts       TEXT,               -- JSON array of short snippets
    PRIMARY KEY(document_id, entity_id),
    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE,
    FOREIGN KEY(entity_id)   REFERENCES entities(id)  ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_de_entity ON document_entities(entity_id);

CREATE TABLE IF NOT EXISTS document_tags (
    document_id TEXT NOT NULL,
    tag_id      TEXT NOT NULL,
    confidence  REAL NOT NULL DEFAULT 1.0,
    source      TEXT NOT NULL DEFAULT 'llm',  -- 'llm' | 'manual' | 'rule'
    PRIMARY KEY(document_id, tag_id),
    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE,
    FOREIGN KEY(tag_id)      REFERENCES tags(id)      ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_dt_tag ON document_tags(tag_id);

CREATE TABLE IF NOT EXISTS document_relations (
    src_document_id  TEXT NOT NULL,
    dst_document_id  TEXT NOT NULL,
    relation_type    TEXT NOT NULL,    -- 'similar' | 'references' | 'revision_of' | 'attachment_of'
    confidence       REAL NOT NULL DEFAULT 1.0,
    evidence         TEXT,
    PRIMARY KEY(src_document_id, dst_document_id, relation_type),
    FOREIGN KEY(src_document_id) REFERENCES documents(id) ON DELETE CASCADE,
    FOREIGN KEY(dst_document_id) REFERENCES documents(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_dr_dst ON document_relations(dst_document_id);

-- ============================================================
-- TODOs (extracted from documents; first-class object)
-- ============================================================
CREATE TABLE IF NOT EXISTS todos (
    id                  TEXT PRIMARY KEY,
    content             TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'pending',  -- pending | in_progress | completed | cancelled
    priority            TEXT NOT NULL DEFAULT 'medium',   -- high | medium | low
    due_date            TEXT,
    source_document_id  TEXT,
    source_section      TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(source_document_id) REFERENCES documents(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_todos_status ON todos(status);
CREATE INDEX IF NOT EXISTS idx_todos_due    ON todos(due_date) WHERE status != 'completed';

-- ============================================================
-- Extraction provenance
-- ============================================================
CREATE TABLE IF NOT EXISTS extraction_runs (
    id             TEXT PRIMARY KEY,
    document_id    TEXT,
    model          TEXT NOT NULL,
    schema_name    TEXT NOT NULL,
    raw_output     TEXT,
    error          TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
);

-- ============================================================
-- FTS5 (trigram tokenizer for Japanese-friendly substring match)
-- ============================================================
CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
    title,
    summary,
    raw_text,
    tokenize = 'trigram',
    content = 'documents',
    content_rowid = 'rowid'
);

CREATE TRIGGER IF NOT EXISTS documents_ai AFTER INSERT ON documents BEGIN
    INSERT INTO documents_fts(rowid, title, summary, raw_text)
    VALUES (new.rowid, new.title, new.summary, new.raw_text);
END;

CREATE TRIGGER IF NOT EXISTS documents_ad AFTER DELETE ON documents BEGIN
    INSERT INTO documents_fts(documents_fts, rowid, title, summary, raw_text)
    VALUES ('delete', old.rowid, old.title, old.summary, old.raw_text);
END;

CREATE TRIGGER IF NOT EXISTS documents_au AFTER UPDATE ON documents BEGIN
    INSERT INTO documents_fts(documents_fts, rowid, title, summary, raw_text)
    VALUES ('delete', old.rowid, old.title, old.summary, old.raw_text);
    INSERT INTO documents_fts(rowid, title, summary, raw_text)
    VALUES (new.rowid, new.title, new.summary, new.raw_text);
END;

-- ============================================================
-- sqlite-vec virtual tables (bge-m3, 1024 dimensions)
-- ============================================================
CREATE VIRTUAL TABLE IF NOT EXISTS documents_vec USING vec0(
    document_id TEXT PRIMARY KEY,
    embedding   float[1024]
);

CREATE VIRTUAL TABLE IF NOT EXISTS entities_vec USING vec0(
    entity_id TEXT PRIMARY KEY,
    embedding float[1024]
);

CREATE VIRTUAL TABLE IF NOT EXISTS tags_vec USING vec0(
    tag_id    TEXT PRIMARY KEY,
    embedding float[1024]
);

INSERT OR IGNORE INTO schema_version(version) VALUES (2);
