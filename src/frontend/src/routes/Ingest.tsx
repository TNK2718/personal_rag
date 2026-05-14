import { useState } from "react";
import { api, ApiError } from "../api/client";
import type { IngestResponse } from "../api/types";
import PageHeader from "../components/PageHeader";
import Badge from "../components/Badge";
import styles from "./Ingest.module.css";

const STATUS_TONE = {
  created: "success",
  updated: "accent",
  skipped: "muted",
  error: "danger",
} as const;

export default function Ingest() {
  const [path, setPath] = useState("./data");
  const [glob, setGlob] = useState("**/*.md");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<IngestResponse | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (loading) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await api.post<IngestResponse>("/api/ingest", {
        path: path.trim() || undefined,
        glob: glob.trim() || undefined,
      });
      setResult(res);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <PageHeader
        title="Ingest"
        subtitle="ファイル/ディレクトリを取り込む"
      />

      <form className={styles.form} onSubmit={submit}>
        <label className={styles.field}>
          <span>Path</span>
          <input
            className={styles.input}
            value={path}
            onChange={(e) => setPath(e.target.value)}
            placeholder="./data"
          />
        </label>
        <label className={styles.field}>
          <span>Glob (directory only)</span>
          <input
            className={styles.input}
            value={glob}
            onChange={(e) => setGlob(e.target.value)}
            placeholder="**/*.md"
          />
        </label>
        <button type="submit" disabled={loading} className={styles.submit}>
          {loading ? "Ingesting…" : "Ingest"}
        </button>
      </form>

      {error && <div className={styles.error}>{error}</div>}

      {result && (
        <div>
          <div className={styles.summary}>
            <Badge tone="success">created {result.summary.created || 0}</Badge>
            <Badge tone="accent">updated {result.summary.updated || 0}</Badge>
            <Badge tone="muted">skipped {result.summary.skipped || 0}</Badge>
            <Badge tone="danger">errors {result.summary.error || 0}</Badge>
          </div>

          <table className={styles.table}>
            <thead>
              <tr>
                <th>Status</th>
                <th>Path</th>
                <th>Tags</th>
                <th>Entities by type</th>
                <th>Notes</th>
              </tr>
            </thead>
            <tbody>
              {result.reports.map((r, i) => (
                <tr key={i}>
                  <td>
                    <Badge tone={STATUS_TONE[r.status]}>{r.status}</Badge>
                  </td>
                  <td className={styles.path}>{r.source_path}</td>
                  <td>{r.tags_added || ""}</td>
                  <td>
                    {Object.entries(r.entities_added_by_type || {})
                      .map(([slug, n]) => `${slug}:${n}`)
                      .join(", ")}
                  </td>
                  <td className={styles.notes}>
                    {r.error && <div className={styles.errorText}>{r.error}</div>}
                    {r.extraction_error && (
                      <div className={styles.warnText}>
                        {r.extraction_error}
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
