import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { Link, useSearchParams } from "react-router-dom";
import { fetcher } from "../api/client";
import { useTypes } from "../api/useTypes";
import type { EdgeRow } from "../api/types";
import PageHeader from "../components/PageHeader";
import EmptyState from "../components/EmptyState";
import Badge from "../components/Badge";
import styles from "./Relations.module.css";

// Relations browse view — backed by /api/edges (denormalised v_edges rows).
// Filter by edge type, free-text src/tgt name match, page shape mirrors
// Entities for muscle-memory consistency.
export default function Relations() {
  const [searchParams, setSearchParams] = useSearchParams();
  const initialType = searchParams.get("type") ?? "";

  const [q, setQ] = useState("");
  const [typeSlug, setTypeSlug] = useState<string>(initialType);

  const { relationTypes } = useTypes();

  useEffect(() => {
    const next = new URLSearchParams(searchParams);
    if (typeSlug) next.set("type", typeSlug);
    else next.delete("type");
    setSearchParams(next, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [typeSlug]);

  const params = new URLSearchParams();
  params.set("top_k", "200");
  if (q.trim()) params.set("q", q.trim());
  if (typeSlug) params.set("type_slug", typeSlug);
  const listUrl = `/api/edges?${params.toString()}`;
  const { data: edges } = useSWR<EdgeRow[]>(listUrl, fetcher);

  // Counts per edge_type for chip badges. Counts the unfiltered fetch
  // is too expensive; we count what is currently visible, like Entities.
  const counts = useMemo(() => {
    const m = new Map<string, number>();
    for (const e of edges ?? []) m.set(e.edge_type, (m.get(e.edge_type) ?? 0) + 1);
    return m;
  }, [edges]);

  return (
    <div>
      <PageHeader title="Relations" subtitle={`${edges?.length ?? 0} 件`} />

      <div className={styles.typeChips}>
        <button
          className={!typeSlug ? `${styles.chip} ${styles.chipActive}` : styles.chip}
          onClick={() => setTypeSlug("")}
        >
          All types
        </button>
        {relationTypes?.map((t) => {
          const n = counts.get(t.slug);
          return (
            <button
              key={t.slug}
              className={
                t.slug === typeSlug
                  ? `${styles.chip} ${styles.chipActive}`
                  : styles.chip
              }
              onClick={() => setTypeSlug(t.slug)}
              title={t.description ?? undefined}
            >
              {t.label}
              <span className={styles.chipMeta}>
                {" "}
                ({t.slug}
                {!typeSlug && n ? `, ${n}` : ""})
              </span>
            </button>
          );
        })}
      </div>

      <div className={styles.filters}>
        <input
          type="search"
          className={styles.search}
          placeholder="名前で検索 (src / tgt)"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
      </div>

      {edges?.length === 0 ? (
        <EmptyState title="No relations" />
      ) : (
        <div className={styles.list}>
          {edges?.map((e, idx) => (
            <div key={e.edge_id} className={styles.row}>
              <div className={styles.srcCell}>
                <Link
                  to={`/entities?type=${encodeURIComponent(e.src_type)}`}
                  className={styles.endpointLink}
                  title={e.src_id}
                >
                  {e.src_name}
                </Link>
                <span className={styles.endpointType}>{e.src_type}</span>
              </div>
              <div className={styles.edgeCell}>
                <Badge tone="accent">
                  {e.edge_label ?? e.edge_type}
                </Badge>
              </div>
              <div className={styles.tgtCell}>
                <Link
                  to={`/entities?type=${encodeURIComponent(e.tgt_type)}`}
                  className={styles.endpointLink}
                  title={e.tgt_id}
                >
                  {e.tgt_name}
                </Link>
                <span className={styles.endpointType}>{e.tgt_type}</span>
              </div>
              {idx < (edges?.length ?? 0) - 1 && <div className={styles.rowDivider} />}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
