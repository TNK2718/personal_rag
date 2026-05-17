export type DocType = "memo" | "meeting" | "journal" | "reference" | "spec" | "other";

// ---------------------------------------------------------------------------
// Type registry (Stage 1 of property-graph redesign)
// ---------------------------------------------------------------------------
export type FieldSpecType =
  | "string"
  | "text"
  | "int"
  | "float"
  | "bool"
  | "date"
  | "datetime"
  | "enum"
  | "url"
  | "ref";

export interface FieldSpec {
  name: string;
  label: string;
  type: FieldSpecType;
  required?: boolean;
  default?: unknown;
  ui_widget?: string;
  options?: string[];        // enum only
  ref_type_slug?: string;    // ref only
}

interface TypeDefBase {
  slug: string;
  label: string;
  description: string | null;
  fields_schema: FieldSpec[];
  extraction_hint: string | null;
  is_builtin: boolean;
  created_ts: string | null;
  updated_ts: string | null;
}

export interface EntityTypeDef extends TypeDefBase {
  icon: string | null;
  color: string | null;
}

export interface RelationTypeDef extends TypeDefBase {
  inverse_label: string | null;
  source_type_slug: string | null;
  target_type_slug: string | null;
}

// ---------------------------------------------------------------------------
// Stats
// ---------------------------------------------------------------------------
export interface EntityTypeCount {
  type_slug: string;
  label: string | null;
  count: number;
}

export interface Stats {
  documents_total: number;
  doc_types: Array<{ doc_type: string; count: number }>;
  entities_total: number;
  entities_by_type: EntityTypeCount[];
  relations_total: number;
  tags_total: number;
}

export interface Citation {
  document_id: string;
  title: string | null;
  snippet: string | null;
  score: number | null;
  source_path: string | null;
  doc_type: DocType | null;
}

export interface DocumentListItem {
  document_id: string;
  title: string | null;
  source_path: string | null;
  doc_type: DocType | null;
  created_at: string | null;
  snippet: string | null;
  score: number | null;
}

export interface DocumentListResponse {
  items: DocumentListItem[];
  total: number;
  limit: number;
  offset: number;
}

// ---------------------------------------------------------------------------
// Property-graph instances (Stage 2)
// ---------------------------------------------------------------------------
export interface EntityRef {
  id: string;
  type_slug: string;
  canonical_name: string;
  aliases: string[];
  description?: string | null;
  fields?: Record<string, unknown>;
  mention_total?: number;
  mention_count?: number;
}

export interface RelationRef {
  id: string;
  type_slug: string;
  source_entity_id: string;
  target_entity_id: string;
  fields: Record<string, unknown>;
}

// /api/edges — denormalised relations (v_edges view) so src/tgt names are
// available without a second fetch. Reads only; writes still use RelationRef.
export interface EdgeRow {
  edge_id: string;
  edge_type: string;
  edge_label: string | null;
  src_id: string;
  src_type: string;
  src_name: string;
  tgt_id: string;
  tgt_type: string;
  tgt_name: string;
  edge_fields: Record<string, unknown>;
  edge_created_ts: string | null;
}

export interface TagRef {
  id: string;
  canonical_name: string;
  category: string | null;
  confidence?: number;
}

export interface DocumentDetail {
  id: string;
  source_path: string | null;
  source_uri: string | null;
  source_type: string;
  title: string | null;
  doc_type: DocType | null;
  author: string | null;
  created_at: string | null;
  summary: string | null;
  raw_text: string | null;
  content_hash: string;
  language: string | null;
  metadata: Record<string, unknown>;
  entities: EntityRef[];
  tags: TagRef[];
}

export interface AgentTrace {
  iteration: number;
  tool: string;
  arguments: Record<string, unknown>;
  result_preview: string;
  error: string | null;
  rewritten_question?: string | null;
}

export interface AskResponse {
  question: string;
  answer: string;
  citations: Citation[];
  trace: AgentTrace[];
  iterations: number;
  exhausted: boolean;
  error: string | null;
}

export interface IngestionReport {
  source_path: string;
  status: "created" | "updated" | "skipped" | "error";
  document_id: string | null;
  tags_added: number;
  entities_added_by_type: Record<string, number>;
  error: string | null;
  extraction_error: string | null;
}

export interface IngestResponse {
  path: string;
  glob: string | null;
  summary: Record<string, number>;
  reports: IngestionReport[];
}
