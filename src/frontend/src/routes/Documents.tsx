import { useState } from "react";
import useSWR from "swr";
import { Link } from "react-router-dom";
import { fetcher } from "../api/client";
import type { DocType, DocumentListResponse } from "../api/types";
import PageHeader from "../components/PageHeader";
import EmptyState from "../components/EmptyState";
import Badge from "../components/Badge";
import styles from "./Documents.module.css";

const DOC_TYPES: DocType[] = ["memo", "meeting", "journal", "reference", "spec", "other"];

export default function Documents() {
  const [q, setQ] = useState("");
  const [docType, setDocType] = useState<string>("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const params = new URLSearchParams();
  params.set("limit", "50");
  if (q.trim()) params.set("q", q.trim());
  if (docType) params.set("doc_type", docType);
  if (dateFrom) params.set("date_from", dateFrom);
  if (dateTo) params.set("date_to", dateTo);

  const { data, error, isLoading } = useSWR<DocumentListResponse>(
    `/api/documents?${params.toString()}`,
    fetcher,
  );

  return (
    <div>
      <PageHeader title="Documents" subtitle={`${data?.total ?? 0} 件`} />

      <div className={styles.filters}>
        <input
          type="search"
          className={styles.search}
          placeholder="検索 (3文字以上)"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <select
          className={styles.select}
          value={docType}
          onChange={(e) => setDocType(e.target.value)}
        >
          <option value="">All doc types</option>
          {DOC_TYPES.map((d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ))}
        </select>
        <input
          type="date"
          className={styles.select}
          value={dateFrom}
          onChange={(e) => setDateFrom(e.target.value)}
        />
        <input
          type="date"
          className={styles.select}
          value={dateTo}
          onChange={(e) => setDateTo(e.target.value)}
        />
      </div>

      {error && <div className={styles.error}>{String(error)}</div>}
      {isLoading && <div className={styles.muted}>Loading…</div>}

      {data?.items?.length ? (
        <ul className={styles.list}>
          {data.items.map((it) => (
            <li key={it.document_id} className={styles.item}>
              <div className={styles.itemHead}>
                <Link to={`/documents/${it.document_id}`} className={styles.title}>
                  {it.title || it.source_path || it.document_id}
                </Link>
                {it.doc_type && <Badge tone="accent">{it.doc_type}</Badge>}
                {it.created_at && (
                  <span className={styles.meta}>{it.created_at}</span>
                )}
              </div>
              {it.snippet && (
                <div
                  className={styles.snippet}
                  dangerouslySetInnerHTML={{ __html: it.snippet }}
                />
              )}
              {it.source_path && (
                <div className={styles.path}>{it.source_path}</div>
              )}
            </li>
          ))}
        </ul>
      ) : !isLoading ? (
        <EmptyState title="No documents" />
      ) : null}
    </div>
  );
}
