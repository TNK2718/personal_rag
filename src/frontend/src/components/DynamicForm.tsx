import { useState } from "react";
import useSWR from "swr";
import { fetcher } from "../api/client";
import type { EntityRef, FieldSpec, FieldSpecType } from "../api/types";
import styles from "./DynamicForm.module.css";

export type DynamicFormValues = Record<string, unknown>;

interface DynamicFormProps {
  fields: FieldSpec[];
  /** Optional preloaded values keyed by field name. */
  initial?: DynamicFormValues;
  /** Built-in inputs for entity-level metadata. The form renders these as a
   * header section so the dynamic fields below stay focused on the type
   * schema. Optional — Settings doesn't need them. */
  headerFields?: HeaderFieldSpec[];
  submitLabel?: string;
  onSubmit: (values: DynamicFormValues) => void | Promise<void>;
  onCancel?: () => void;
  submitting?: boolean;
}

export interface HeaderFieldSpec {
  name: string;
  label: string;
  type: "string" | "text";
  required?: boolean;
  placeholder?: string;
}

const TEXT_WIDGET_TYPES = new Set<FieldSpecType>(["text"]);

export default function DynamicForm({
  fields,
  initial,
  headerFields,
  submitLabel = "Save",
  onSubmit,
  onCancel,
  submitting = false,
}: DynamicFormProps) {
  const [values, setValues] = useState<DynamicFormValues>(() =>
    seedValues(fields, initial ?? {}, headerFields),
  );
  const [errors, setErrors] = useState<Record<string, string>>({});

  function setField(name: string, value: unknown) {
    setValues((prev) => ({ ...prev, [name]: value }));
    if (errors[name]) {
      setErrors((prev) => {
        const next = { ...prev };
        delete next[name];
        return next;
      });
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const v = { ...values };
    const errs: Record<string, string> = {};

    for (const h of headerFields ?? []) {
      const value = (v[h.name] ?? "") as string;
      if (h.required && !value.trim()) {
        errs[h.name] = "必須項目です";
      }
    }
    for (const f of fields) {
      if (f.required && isEmpty(v[f.name])) {
        errs[f.name] = "必須項目です";
      }
    }
    if (Object.keys(errs).length > 0) {
      setErrors(errs);
      return;
    }

    await onSubmit(v);
  }

  return (
    <form className={styles.form} onSubmit={handleSubmit}>
      {(headerFields ?? []).map((h) => (
        <HeaderField
          key={h.name}
          spec={h}
          value={(values[h.name] as string) ?? ""}
          error={errors[h.name]}
          onChange={(v) => setField(h.name, v)}
        />
      ))}

      {fields.map((f) => (
        <DynamicField
          key={f.name}
          spec={f}
          value={values[f.name]}
          error={errors[f.name]}
          onChange={(v) => setField(f.name, v)}
        />
      ))}

      <div className={styles.actions}>
        <button
          type="submit"
          className={styles.primary}
          disabled={submitting}
        >
          {submitting ? "..." : submitLabel}
        </button>
        {onCancel && (
          <button
            type="button"
            className={styles.secondary}
            onClick={onCancel}
            disabled={submitting}
          >
            Cancel
          </button>
        )}
      </div>
    </form>
  );
}

// ---------------------------------------------------------------------------
// Per-field widgets
// ---------------------------------------------------------------------------
function HeaderField({
  spec,
  value,
  error,
  onChange,
}: {
  spec: HeaderFieldSpec;
  value: string;
  error?: string;
  onChange: (v: string) => void;
}) {
  return (
    <label className={styles.field}>
      <span className={styles.label}>
        {spec.label}
        <span className={styles.fieldName}>{spec.name}</span>
        {spec.required && <span className={styles.required}>required</span>}
      </span>
      {spec.type === "text" ? (
        <textarea
          className={styles.textarea}
          value={value}
          placeholder={spec.placeholder}
          onChange={(e) => onChange(e.target.value)}
        />
      ) : (
        <input
          className={styles.input}
          value={value}
          placeholder={spec.placeholder}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
      {error && <span className={styles.error}>{error}</span>}
    </label>
  );
}

function DynamicField({
  spec,
  value,
  error,
  onChange,
}: {
  spec: FieldSpec;
  value: unknown;
  error?: string;
  onChange: (v: unknown) => void;
}) {
  return (
    <label className={styles.field}>
      <span className={styles.label}>
        {spec.label}
        <span className={styles.fieldName}>{spec.name}</span>
        {spec.required && <span className={styles.required}>required</span>}
      </span>
      <Widget spec={spec} value={value} onChange={onChange} />
      {error && <span className={styles.error}>{error}</span>}
    </label>
  );
}

function Widget({
  spec,
  value,
  onChange,
}: {
  spec: FieldSpec;
  value: unknown;
  onChange: (v: unknown) => void;
}) {
  if (spec.type === "enum") {
    return (
      <select
        className={styles.select}
        value={(value as string) ?? ""}
        onChange={(e) => onChange(e.target.value || null)}
      >
        {!spec.required && <option value="">（未設定）</option>}
        {(spec.options ?? []).map((opt) => (
          <option key={opt} value={opt}>
            {opt}
          </option>
        ))}
      </select>
    );
  }
  if (spec.type === "bool") {
    return (
      <span className={styles.checkbox}>
        <input
          type="checkbox"
          checked={Boolean(value)}
          onChange={(e) => onChange(e.target.checked)}
        />
        <span>{spec.label}</span>
      </span>
    );
  }
  if (TEXT_WIDGET_TYPES.has(spec.type) || spec.ui_widget === "textarea") {
    return (
      <textarea
        className={styles.textarea}
        value={(value as string) ?? ""}
        onChange={(e) => onChange(e.target.value || null)}
      />
    );
  }
  if (spec.type === "ref") {
    return (
      <RefWidget spec={spec} value={value as string | null} onChange={onChange} />
    );
  }

  const inputType = inputTypeFor(spec.type);
  return (
    <input
      className={styles.input}
      type={inputType}
      value={
        value === null || value === undefined
          ? ""
          : typeof value === "boolean"
            ? String(value)
            : (value as string | number).toString()
      }
      step={spec.type === "float" ? "any" : undefined}
      onChange={(e) => onChange(parseInputValue(spec.type, e.target.value))}
    />
  );
}

function RefWidget({
  spec,
  value,
  onChange,
}: {
  spec: FieldSpec;
  value: string | null;
  onChange: (v: string | null) => void;
}) {
  // Stage 4 keeps refs simple: a select populated from `/api/entities?type_slug=...`.
  // Stage 5+ could swap in a typeahead.
  const url = spec.ref_type_slug
    ? `/api/entities?type_slug=${encodeURIComponent(spec.ref_type_slug)}&top_k=200`
    : null;
  const { data } = useSWR<EntityRef[]>(url, fetcher);

  return (
    <select
      className={styles.select}
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value || null)}
    >
      <option value="">（未設定）</option>
      {(data ?? []).map((e) => (
        <option key={e.id} value={e.id}>
          {e.canonical_name}
        </option>
      ))}
    </select>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function seedValues(
  fields: FieldSpec[],
  initial: DynamicFormValues,
  headerFields?: HeaderFieldSpec[],
): DynamicFormValues {
  const seeded: DynamicFormValues = { ...initial };
  for (const h of headerFields ?? []) {
    if (seeded[h.name] === undefined) {
      seeded[h.name] = "";
    }
  }
  for (const f of fields) {
    if (seeded[f.name] !== undefined) continue;
    if (f.default !== undefined && f.default !== null) {
      seeded[f.name] = f.default;
    } else if (f.type === "bool") {
      seeded[f.name] = false;
    } else {
      seeded[f.name] = null;
    }
  }
  return seeded;
}

function inputTypeFor(t: FieldSpecType): string {
  switch (t) {
    case "int":
    case "float":
      return "number";
    case "date":
      return "date";
    case "datetime":
      return "datetime-local";
    case "url":
      return "url";
    default:
      return "text";
  }
}

function parseInputValue(t: FieldSpecType, raw: string): unknown {
  if (raw === "") return null;
  if (t === "int") {
    const n = Number(raw);
    return Number.isFinite(n) ? Math.trunc(n) : raw;
  }
  if (t === "float") {
    const n = Number(raw);
    return Number.isFinite(n) ? n : raw;
  }
  if (t === "datetime") {
    // datetime-local emits "YYYY-MM-DDTHH:MM" — append seconds + Z when missing
    // so the backend's ISO parser accepts it.
    if (raw.length === 16) return `${raw}:00Z`;
    return raw;
  }
  return raw;
}

function isEmpty(v: unknown): boolean {
  if (v === null || v === undefined) return true;
  if (typeof v === "string" && v.trim() === "") return true;
  return false;
}

/**
 * Pack a DynamicForm submission into the shape ``/api/entities`` POST expects.
 * Caller splits header fields (canonical_name, description) from dynamic fields.
 */
export function pickFieldValues(
  values: DynamicFormValues,
  fields: FieldSpec[],
): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const f of fields) {
    const v = values[f.name];
    if (v === undefined || v === null) {
      if (f.required) {
        // Required value left blank — pass through; the server will surface a
        // 400 with a useful message. We do not silently drop required nulls.
        out[f.name] = v ?? "";
      }
      continue;
    }
    out[f.name] = v;
  }
  return out;
}
