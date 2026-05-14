-- DocDB schema v3
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
-- Entities (property-graph instances)
-- Each row is a typed node. ``type_slug`` points at entity_types.slug;
-- ``fields`` is a JSON object validated by docdb.typing.field_spec against
-- that type's fields_schema before write.
-- ============================================================
CREATE TABLE IF NOT EXISTS entities (
    id              TEXT PRIMARY KEY,
    type_slug       TEXT NOT NULL,
    canonical_name  TEXT NOT NULL,
    aliases         TEXT NOT NULL DEFAULT '[]',
    description     TEXT,
    fields          TEXT NOT NULL DEFAULT '{}',
    created_ts      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_ts      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(type_slug, canonical_name),
    CHECK (json_valid(aliases) AND json_valid(fields)),
    FOREIGN KEY(type_slug) REFERENCES entity_types(slug) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_entities_type      ON entities(type_slug);
CREATE INDEX IF NOT EXISTS idx_entities_canonical ON entities(canonical_name);

-- Property-graph edges. Source and target reference entities. ``fields`` is
-- validated by docdb.typing.field_spec against relation_types.fields_schema.
CREATE TABLE IF NOT EXISTS relations (
    id                 TEXT PRIMARY KEY,
    type_slug          TEXT NOT NULL,
    source_entity_id   TEXT NOT NULL,
    target_entity_id   TEXT NOT NULL,
    fields             TEXT NOT NULL DEFAULT '{}',
    created_ts         TEXT NOT NULL DEFAULT (datetime('now')),
    updated_ts         TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(type_slug, source_entity_id, target_entity_id),
    CHECK (json_valid(fields)),
    FOREIGN KEY(type_slug)        REFERENCES relation_types(slug) ON DELETE RESTRICT,
    FOREIGN KEY(source_entity_id) REFERENCES entities(id)         ON DELETE CASCADE,
    FOREIGN KEY(target_entity_id) REFERENCES entities(id)         ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_relations_source ON relations(source_entity_id);
CREATE INDEX IF NOT EXISTS idx_relations_target ON relations(target_entity_id);
CREATE INDEX IF NOT EXISTS idx_relations_type   ON relations(type_slug);

-- ============================================================
-- Entity search shadow (Python-maintained) + trigram FTS
-- ``searchable_text`` concatenates canonical_name, aliases, description and
-- string-typed field values. The store layer rewrites this row on every
-- entity upsert; tests and direct CRUD callers must go through the store.
-- ============================================================
CREATE TABLE IF NOT EXISTS entities_search (
    entity_id        TEXT PRIMARY KEY,
    searchable_text  TEXT NOT NULL,
    FOREIGN KEY(entity_id) REFERENCES entities(id) ON DELETE CASCADE
);

CREATE VIRTUAL TABLE IF NOT EXISTS entities_fts USING fts5(
    searchable_text,
    tokenize = 'trigram',
    content = 'entities_search',
    content_rowid = 'rowid'
);

CREATE TRIGGER IF NOT EXISTS entities_search_ai AFTER INSERT ON entities_search BEGIN
    INSERT INTO entities_fts(rowid, searchable_text) VALUES (new.rowid, new.searchable_text);
END;

CREATE TRIGGER IF NOT EXISTS entities_search_ad AFTER DELETE ON entities_search BEGIN
    INSERT INTO entities_fts(entities_fts, rowid, searchable_text)
    VALUES ('delete', old.rowid, old.searchable_text);
END;

CREATE TRIGGER IF NOT EXISTS entities_search_au AFTER UPDATE ON entities_search BEGIN
    INSERT INTO entities_fts(entities_fts, rowid, searchable_text)
    VALUES ('delete', old.rowid, old.searchable_text);
    INSERT INTO entities_fts(rowid, searchable_text)
    VALUES (new.rowid, new.searchable_text);
END;

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
    contexts       TEXT NOT NULL DEFAULT '[]',   -- JSON array of short snippets
    PRIMARY KEY(document_id, entity_id),
    CHECK (json_valid(contexts)),
    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE,
    FOREIGN KEY(entity_id)   REFERENCES entities(id)  ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_de_entity ON document_entities(entity_id);

-- Provenance for property-graph relations. Lets the UI answer "which doc
-- produced this edge?" and ingestion clean up stale relations on re-ingest.
CREATE TABLE IF NOT EXISTS document_relation_mentions (
    document_id  TEXT NOT NULL,
    relation_id  TEXT NOT NULL,
    contexts     TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY(document_id, relation_id),
    CHECK (json_valid(contexts)),
    FOREIGN KEY(document_id) REFERENCES documents(id)  ON DELETE CASCADE,
    FOREIGN KEY(relation_id) REFERENCES relations(id)  ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_drm_relation ON document_relation_mentions(relation_id);

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

INSERT OR IGNORE INTO schema_version(version) VALUES (3);
