import { useEffect, useState } from "react";
import useSWR, { mutate } from "swr";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError, api, fetcher } from "../api/client";
import { useTypes } from "../api/useTypes";
import type {
  DocumentDetail,
  EntityRef,
  EntityTypeDef,
  FieldSpec,
  RelationRef,
} from "../api/types";
import PageHeader from "../components/PageHeader";
import EmptyState from "../components/EmptyState";
import Badge from "../components/Badge";
import DynamicForm, {
  DynamicFormValues,
  pickFieldValues,
  HeaderFieldSpec,
} from "../components/DynamicForm";
import styles from "./Entities.module.css";

type Mode =
  | { kind: "idle" }
  | { kind: "create"; typeSlug: string }
  | { kind: "edit"; entityId: string };

const HEADER_FIELDS: HeaderFieldSpec[] = [
  {
    name: "canonical_name",
    label: "canonical name",
    type: "string",
    required: true,
    placeholder: "正規名 (一意のラベル)",
  },
  {
    name: "description",
    label: "description",
    type: "text",
    placeholder: "任意のメモ",
  },
  {
    name: "aliases",
    label: "aliases (カンマ区切り)",
    type: "string",
    placeholder: "Alice, A. Tanaka",
  },
];

export default function Entities() {
  const [searchParams, setSearchParams] = useSearchParams();
  const initialType = searchParams.get("type") ?? "";

  const [q, setQ] = useState("");
  const [typeSlug, setTypeSlug] = useState<string>(initialType);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [mode, setMode] = useState<Mode>({ kind: "idle" });

  const { entityTypes, entityBySlug } = useTypes();

  // Keep ?type= in the URL synced.
  useEffect(() => {
    const next = new URLSearchParams(searchParams);
    if (typeSlug) {
      next.set("type", typeSlug);
    } else {
      next.delete("type");
    }
    setSearchParams(next, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [typeSlug]);

  // Default the selected type once the registry loads.
  useEffect(() => {
    if (!typeSlug && entityTypes && entityTypes.length > 0) {
      setTypeSlug(entityTypes[0].slug);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entityTypes]);

  const params = new URLSearchParams();
  params.set("top_k", "100");
  if (q.trim()) params.set("q", q.trim());
  if (typeSlug) params.set("type_slug", typeSlug);
  const listUrl = `/api/entities?${params.toString()}`;
  const { data: entities, mutate: mutateEntities } = useSWR<EntityRef[]>(
    listUrl,
    fetcher,
  );

  const selectedType: EntityTypeDef | undefined = typeSlug
    ? entityBySlug.get(typeSlug)
    : undefined;
  const fieldsSchema: FieldSpec[] = selectedType?.fields_schema ?? [];

  const selected = entities?.find((e) => e.id === selectedId) ?? null;

  function reloadAll() {
    mutateEntities();
    // Stats card on the dashboard relies on the same data.
    mutate("/api/stats");
  }

  return (
    <div>
      <PageHeader
        title="Entities"
        subtitle={`${entities?.length ?? 0} 件`}
      />

      <div className={styles.typeChips}>
        <button
          className={!typeSlug ? `${styles.chip} ${styles.chipActive}` : styles.chip}
          onClick={() => {
            setTypeSlug("");
            setSelectedId(null);
            setMode({ kind: "idle" });
          }}
        >
          All types
        </button>
        {entityTypes?.map((t) => (
          <button
            key={t.slug}
            className={
              t.slug === typeSlug
                ? `${styles.chip} ${styles.chipActive}`
                : styles.chip
            }
            onClick={() => {
              setTypeSlug(t.slug);
              setSelectedId(null);
              setMode({ kind: "idle" });
            }}
          >
            {t.label}{" "}
            <span style={{ opacity: 0.7 }}>({t.slug})</span>
          </button>
        ))}
      </div>

      <div className={styles.filters}>
        <input
          type="search"
          className={styles.search}
          placeholder="名前で検索"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        {typeSlug && (
          <button
            className={styles.newBtn}
            onClick={() => setMode({ kind: "create", typeSlug })}
          >
            + New {selectedType?.label ?? typeSlug}
          </button>
        )}
      </div>

      {mode.kind === "create" && (
        <div className={styles.editorPanel}>
          <h3>New {selectedType?.label}</h3>
          <EntityForm
            fields={fieldsSchema}
            onSubmit={async (values) => {
              await api.post("/api/entities", buildEntityPayload(values, fieldsSchema, mode.typeSlug));
              setMode({ kind: "idle" });
              reloadAll();
            }}
            onCancel={() => setMode({ kind: "idle" })}
          />
        </div>
      )}

      {mode.kind === "edit" && selected && (
        <div className={styles.editorPanel}>
          <h3>Edit {selected.canonical_name}</h3>
          <EntityForm
            fields={fieldsSchema}
            initial={{
              canonical_name: selected.canonical_name,
              description: selected.description ?? "",
              aliases: (selected.aliases || []).join(", "),
              ...(selected.fields ?? {}),
            }}
            onSubmit={async (values) => {
              const payload: Record<string, unknown> = {
                canonical_name: values.canonical_name,
                description: values.description || null,
                aliases: parseAliases(values.aliases as string),
                fields: pickFieldValues(values, fieldsSchema),
              };
              await api.patch(`/api/entities/${selected.id}`, payload);
              setMode({ kind: "idle" });
              reloadAll();
            }}
            onCancel={() => setMode({ kind: "idle" })}
          />
        </div>
      )}

      <div className={styles.layout}>
        <div className={styles.list}>
          {entities?.length === 0 && <EmptyState title="No entities" />}
          {entities?.map((e) => (
            <button
              key={e.id}
              className={`${styles.item} ${
                e.id === selectedId ? styles.itemActive : ""
              }`}
              onClick={() => {
                setSelectedId(e.id);
                setMode({ kind: "idle" });
              }}
            >
              <div className={styles.itemHead}>
                <span className={styles.itemName}>{e.canonical_name}</span>
                <Badge tone="muted">{e.type_slug}</Badge>
              </div>
              <ItemSummary entity={e} type={entityBySlug.get(e.type_slug)} />
            </button>
          ))}
        </div>

        <EntityDetail
          entity={selected}
          type={selected ? entityBySlug.get(selected.type_slug) : undefined}
          onEdit={() => selected && setMode({ kind: "edit", entityId: selected.id })}
          onDelete={async () => {
            if (!selected) return;
            if (!confirm(`"${selected.canonical_name}" を削除しますか？`)) return;
            try {
              await api.deleteRoute(`/api/entities/${selected.id}`);
              setSelectedId(null);
              reloadAll();
            } catch (err) {
              alert(err instanceof ApiError ? err.message : String(err));
            }
          }}
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Detail panel
// ---------------------------------------------------------------------------
function EntityDetail({
  entity,
  type,
  onEdit,
  onDelete,
}: {
  entity: EntityRef | null;
  type: EntityTypeDef | undefined;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const { data: docs } = useSWR<DocumentDetail[]>(
    entity ? `/api/entities/${entity.id}/documents` : null,
    fetcher,
  );
  const { data: outgoing } = useSWR<RelationRef[]>(
    entity ? `/api/relations?source_entity_id=${entity.id}` : null,
    fetcher,
  );
  const { data: incoming } = useSWR<RelationRef[]>(
    entity ? `/api/relations?target_entity_id=${entity.id}` : null,
    fetcher,
  );

  if (!entity) {
    return (
      <div className={styles.detail}>
        <EmptyState title="エンティティを選択" />
      </div>
    );
  }
  return (
    <div className={styles.detail}>
      <h2 className={styles.detailTitle}>
        {entity.canonical_name}{" "}
        <Badge tone="muted">{entity.type_slug}</Badge>
      </h2>
      <div className={styles.detailActions}>
        <button onClick={onEdit}>Edit</button>
        <button onClick={onDelete}>Delete</button>
      </div>
      {entity.aliases.length > 0 && (
        <div className={styles.aliases}>
          aliases: {entity.aliases.join(", ")}
        </div>
      )}
      {entity.description && (
        <div className={styles.aliases}>{entity.description}</div>
      )}
      {entity.fields && Object.keys(entity.fields).length > 0 && (
        <dl className={styles.fields}>
          {(type?.fields_schema ?? []).map((spec) => {
            const v = entity.fields?.[spec.name];
            if (v === undefined || v === null || v === "") return null;
            return (
              <FieldRow key={spec.name} label={spec.label} name={spec.name} value={v} />
            );
          })}
          {/* extras not declared in the schema (Stage 5 user types may drift) */}
          {Object.entries(entity.fields)
            .filter(([k]) => !(type?.fields_schema ?? []).some((s) => s.name === k))
            .map(([k, v]) => (
              <FieldRow key={k} label={k} name={k} value={v} />
            ))}
        </dl>
      )}

      <h3 className={styles.docsHeader}>Mentioned in</h3>
      {!docs ? (
        <div className={styles.muted}>Loading…</div>
      ) : docs.length === 0 ? (
        <EmptyState title="(no documents)" />
      ) : (
        <ul className={styles.docs}>
          {docs.map((d) => (
            <li key={d.id}>
              <Link to={`/documents/${d.id}`}>
                {d.title || d.source_path || d.id}
              </Link>
              <span className={styles.muted}>{d.doc_type || "—"}</span>
            </li>
          ))}
        </ul>
      )}

      {(outgoing?.length || incoming?.length) ? (
        <div className={styles.relations}>
          <h3 className={styles.docsHeader}>Relations</h3>
          {outgoing?.map((r) => (
            <div key={r.id} className={styles.relRow}>
              <Badge tone="accent">{r.type_slug}</Badge>
              <span>→ {r.target_entity_id}</span>
            </div>
          ))}
          {incoming?.map((r) => (
            <div key={r.id} className={styles.relRow}>
              <span>{r.source_entity_id} →</span>
              <Badge tone="accent">{r.type_slug}</Badge>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function FieldRow({
  label,
  name,
  value,
}: {
  label: string;
  name: string;
  value: unknown;
}) {
  return (
    <>
      <div className={styles.fieldKey} title={name}>
        {label}
      </div>
      <div>{formatValue(value)}</div>
    </>
  );
}

function formatValue(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "boolean") return v ? "true" : "false";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

// ---------------------------------------------------------------------------
// EntityForm wraps DynamicForm with the canonical_name / description / aliases
// header so the dynamic fields stay focused on the FieldSpec[] view.
// ---------------------------------------------------------------------------
function EntityForm({
  fields,
  initial,
  onSubmit,
  onCancel,
}: {
  fields: FieldSpec[];
  initial?: DynamicFormValues;
  onSubmit: (values: DynamicFormValues) => Promise<void>;
  onCancel: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  return (
    <>
      <DynamicForm
        fields={fields}
        headerFields={HEADER_FIELDS}
        initial={initial}
        submitting={submitting}
        onCancel={onCancel}
        submitLabel="Save"
        onSubmit={async (values) => {
          setError(null);
          setSubmitting(true);
          try {
            await onSubmit(values);
          } catch (err) {
            setError(err instanceof ApiError ? err.message : String(err));
          } finally {
            setSubmitting(false);
          }
        }}
      />
      {error && <div className={styles.error}>{error}</div>}
    </>
  );
}

function ItemSummary({
  entity,
  type,
}: {
  entity: EntityRef;
  type?: EntityTypeDef;
}) {
  if (!type || type.fields_schema.length === 0) {
    if (entity.mention_total) {
      return (
        <div className={styles.itemMeta}>{entity.mention_total} mentions</div>
      );
    }
    return null;
  }
  // Show first 2 field values for a quick scan in the list.
  const pairs = type.fields_schema
    .slice(0, 2)
    .map((f) => entity.fields?.[f.name])
    .filter((v) => v !== null && v !== undefined && v !== "");
  if (pairs.length === 0) return null;
  return <div className={styles.itemMeta}>{pairs.join(" · ")}</div>;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function parseAliases(raw: string): string[] {
  return (raw ?? "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

function buildEntityPayload(
  values: DynamicFormValues,
  fields: FieldSpec[],
  typeSlug: string,
): Record<string, unknown> {
  return {
    type_slug: typeSlug,
    canonical_name: values.canonical_name,
    description: values.description || null,
    aliases: parseAliases(values.aliases as string),
    fields: pickFieldValues(values, fields),
  };
}
