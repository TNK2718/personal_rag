import { useState } from "react";
import useSWR from "swr";
import { fetcher } from "../api/client";
import type {
  EntityTypeDef,
  FieldSpec,
  RelationTypeDef,
} from "../api/types";
import PageHeader from "../components/PageHeader";
import Badge from "../components/Badge";
import EmptyState from "../components/EmptyState";
import styles from "./Settings.module.css";

type Tab = "entities" | "relations";

export default function Settings() {
  const [tab, setTab] = useState<Tab>("entities");

  const { data: entityTypes } = useSWR<EntityTypeDef[]>(
    "/api/types/entities",
    fetcher,
  );
  const { data: relationTypes } = useSWR<RelationTypeDef[]>(
    "/api/types/relations",
    fetcher,
  );

  return (
    <div>
      <PageHeader
        title="Settings"
        subtitle="Entity / Relation type registry (read-only in Stage 1)"
      />

      <div className={styles.tabs}>
        <button
          className={tab === "entities" ? `${styles.tab} ${styles.tabActive}` : styles.tab}
          onClick={() => setTab("entities")}
        >
          Entity types ({entityTypes?.length ?? 0})
        </button>
        <button
          className={tab === "relations" ? `${styles.tab} ${styles.tabActive}` : styles.tab}
          onClick={() => setTab("relations")}
        >
          Relation types ({relationTypes?.length ?? 0})
        </button>
      </div>

      {tab === "entities" && <EntityTypeList items={entityTypes} />}
      {tab === "relations" && <RelationTypeList items={relationTypes} />}

      <p className={styles.placeholder}>
        編集 UI は Stage 4 で追加されます。Stage 1 は登録済みの型を確認するための画面です。
      </p>
    </div>
  );
}

function EntityTypeList({ items }: { items?: EntityTypeDef[] }) {
  if (!items) return null;
  if (items.length === 0) return <EmptyState title="No entity types defined" />;
  return (
    <div className={styles.list}>
      {items.map((t) => (
        <article key={t.slug} className={styles.card}>
          <div className={styles.cardHead}>
            <div>
              <span className={styles.label}>{t.label}</span>{" "}
              <span className={styles.slug}>{t.slug}</span>
            </div>
            {t.is_builtin && <Badge tone="muted">built-in</Badge>}
          </div>
          {t.description && <div className={styles.description}>{t.description}</div>}
          <FieldSchemaList fields={t.fields_schema} />
          {t.extraction_hint && (
            <div className={styles.hint}>
              <strong>LLM hint:</strong> {t.extraction_hint}
            </div>
          )}
        </article>
      ))}
    </div>
  );
}

function RelationTypeList({ items }: { items?: RelationTypeDef[] }) {
  if (!items) return null;
  if (items.length === 0) return <EmptyState title="No relation types defined" />;
  return (
    <div className={styles.list}>
      {items.map((t) => (
        <article key={t.slug} className={styles.card}>
          <div className={styles.cardHead}>
            <div>
              <span className={styles.label}>{t.label}</span>{" "}
              <span className={styles.slug}>{t.slug}</span>
              {t.inverse_label && (
                <span className={styles.slug}> ⇄ {t.inverse_label}</span>
              )}
            </div>
            {t.is_builtin && <Badge tone="muted">built-in</Badge>}
          </div>
          {t.description && <div className={styles.description}>{t.description}</div>}
          <div className={styles.fieldRow}>
            <span className={styles.fieldType}>source:</span>
            <span className={styles.fieldName}>{t.source_type_slug ?? "any"}</span>
            <span className={styles.fieldType}>→ target:</span>
            <span className={styles.fieldName}>{t.target_type_slug ?? "any"}</span>
          </div>
          <FieldSchemaList fields={t.fields_schema} />
          {t.extraction_hint && (
            <div className={styles.hint}>
              <strong>LLM hint:</strong> {t.extraction_hint}
            </div>
          )}
        </article>
      ))}
    </div>
  );
}

function FieldSchemaList({ fields }: { fields: FieldSpec[] }) {
  if (fields.length === 0) {
    return <div className={styles.empty}>(no custom fields)</div>;
  }
  return (
    <div className={styles.fieldList}>
      {fields.map((f) => (
        <div key={f.name} className={styles.fieldRow}>
          <span className={styles.fieldName}>{f.name}</span>
          <span className={styles.fieldType}>: {f.type}</span>
          {f.required && <Badge tone="warning">required</Badge>}
          {f.type === "enum" && f.options && (
            <span className={styles.fieldType}>[{f.options.join(", ")}]</span>
          )}
          {f.default !== undefined && f.default !== null && (
            <span className={styles.fieldType}>
              default: {String(f.default)}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}
