import { useState } from "react";
import useSWR from "swr";
import { Link } from "react-router-dom";
import { fetcher } from "../api/client";
import type { DocumentDetail, EntityRef, EntityType } from "../api/types";
import PageHeader from "../components/PageHeader";
import EmptyState from "../components/EmptyState";
import Badge from "../components/Badge";
import styles from "./Entities.module.css";

const TYPES: EntityType[] = ["person", "org", "product", "tech", "place", "other"];

export default function Entities() {
  const [q, setQ] = useState("");
  const [type, setType] = useState<string>("");
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const params = new URLSearchParams();
  params.set("top_k", "100");
  if (q.trim()) params.set("q", q.trim());
  if (type) params.set("entity_type", type);

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
          value={type}
          onChange={(e) => setType(e.target.value)}
        >
          <option value="">All types</option>
          {TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
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
                <Badge tone="muted">{e.entity_type}</Badge>
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
                <Badge tone="muted">{selected.entity_type}</Badge>
              </h2>
              {selected.aliases.length > 0 && (
                <div className={styles.aliases}>
                  aliases: {selected.aliases.join(", ")}
                </div>
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
