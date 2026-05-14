import type { FieldSpec, FieldSpecType } from "../api/types";
import styles from "./FieldSpecEditor.module.css";

const FIELD_TYPES: FieldSpecType[] = [
  "string",
  "text",
  "int",
  "float",
  "bool",
  "date",
  "datetime",
  "enum",
  "url",
  "ref",
];

interface FieldSpecEditorProps {
  value: FieldSpec[];
  onChange: (next: FieldSpec[]) => void;
  /** Slugs eligible to be referenced by ``ref`` fields (populated from the
   * entity type registry by the parent). */
  refTypeSlugs?: string[];
}

export default function FieldSpecEditor({
  value,
  onChange,
  refTypeSlugs,
}: FieldSpecEditorProps) {
  function update(i: number, patch: Partial<FieldSpec>) {
    const next = [...value];
    next[i] = { ...next[i], ...patch };
    onChange(next);
  }
  function remove(i: number) {
    onChange(value.filter((_, idx) => idx !== i));
  }
  function move(i: number, delta: number) {
    const j = i + delta;
    if (j < 0 || j >= value.length) return;
    const next = [...value];
    [next[i], next[j]] = [next[j], next[i]];
    onChange(next);
  }
  function add() {
    const i = value.length + 1;
    onChange([
      ...value,
      {
        name: `field_${i}`,
        label: `Field ${i}`,
        type: "string",
        required: false,
      },
    ]);
  }

  return (
    <div className={styles.editor}>
      <div className={styles.rows}>
        {value.map((spec, i) => (
          <FieldRow
            key={i}
            spec={spec}
            refTypeSlugs={refTypeSlugs ?? []}
            onChange={(patch) => update(i, patch)}
            onRemove={() => remove(i)}
            onMoveUp={i > 0 ? () => move(i, -1) : undefined}
            onMoveDown={i < value.length - 1 ? () => move(i, +1) : undefined}
          />
        ))}
      </div>
      <button type="button" className={styles.add} onClick={add}>
        + Add field
      </button>
    </div>
  );
}

interface FieldRowProps {
  spec: FieldSpec;
  refTypeSlugs: string[];
  onChange: (patch: Partial<FieldSpec>) => void;
  onRemove: () => void;
  onMoveUp?: () => void;
  onMoveDown?: () => void;
}

function FieldRow({
  spec,
  refTypeSlugs,
  onChange,
  onRemove,
  onMoveUp,
  onMoveDown,
}: FieldRowProps) {
  return (
    <div className={styles.row}>
      <label>
        <div className={styles.label}>name</div>
        <input
          className={styles.input}
          value={spec.name}
          onChange={(e) => onChange({ name: e.target.value })}
          placeholder="snake_case"
        />
      </label>
      <label>
        <div className={styles.label}>label</div>
        <input
          className={styles.input}
          value={spec.label}
          onChange={(e) => onChange({ label: e.target.value })}
        />
      </label>
      <label>
        <div className={styles.label}>type</div>
        <select
          className={styles.select}
          value={spec.type}
          onChange={(e) =>
            onChange({
              type: e.target.value as FieldSpecType,
              // Clear type-specific extras so the saved schema stays clean.
              options: e.target.value === "enum" ? (spec.options ?? []) : undefined,
              ref_type_slug:
                e.target.value === "ref" ? spec.ref_type_slug : undefined,
            })
          }
        >
          {FIELD_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </label>
      <label className={styles.smallCheckbox}>
        <input
          type="checkbox"
          checked={Boolean(spec.required)}
          onChange={(e) => onChange({ required: e.target.checked })}
        />
        required
      </label>
      <div className={styles.move}>
        <button
          type="button"
          className={styles.moveBtn}
          onClick={onMoveUp}
          disabled={!onMoveUp}
        >
          ↑
        </button>
        <button
          type="button"
          className={styles.moveBtn}
          onClick={onMoveDown}
          disabled={!onMoveDown}
        >
          ↓
        </button>
        <button
          type="button"
          className={styles.remove}
          onClick={onRemove}
          title="Remove field"
        >
          ✕
        </button>
      </div>

      {spec.type === "enum" && (
        <label className={styles.full}>
          <div className={styles.label}>options (one per line)</div>
          <textarea
            className={styles.input}
            value={(spec.options ?? []).join("\n")}
            rows={3}
            onChange={(e) =>
              onChange({
                options: e.target.value
                  .split(/\r?\n/)
                  .map((s) => s.trim())
                  .filter(Boolean),
              })
            }
          />
        </label>
      )}

      {spec.type === "ref" && (
        <label className={styles.full}>
          <div className={styles.label}>ref_type_slug</div>
          <select
            className={styles.select}
            value={spec.ref_type_slug ?? ""}
            onChange={(e) =>
              onChange({ ref_type_slug: e.target.value || undefined })
            }
          >
            <option value="">(any entity)</option>
            {refTypeSlugs.map((slug) => (
              <option key={slug} value={slug}>
                {slug}
              </option>
            ))}
          </select>
        </label>
      )}

      {(spec.type === "enum" || spec.type === "string") && (
        <label className={styles.full}>
          <div className={styles.label}>default (optional)</div>
          <input
            className={styles.input}
            value={(spec.default as string | undefined) ?? ""}
            onChange={(e) =>
              onChange({ default: e.target.value || undefined })
            }
          />
        </label>
      )}
    </div>
  );
}
