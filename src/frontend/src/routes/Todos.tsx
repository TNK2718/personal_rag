import { useState } from "react";
import useSWR, { mutate } from "swr";
import { Link } from "react-router-dom";
import { api, fetcher } from "../api/client";
import type { Priority, Todo, TodoStatus } from "../api/types";
import PageHeader from "../components/PageHeader";
import EmptyState from "../components/EmptyState";
import Badge from "../components/Badge";
import styles from "./Todos.module.css";

const COLUMNS: { status: TodoStatus; label: string }[] = [
  { status: "pending", label: "Pending" },
  { status: "in_progress", label: "In progress" },
  { status: "completed", label: "Completed" },
  { status: "cancelled", label: "Cancelled" },
];

const PRIORITY_TONE = {
  high: "danger",
  medium: "warning",
  low: "muted",
} as const;

export default function Todos() {
  const [priority, setPriority] = useState<string>("");
  const params = new URLSearchParams();
  params.set("limit", "300");
  if (priority) params.set("priority", priority);
  const key = `/api/todos?${params.toString()}`;

  const { data, error, isLoading } = useSWR<Todo[]>(key, fetcher);
  const [dragId, setDragId] = useState<string | null>(null);

  async function updateStatus(id: string, status: TodoStatus) {
    try {
      await api.patch(`/api/todos/${id}`, { status });
      mutate(key);
    } catch (err) {
      console.error(err);
      alert("更新に失敗しました: " + String(err));
    }
  }

  function groupBy<T extends TodoStatus>(status: T) {
    return (data || []).filter((t) => t.status === status);
  }

  return (
    <div>
      <PageHeader
        title="Todos"
        subtitle={`${data?.length ?? 0} 件`}
        actions={
          <select
            className={styles.select}
            value={priority}
            onChange={(e) => setPriority(e.target.value)}
          >
            <option value="">All priorities</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
        }
      />

      {error && <div className={styles.error}>{String(error)}</div>}
      {isLoading && <div className={styles.muted}>Loading…</div>}

      <div className={styles.board}>
        {COLUMNS.map((col) => {
          const cards = groupBy(col.status);
          return (
            <div
              key={col.status}
              className={styles.column}
              onDragOver={(e) => e.preventDefault()}
              onDrop={() => {
                if (dragId) {
                  updateStatus(dragId, col.status);
                  setDragId(null);
                }
              }}
            >
              <div className={styles.colHead}>
                <span>{col.label}</span>
                <span className={styles.count}>{cards.length}</span>
              </div>
              <div className={styles.colBody}>
                {cards.length === 0 ? (
                  <EmptyState title="—" />
                ) : (
                  cards.map((t) => (
                    <article
                      key={t.id}
                      className={styles.card}
                      draggable
                      onDragStart={() => setDragId(t.id)}
                      onDragEnd={() => setDragId(null)}
                    >
                      <div className={styles.cardBody}>{t.content}</div>
                      <div className={styles.cardMeta}>
                        <Badge tone={PRIORITY_TONE[t.priority as Priority]}>
                          {t.priority}
                        </Badge>
                        {t.due_date && (
                          <span className={styles.due}>{t.due_date}</span>
                        )}
                      </div>
                      {t.source_document_id && (
                        <Link
                          to={`/documents/${t.source_document_id}`}
                          className={styles.source}
                        >
                          {t.source_title || t.source_path || "source"}
                        </Link>
                      )}
                    </article>
                  ))
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
