import { useEffect, useState } from "react";
import useSWR from "swr";
import { Link, useSearchParams } from "react-router-dom";
import { fetcher } from "../api/client";
import type {
  DocumentDetail,
  EntityRef,
  EntityTypeDef,
} from "../api/types";
import PageHeader from "../components/PageHeader";
import EmptyState from "../components/EmptyState";
import Badge from "../components/Badge";
import styles from "./Entities.module.css";

export default function Entities() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [q, setQ] = useState("");
  const [typeSlug, setTypeSlug] = useState<string>(searchParams.get("type") || "");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // Sync the type filter back to the URL so /entities?type=task is shareable.
  useEffect(() => {
    if (typeSlug) {
      setSearchParams({ type: typeSlug }, { replace: true });
    } else if (searchParams.has("type")) {
      setSearchParams({}, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [typeSlug]);

  const { data: types } = useSWR<EntityTypeDef[]>("/api/types/entities", fetcher);

  const params = new URLSearchParams();
  params.set("top_k", "100");
  if (q.trim()) params.set("q", q.trim());
  if (typeSlug) params.set("type_slug", typeSlug);

  const { data: entities } = useSWR<EntityRef[]>(
    `/api/entities?${params.toString()}`,
    fetcher,
  );

  const { data: docs } = useSWR<DocumentDetail[]>(
    selectedId ? `/api/entities/${selectedId}/documents` : null,
    fetcher,
  );

  const selected = entities?.find((e) => e.id === selectedId) ?? null;

  return (
    <div>
      <PageHeader title="Entities" subtitle={`${entities?.length ?? 0} 件`} />

      <div className={styles.filters}>
        <input
          type="search"
          className={styles.search}
          placeholder="名前で検索"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <select
          className={styles.select}
          value={typeSlug}
          onChange={(e) => setTypeSlug(e.target.value)}
        >
          <option value="">All types</option>
          {types?.map((t) => (
            <option key={t.slug} value={t.slug}>
              {t.label} ({t.slug})
            </option>
          ))}
        </select>
      </div>

      <div className={styles.layout}>
        <div className={styles.list}>
          {entities?.length === 0 && <EmptyState title="No entities" />}
          {entities?.map((e) => (
            <button
              key={e.id}
              className={`${styles.item} ${
                e.id === selectedId ? styles.itemActive : ""
              }`}
              onClick={() => setSelectedId(e.id)}
            >
              <div className={styles.itemHead}>
                <span className={styles.itemName}>{e.canonical_name}</span>
                <Badge tone="muted">{e.type_slug}</Badge>
              </div>
              {!!e.mention_total && (
                <div className={styles.itemMeta}>
                  {e.mention_total} mentions
                </div>
              )}
            </button>
          ))}
        </div>

        <div className={styles.detail}>
          {!selected ? (
            <EmptyState title="エンティティを選択" />
          ) : (
            <>
              <h2 className={styles.detailTitle}>
                {selected.canonical_name}{" "}
                <Badge tone="muted">{selected.type_slug}</Badge>
              </h2>
              {selected.aliases.length > 0 && (
                <div className={styles.aliases}>
                  aliases: {selected.aliases.join(", ")}
                </div>
              )}
              {selected.fields && Object.keys(selected.fields).length > 0 && (
                <dl className={styles.aliases}>
                  {Object.entries(selected.fields).map(([k, v]) => (
                    <div key={k}>
                      <strong>{k}:</strong> {String(v ?? "")}
                    </div>
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
            </>
          )}
        </div>
      </div>
    </div>
  );
}
