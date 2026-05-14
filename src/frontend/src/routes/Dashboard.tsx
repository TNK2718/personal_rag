import useSWR from "swr";
import { Link } from "react-router-dom";
import { fetcher } from "../api/client";
import type {
  DocumentListResponse,
  Stats,
  Todo,
} from "../api/types";
import PageHeader from "../components/PageHeader";
import EmptyState from "../components/EmptyState";
import Badge from "../components/Badge";
import styles from "./Dashboard.module.css";

const STATUS_TONE = {
  pending: "warning",
  in_progress: "accent",
  completed: "success",
  cancelled: "muted",
} as const;

export default function Dashboard() {
  const { data: stats } = useSWR<Stats>("/api/stats", fetcher);
  const { data: docs } = useSWR<DocumentListResponse>(
    "/api/documents?limit=5",
    fetcher,
  );
  const { data: todos } = useSWR<Todo[]>(
    "/api/todos?status=pending&limit=5",
    fetcher,
  );

  return (
    <div>
      <PageHeader title="Dashboard" subtitle="知識ベース全体の状況" />

      <section className={styles.cards}>
        <Card label="Documents" value={stats?.documents_total} />
        <Card label="Todos" value={stats?.todos_total} />
        <Card label="Entities" value={stats?.entities_total} />
        <Card label="Tags" value={stats?.tags_total} />
      </section>

      <section className={styles.row}>
        <Panel title="Doc types">
          {stats?.doc_types?.length ? (
            <ul className={styles.breakdown}>
              {stats.doc_types.map((d) => {
                const ratio = stats.documents_total
                  ? d.count / stats.documents_total
                  : 0;
                return (
                  <li key={d.doc_type}>
                    <div className={styles.breakdownRow}>
                      <span>{d.doc_type}</span>
                      <span className={styles.muted}>{d.count}</span>
                    </div>
                    <div className={styles.bar}>
                      <div
                        className={styles.barFill}
                        style={{ width: `${ratio * 100}%` }}
                      />
                    </div>
                  </li>
                );
              })}
            </ul>
          ) : (
            <EmptyState title="No documents yet" description="Ingest をどうぞ" />
          )}
        </Panel>

        <Panel title="Recent documents">
          {docs?.items?.length ? (
            <ul className={styles.list}>
              {docs.items.map((it) => (
                <li key={it.document_id}>
                  <Link to={`/documents/${it.document_id}`}>
                    {it.title || it.source_path || it.document_id}
                  </Link>
                  <span className={styles.meta}>{it.doc_type || "—"}</span>
                  <span className={styles.meta}>{it.created_at || ""}</span>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState title="Empty" />
          )}
        </Panel>

        <Panel title="Pending todos">
          {todos?.length ? (
            <ul className={styles.list}>
              {todos.map((t) => (
                <li key={t.id}>
                  <Badge tone={STATUS_TONE[t.status]}>{t.status}</Badge>
                  <span style={{ marginLeft: 8 }}>{t.content}</span>
                  {t.due_date && (
                    <span className={styles.meta}>{t.due_date}</span>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState title="No pending todos" />
          )}
        </Panel>
      </section>
    </div>
  );
}

function Card({ label, value }: { label: string; value: number | undefined }) {
  return (
    <div className={styles.card}>
      <div className={styles.cardLabel}>{label}</div>
      <div className={styles.cardValue}>{value ?? "—"}</div>
    </div>
  );
}

function Panel({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className={styles.panel}>
      <h2 className={styles.panelTitle}>{title}</h2>
      {children}
    </div>
  );
}
