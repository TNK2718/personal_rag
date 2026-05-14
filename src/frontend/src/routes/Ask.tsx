import { useState } from "react";
import { marked } from "marked";
import { Link } from "react-router-dom";
import { api, ApiError } from "../api/client";
import type { AskResponse } from "../api/types";
import PageHeader from "../components/PageHeader";
import styles from "./Ask.module.css";

export default function Ask() {
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AskResponse | null>(null);
  const [showTrace, setShowTrace] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const q = question.trim();
    if (!q || loading) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await api.post<AskResponse>("/api/ask", { question: q });
      setResult(res);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <PageHeader title="Ask" subtitle="自然言語でエージェントに質問" />

      <form className={styles.form} onSubmit={submit}>
        <textarea
          className={styles.textarea}
          rows={4}
          placeholder="質問を入力してください (例: 先週の会議で決まったTODOは?)"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
        />
        <div className={styles.formActions}>
          <button type="submit" className={styles.submit} disabled={loading}>
            {loading ? "Asking…" : "Ask"}
          </button>
        </div>
      </form>

      {error && <div className={styles.error}>{error}</div>}

      {result && (
        <div className={styles.result}>
          <section className={styles.answerSection}>
            <h2 className={styles.h2}>Answer</h2>
            {result.exhausted && (
              <div className={styles.warning}>
                エージェントが反復上限に達しました ({result.iterations})
              </div>
            )}
            <div
              className={styles.answer}
              dangerouslySetInnerHTML={{
                __html: marked.parse(result.answer || "(no answer)") as string,
              }}
            />
          </section>

          {result.citations.length > 0 && (
            <section>
              <h2 className={styles.h2}>Citations</h2>
              <ul className={styles.citations}>
                {result.citations.map((c) => (
                  <li key={c.document_id}>
                    <Link to={`/documents/${c.document_id}`}>
                      {c.title || c.source_path || c.document_id}
                    </Link>
                    {c.snippet && (
                      <div className={styles.snippet}>{c.snippet}</div>
                    )}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {result.trace.length > 0 && (
            <section>
              <button
                className={styles.traceToggle}
                onClick={() => setShowTrace((v) => !v)}
              >
                {showTrace ? "▼" : "▶"} Trace ({result.trace.length} steps)
              </button>
              {showTrace && (
                <ol className={styles.trace}>
                  {result.trace.map((t, i) => (
                    <li key={i}>
                      <div className={styles.traceHeader}>
                        <span className={styles.traceTool}>{t.tool}</span>
                        <span className={styles.traceIter}>
                          step {t.iteration}
                        </span>
                      </div>
                      <pre className={styles.traceArgs}>
                        {JSON.stringify(t.arguments, null, 2)}
                      </pre>
                      {t.error ? (
                        <div className={styles.error}>{t.error}</div>
                      ) : (
                        <pre className={styles.tracePreview}>
                          {t.result_preview}
                        </pre>
                      )}
                    </li>
                  ))}
                </ol>
              )}
            </section>
          )}
        </div>
      )}
    </div>
  );
}
