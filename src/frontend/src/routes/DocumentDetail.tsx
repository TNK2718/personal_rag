import useSWR from "swr";
import { marked } from "marked";
import { Link, useParams } from "react-router-dom";
import { fetcher } from "../api/client";
import type { Citation, DocumentDetail as DocDetail } from "../api/types";
import PageHeader from "../components/PageHeader";
import Badge from "../components/Badge";
import EmptyState from "../components/EmptyState";
import styles from "./DocumentDetail.module.css";

export default function DocumentDetail() {
  const { id } = useParams();
  const { data, error, isLoading } = useSWR<DocDetail>(
    id ? `/api/documents/${id}` : null,
    fetcher,
  );
  const { data: similar } = useSWR<Citation[]>(
    id ? `/api/documents/${id}/similar?top_k=5` : null,
    fetcher,
  );

  if (isLoading) return <div className={styles.muted}>Loading…</div>;
  if (error) return <div className={styles.error}>{String(error)}</div>;
  if (!data) return <EmptyState title="Not found" />;

  return (
    <div>
      <PageHeader
        title={data.title || data.source_path || data.id}
        subtitle={data.source_path || ""}
        actions={
          <Link to="/documents" className={styles.back}>
            ← Back
          </Link>
        }
      />

      <div className={styles.metaRow}>
        {data.doc_type && <Badge tone="accent">{data.doc_type}</Badge>}
        {data.language && <Badge>{data.language}</Badge>}
        {data.created_at && (
          <span className={styles.muted}>{data.created_at}</span>
        )}
      </div>

      <div className={styles.layout}>
        <aside className={styles.side}>
          <Section title="Summary">
            <p className={styles.summary}>{data.summary || "—"}</p>
          </Section>

          <Section title={`Entities (${data.entities.length})`}>
            {data.entities.length === 0 ? (
              <div className={styles.muted}>—</div>
            ) : (
              <ul className={styles.list}>
                {data.entities.map((e) => (
                  <li key={e.id}>
                    <span>{e.canonical_name}</span>
                    <Badge tone="muted">{e.type_slug}</Badge>
                  </li>
                ))}
              </ul>
            )}
          </Section>

          <Section title={`Tags (${data.tags.length})`}>
            {data.tags.length === 0 ? (
              <div className={styles.muted}>—</div>
            ) : (
              <div className={styles.tagChips}>
                {data.tags.map((t) => (
                  <Badge key={t.id}>{t.canonical_name}</Badge>
                ))}
              </div>
            )}
          </Section>

          {similar && similar.length > 0 && (
            <Section title="Similar">
              <ul className={styles.list}>
                {similar.map((c) => (
                  <li key={c.document_id}>
                    <Link to={`/documents/${c.document_id}`}>
                      {c.title || c.source_path || c.document_id}
                    </Link>
                  </li>
                ))}
              </ul>
            </Section>
          )}
        </aside>

        <article className={styles.content}>
          <h2 className={styles.contentTitle}>Content</h2>
          <div
            className={styles.markdown}
            dangerouslySetInnerHTML={{
              __html: marked.parse(data.raw_text || "") as string,
            }}
          />
        </article>
      </div>
    </div>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className={styles.section}>
      <h3 className={styles.sectionTitle}>{title}</h3>
      {children}
    </section>
  );
}
