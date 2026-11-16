import { useId } from "react";
import type { SpecError } from "./specSchema";
import styles from "./SpecEditor.module.css";

type Props = { label: string; text: string; onChange: (text: string) => void; errors: SpecError[]; rows?: number };

/** The JSON text of an assistant spec with its schema errors listed below. */
export function SpecEditor({ label, text, onChange, errors, rows = 18 }: Props) {
  const id = useId();
  return (
    <div className={styles.editor}>
      <label htmlFor={id} className={styles.label}>
        {label}
      </label>
      <textarea
        id={id}
        className={styles.text}
        value={text}
        onChange={(e) => onChange(e.target.value)}
        rows={rows}
        spellCheck={false}
        aria-invalid={errors.length > 0}
        aria-describedby={errors.length ? `${id}-errors` : undefined}
      />
      {errors.length > 0 && (
        <ul id={`${id}-errors`} className={styles.errors} aria-label="Spec errors">
          {errors.map((e, i) => (
            <li key={i}>
              {e.path && <><code>{e.path}</code> </>}
              {e.message}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
