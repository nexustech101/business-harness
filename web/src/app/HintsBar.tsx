import { AlertTriangle, Info, Lightbulb, X } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import type { Hint } from "../api/types";
import { useAgentic } from "./agentic";
import styles from "./HintsBar.module.css";

const ICONS: Record<Hint["tone"], typeof Info> = { info: Info, suggestion: Lightbulb, warning: AlertTriangle };

/** The hints for this screen (see agentic.tsx): the most relevant one, the rest behind "+n more"; a dismissed hint
 * stays dismissed. */
export function HintsBar() {
  const { hints, dismiss, track } = useAgentic();
  const [expanded, setExpanded] = useState(false);
  if (!hints.length) return null;
  const more = hints.length - 1;
  return (
    <section className={styles.bar} aria-label="Hints">
      {(expanded ? hints : hints.slice(0, 1)).map((hint, i) => {
        const Icon = ICONS[hint.tone];
        return (
          <div key={hint.id} className={`${styles.hint} ${styles[hint.tone]}`} data-hint={hint.id}>
            <Icon className={styles.icon} aria-hidden />
            <p className={styles.text}>
              <strong>{hint.title}</strong> <span>{hint.body}</span>
            </p>
            {hint.action && (
              <Link to={hint.action.href} className={styles.action} onClick={() => track("action", `hint:${hint.id}`, { href: hint.action?.href })}>
                {hint.action.label}
              </Link>
            )}
            {i === 0 && more > 0 && (
              <button type="button" className={styles.more} aria-expanded={expanded} onClick={() => setExpanded((e) => !e)}>
                {expanded ? "Show less" : `+${more} more`}
              </button>
            )}
            <button type="button" className={styles.dismiss} aria-label={`Dismiss hint: ${hint.title}`} title="Dismiss" onClick={() => dismiss(hint.id)}>
              <X aria-hidden />
            </button>
          </div>
        );
      })}
    </section>
  );
}
