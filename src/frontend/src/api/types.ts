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

export type TodoStatus = "pending" | "in_progress" | "completed" | "cancelled";
export type Priority = "high" | "medium" | "low";
export type EntityType = "person" | "org" | "product" | "tech" | "place" | "other";

export interface Stats {
  documents_total: number;
  doc_types: Array<{ doc_type: string; count: number }>;
  todos_total: number;
  todos_by_status: Partial<Record<TodoStatus, number>>;
  entities_total: number;
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

export interface Todo {
  id: string;
  content: string;
  status: TodoStatus;
  priority: Priority;
  due_date: string | null;
  source_document_id: string | null;
  source_section: string | null;
  created_at: string | null;
  updated_at: string | null;
  source_title?: string | null;
  source_path?: string | null;
}

export interface EntityRef {
  id: string;
  canonical_name: string;
  entity_type: EntityType;
  aliases: string[];
  description?: string | null;
  mention_total?: number;
  mention_count?: number;
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
  todos: Todo[];
  entities: EntityRef[];
  tags: TagRef[];
}

export interface AgentTrace {
  iteration: number;
  tool: string;
  arguments: Record<string, unknown>;
  result_preview: string;
  error: string | null;
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
  todos_added: number;
  entities_added: number;
  tags_added: number;
  error: string | null;
  extraction_error: string | null;
}

export interface IngestResponse {
  path: string;
  glob: string | null;
  summary: Record<string, number>;
  reports: IngestionReport[];
}
