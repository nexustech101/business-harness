import { Save } from "lucide-react";
import { errorMessage } from "../../api/client";
import type { AssistantInfo, WriteMode } from "../../api/types";
import { Alert } from "../../components/Alert";
import { Button } from "../../components/Button";
import { Card } from "../../components/Card";
import { Select } from "../../components/Field";
import { Segmented } from "../../components/Segmented";
import { Skeleton } from "../../components/Skeleton";
import { plural } from "../../lib/format";
import { usePolicyEditor, type ToolMode } from "./hooks";
import styles from "./AssistantDetailPage.module.css";

const MODES: { value: WriteMode; label: string }[] = [
  { value: "auto", label: "Auto" },
  { value: "ask", label: "Ask" },
  { value: "deny", label: "Deny" },
];

type Props = { assistant: AssistantInfo; onSave: (policy: { default: WriteMode; tools: Record<string, WriteMode> }) => void; saving: boolean };

/** The write policy: default mode, and a mode per write tool of its connectors (GET /v1/connectors/{id}/tools). */
export function PolicyEditor({ assistant, onSave, saving }: Props) {
  const editor = usePolicyEditor(assistant);
  return (
    <Card
      title="Write policy"
      actions={
        <Button size="sm" variant="primary" icon={<Save />} loading={saving} disabled={!editor.dirty} onClick={() => onSave(editor.policy)}>
          Save policy
        </Button>
      }
    >
      <div className={styles.policy}>
        <div className={styles.policyRow}>
          <div>
            <p className={styles.policyTitle}>Default for write tools</p>
            <p className="muted">Auto runs, Ask queues an approval, Deny refuses. Read-only tools always run.</p>
          </div>
          <Segmented label="Default for write tools" value={editor.mode} onChange={editor.setMode} options={MODES} />
        </div>
        {editor.errors.length > 0 && <Alert tone="warning" title="Some connector tools could not be listed">{errorMessage(editor.errors[0])}</Alert>}
        {editor.pending ? (
          <Skeleton height={60} />
        ) : editor.rows.length === 0 ? (
          <p className="muted">
            {(assistant.connectors ?? []).length ? "Its connectors offer no write tools." : "No connectors in its spec: add connector ids to set a mode per tool."}
          </p>
        ) : (
          <ul className={styles.toolModes} aria-label="Per-tool modes">
            {editor.rows.map(({ key, description }) => (
              <li key={key}>
                <span className={styles.toolText}>
                  <code>{key}</code>
                  <span className="muted truncate">{description ?? "No longer offered by its connector"}</span>
                </span>
                <Select
                  aria-label={`Mode for ${key}`}
                  value={editor.overrides[key] ?? ""}
                  onChange={(e) => editor.setTool(key, e.target.value as ToolMode)}
                >
                  <option value="">Default ({editor.mode})</option>
                  {MODES.map((m) => (
                    <option key={m.value} value={m.value}>
                      {m.label}
                    </option>
                  ))}
                </Select>
              </li>
            ))}
          </ul>
        )}
        {editor.readOnly > 0 && <p className="muted">{plural(editor.readOnly, "read-only tool")} always run.</p>}
      </div>
    </Card>
  );
}
