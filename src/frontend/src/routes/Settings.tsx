import { useState } from "react";
import { ApiError, api } from "../api/client";
import { useTypes } from "../api/useTypes";
import type {
  EntityTypeDef,
  FieldSpec,
  RelationTypeDef,
} from "../api/types";
import PageHeader from "../components/PageHeader";
import Badge from "../components/Badge";
import EmptyState from "../components/EmptyState";
import FieldSpecEditor from "../components/FieldSpecEditor";
import styles from "./Settings.module.css";

type Tab = "entities" | "relations";

type EditState =
  | { kind: "none" }
  | { kind: "new"; tab: Tab }
  | { kind: "edit"; tab: Tab; slug: string };

export default function Settings() {
  const [tab, setTab] = useState<Tab>("entities");
  const [edit, setEdit] = useState<EditState>({ kind: "none" });
  const { entityTypes, relationTypes, refresh } = useTypes();

  const editing =
    edit.kind === "edit"
      ? (edit.tab === "entities"
          ? (entityTypes ?? []).find((t) => t.slug === edit.slug)
          : (relationTypes ?? []).find((t) => t.slug === edit.slug)) ?? null
      : null;

  return (
    <div>
      <PageHeader
        title="Settings"
        subtitle="Entity / Relation 型レジストリ"
      />

      <div className={styles.tabs}>
        <button
          className={tab === "entities" ? `${styles.tab} ${styles.tabActive}` : styles.tab}
          onClick={() => {
            setTab("entities");
            setEdit({ kind: "none" });
          }}
        >
          Entity types ({entityTypes?.length ?? 0})
        </button>
        <button
          className={tab === "relations" ? `${styles.tab} ${styles.tabActive}` : styles.tab}
          onClick={() => {
            setTab("relations");
            setEdit({ kind: "none" });
          }}
        >
          Relation types ({relationTypes?.length ?? 0})
        </button>
      </div>

      <div className={styles.toolbar}>
        <div />
        <button
          className={styles.newBtn}
          onClick={() => setEdit({ kind: "new", tab })}
        >
          + New {tab === "entities" ? "entity" : "relation"} type
        </button>
      </div>

      {edit.kind === "new" && edit.tab === tab && (
        tab === "entities" ? (
          <EntityTypeEditor
            entityTypeSlugs={(entityTypes ?? []).map((t) => t.slug)}
            initial={null}
            onClose={() => setEdit({ kind: "none" })}
            onSaved={() => {
              refresh();
              setEdit({ kind: "none" });
            }}
          />
        ) : (
          <RelationTypeEditor
            entityTypeSlugs={(entityTypes ?? []).map((t) => t.slug)}
            initial={null}
            onClose={() => setEdit({ kind: "none" })}
            onSaved={() => {
              refresh();
              setEdit({ kind: "none" });
            }}
          />
        )
      )}

      {edit.kind === "edit" && edit.tab === tab && editing && (
        tab === "entities" ? (
          <EntityTypeEditor
            entityTypeSlugs={(entityTypes ?? []).map((t) => t.slug)}
            initial={editing as EntityTypeDef}
            onClose={() => setEdit({ kind: "none" })}
            onSaved={() => {
              refresh();
              setEdit({ kind: "none" });
            }}
          />
        ) : (
          <RelationTypeEditor
            entityTypeSlugs={(entityTypes ?? []).map((t) => t.slug)}
            initial={editing as RelationTypeDef}
            onClose={() => setEdit({ kind: "none" })}
            onSaved={() => {
              refresh();
              setEdit({ kind: "none" });
            }}
          />
        )
      )}

      {tab === "entities" && (
        <EntityTypeList
          items={entityTypes}
          onEdit={(slug) => setEdit({ kind: "edit", tab: "entities", slug })}
          onDelete={async (slug) => {
            await api.deleteRoute(`/api/types/entities/${slug}`);
            refresh();
          }}
        />
      )}
      {tab === "relations" && (
        <RelationTypeList
          items={relationTypes}
          onEdit={(slug) => setEdit({ kind: "edit", tab: "relations", slug })}
          onDelete={async (slug) => {
            await api.deleteRoute(`/api/types/relations/${slug}`);
            refresh();
          }}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Type editors
// ---------------------------------------------------------------------------
function EntityTypeEditor({
  initial,
  entityTypeSlugs,
  onClose,
  onSaved,
}: {
  initial: EntityTypeDef | null;
  entityTypeSlugs: string[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const isNew = initial === null;
  const [slug, setSlug] = useState(initial?.slug ?? "");
  const [label, setLabel] = useState(initial?.label ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [extractionHint, setExtractionHint] = useState(
    initial?.extraction_hint ?? "",
  );
  const [fieldsSchema, setFieldsSchema] = useState<FieldSpec[]>(
    initial?.fields_schema ?? [],
  );
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setError(null);
    const payload = {
      slug: slug.trim(),
      label: label.trim(),
      description: description.trim() || null,
      extraction_hint: extractionHint.trim() || null,
      fields_schema: fieldsSchema,
    };
    try {
      if (isNew) {
        await api.post("/api/types/entities", payload);
      } else {
        await api.put(`/api/types/entities/${initial!.slug}`, payload);
      }
      onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className={styles.editor} onSubmit={submit}>
      <div className={styles.formRow}>
        <div className={styles.editorField}>
          <label>slug (snake_case, unique)</label>
          <input
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            disabled={!isNew}
            placeholder="e.g. meeting_topic"
            required
          />
        </div>
        <div className={styles.editorField}>
          <label>label (表示名)</label>
          <input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="議題"
            required
          />
        </div>
      </div>
      <div className={styles.editorField}>
        <label>description</label>
        <textarea
          rows={2}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </div>
      <div className={styles.editorField}>
        <label>LLM extraction hint (200 字程度推奨)</label>
        <textarea
          rows={2}
          value={extractionHint}
          onChange={(e) => setExtractionHint(e.target.value)}
          placeholder="どんなときにこの型を作るか、LLM に伝える一文"
        />
      </div>
      <div className={styles.editorField}>
        <label>fields</label>
        <FieldSpecEditor
          value={fieldsSchema}
          onChange={setFieldsSchema}
          refTypeSlugs={entityTypeSlugs}
        />
      </div>
      {error && <div className={styles.error}>{error}</div>}
      <div className={styles.editorActions}>
        <button type="submit" className={styles.primary} disabled={submitting}>
          {submitting ? "..." : isNew ? "Create" : "Save"}
        </button>
        <button type="button" className={styles.secondary} onClick={onClose}>
          Cancel
        </button>
      </div>
    </form>
  );
}

function RelationTypeEditor({
  initial,
  entityTypeSlugs,
  onClose,
  onSaved,
}: {
  initial: RelationTypeDef | null;
  entityTypeSlugs: string[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const isNew = initial === null;
  const [slug, setSlug] = useState(initial?.slug ?? "");
  const [label, setLabel] = useState(initial?.label ?? "");
  const [inverseLabel, setInverseLabel] = useState(initial?.inverse_label ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [extractionHint, setExtractionHint] = useState(
    initial?.extraction_hint ?? "",
  );
  const [sourceTypeSlug, setSourceTypeSlug] = useState(
    initial?.source_type_slug ?? "",
  );
  const [targetTypeSlug, setTargetTypeSlug] = useState(
    initial?.target_type_slug ?? "",
  );
  const [fieldsSchema, setFieldsSchema] = useState<FieldSpec[]>(
    initial?.fields_schema ?? [],
  );
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    setError(null);
    const payload = {
      slug: slug.trim(),
      label: label.trim(),
      inverse_label: inverseLabel.trim() || null,
      description: description.trim() || null,
      source_type_slug: sourceTypeSlug || null,
      target_type_slug: targetTypeSlug || null,
      extraction_hint: extractionHint.trim() || null,
      fields_schema: fieldsSchema,
    };
    try {
      if (isNew) {
        await api.post("/api/types/relations", payload);
      } else {
        await api.put(`/api/types/relations/${initial!.slug}`, payload);
      }
      onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className={styles.editor} onSubmit={submit}>
      <div className={styles.formRow}>
        <div className={styles.editorField}>
          <label>slug</label>
          <input
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            disabled={!isNew}
            placeholder="e.g. blocks"
            required
          />
        </div>
        <div className={styles.editorField}>
          <label>label</label>
          <input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            required
          />
        </div>
      </div>
      <div className={styles.formRow}>
        <div className={styles.editorField}>
          <label>source type slug (任意)</label>
          <select
            value={sourceTypeSlug}
            onChange={(e) => setSourceTypeSlug(e.target.value)}
          >
            <option value="">(any)</option>
            {entityTypeSlugs.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
        <div className={styles.editorField}>
          <label>target type slug (任意)</label>
          <select
            value={targetTypeSlug}
            onChange={(e) => setTargetTypeSlug(e.target.value)}
          >
            <option value="">(any)</option>
            {entityTypeSlugs.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
      </div>
      <div className={styles.editorField}>
        <label>inverse label (e.g. "managed by" の逆向き名)</label>
        <input
          value={inverseLabel}
          onChange={(e) => setInverseLabel(e.target.value)}
        />
      </div>
      <div className={styles.editorField}>
        <label>description</label>
        <textarea
          rows={2}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </div>
      <div className={styles.editorField}>
        <label>LLM extraction hint</label>
        <textarea
          rows={2}
          value={extractionHint}
          onChange={(e) => setExtractionHint(e.target.value)}
        />
      </div>
      <div className={styles.editorField}>
        <label>fields (relations rarely need any)</label>
        <FieldSpecEditor
          value={fieldsSchema}
          onChange={setFieldsSchema}
          refTypeSlugs={entityTypeSlugs}
        />
      </div>
      {error && <div className={styles.error}>{error}</div>}
      <div className={styles.editorActions}>
        <button type="submit" className={styles.primary} disabled={submitting}>
          {submitting ? "..." : isNew ? "Create" : "Save"}
        </button>
        <button type="button" className={styles.secondary} onClick={onClose}>
          Cancel
        </button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------------------
// Listings
// ---------------------------------------------------------------------------
function EntityTypeList({
  items,
  onEdit,
  onDelete,
}: {
  items: EntityTypeDef[] | undefined;
  onEdit: (slug: string) => void;
  onDelete: (slug: string) => Promise<void>;
}) {
  if (!items) return null;
  if (items.length === 0) return <EmptyState title="No entity types defined" />;
  return (
    <div className={styles.list}>
      {items.map((t) => (
        <TypeCard
          key={t.slug}
          slug={t.slug}
          label={t.label}
          description={t.description}
          isBuiltin={t.is_builtin}
          extractionHint={t.extraction_hint}
          fields={t.fields_schema}
          extraMeta={null}
          onEdit={() => onEdit(t.slug)}
          onDelete={
            t.is_builtin ? undefined : async () => {
              if (!confirm(`型 "${t.slug}" を削除しますか？`)) return;
              try {
                await onDelete(t.slug);
              } catch (err) {
                alert(err instanceof ApiError ? err.message : String(err));
              }
            }
          }
        />
      ))}
    </div>
  );
}

function RelationTypeList({
  items,
  onEdit,
  onDelete,
}: {
  items: RelationTypeDef[] | undefined;
  onEdit: (slug: string) => void;
  onDelete: (slug: string) => Promise<void>;
}) {
  if (!items) return null;
  if (items.length === 0) return <EmptyState title="No relation types defined" />;
  return (
    <div className={styles.list}>
      {items.map((t) => (
        <TypeCard
          key={t.slug}
          slug={t.slug}
          label={t.label}
          description={t.description}
          isBuiltin={t.is_builtin}
          extractionHint={t.extraction_hint}
          fields={t.fields_schema}
          extraMeta={
            <div className={styles.fieldRow}>
              <span className={styles.fieldType}>source:</span>
              <span>{t.source_type_slug ?? "any"}</span>
              <span className={styles.fieldType}>→ target:</span>
              <span>{t.target_type_slug ?? "any"}</span>
              {t.inverse_label && (
                <span className={styles.fieldType}>
                  inverse: {t.inverse_label}
                </span>
              )}
            </div>
          }
          onEdit={() => onEdit(t.slug)}
          onDelete={
            t.is_builtin ? undefined : async () => {
              if (!confirm(`関係型 "${t.slug}" を削除しますか？`)) return;
              try {
                await onDelete(t.slug);
              } catch (err) {
                alert(err instanceof ApiError ? err.message : String(err));
              }
            }
          }
        />
      ))}
    </div>
  );
}

function TypeCard({
  slug,
  label,
  description,
  isBuiltin,
  extractionHint,
  fields,
  extraMeta,
  onEdit,
  onDelete,
}: {
  slug: string;
  label: string;
  description: string | null;
  isBuiltin: boolean;
  extractionHint: string | null;
  fields: FieldSpec[];
  extraMeta: React.ReactNode;
  onEdit: () => void;
  onDelete?: () => void;
}) {
  return (
    <article className={styles.card}>
      <div className={styles.cardHead}>
        <div>
          <span className={styles.label}>{label}</span>{" "}
          <span className={styles.slug}>{slug}</span>{" "}
          {isBuiltin && <Badge tone="muted">built-in</Badge>}
        </div>
        <div className={styles.cardActions}>
          <button onClick={onEdit}>Edit</button>
          {onDelete && <button onClick={onDelete}>Delete</button>}
        </div>
      </div>
      {description && <div className={styles.description}>{description}</div>}
      {extraMeta}
      {fields.length === 0 ? (
        <div className={styles.empty}>(no custom fields)</div>
      ) : (
        <div>
          {fields.map((f) => (
            <div key={f.name} className={styles.fieldRow}>
              <span style={{ fontFamily: "var(--font-mono, monospace)" }}>
                {f.name}
              </span>
              <span className={styles.fieldType}>: {f.type}</span>
              {f.required && <Badge tone="warning">required</Badge>}
              {f.type === "enum" && f.options && (
                <span className={styles.fieldType}>
                  [{f.options.join(", ")}]
                </span>
              )}
            </div>
          ))}
        </div>
      )}
      {extractionHint && (
        <div className={styles.hint}>
          <strong>LLM hint:</strong> {extractionHint}
        </div>
      )}
    </article>
  );
}
