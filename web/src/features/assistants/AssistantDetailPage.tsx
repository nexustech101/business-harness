import { ArrowLeft, Bot, Save, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router";
import { useAssistantContext } from "../../api/assistants";
import { ApiError, errorMessage } from "../../api/client";
import type { AssistantInfo, AssistantStatus } from "../../api/types";
import { useScreenState } from "../../app/agentic";
import { Alert } from "../../components/Alert";
import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Card } from "../../components/Card";
import { Dialog } from "../../components/Dialog";
import { EmptyState } from "../../components/EmptyState";
import { Segmented } from "../../components/Segmented";
import { Skeleton } from "../../components/Skeleton";
import { formatCount } from "../../lib/format";
import { ASSISTANT_STATUS as STATUS } from "../../lib/status";
import { specOf, toJson, useAssistantView, useSpecEditor } from "./hooks";
import { PolicyEditor } from "./PolicyEditor";
import { RunPanel } from "./RunPanel";
import { SpecEditor } from "./SpecEditor";
import styles from "./AssistantDetailPage.module.css";

const STATUSES: AssistantStatus[] = ["draft", "active", "paused"];

/** `/assistants/:id`: status, run a task, what it sees, its write policy and its JSON spec. */
export function AssistantDetailPage() {
  const { id = "" } = useParams();
  const view = useAssistantView(id);
  const { assistant } = view;
  const [confirming, setConfirming] = useState(false);
  useScreenState({ entity: assistant.data ? { kind: "assistant", id, title: assistant.data.name } : null, detail: { status: assistant.data?.status ?? null } });

  if (assistant.isError) {
    const missing = assistant.error instanceof ApiError && assistant.error.status === 404;
    return missing ? (
      <EmptyState icon={<Bot />} title="Assistant not found" action={<Link to="/assistants">Back to assistants</Link>}>
        It was deleted, or it belongs to another API key.
      </EmptyState>
    ) : (
      <Alert title="The assistant could not be loaded">{errorMessage(assistant.error)}</Alert>
    );
  }
  if (!assistant.data) return <Skeleton height={240} />;
  const a = assistant.data;

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <div className={styles.headText}>
          <Link to="/assistants" className={styles.back}>
            <ArrowLeft aria-hidden /> Assistants
          </Link>
          <div className={styles.titleLine}>
            <h1 className="truncate">{a.name}</h1>
            <Badge tone={STATUS[a.status].tone} dot>
              {STATUS[a.status].label}
            </Badge>
          </div>
          <p className={styles.role}>
            {a.role}
            {a.department && <span className="muted"> · {a.department}</span>}
            <span className="muted"> · created by {a.created_by === "partner" ? "the partner" : "you"}</span>
          </p>
        </div>
        <div className={styles.headActions}>
          <Segmented
            label="Status"
            value={a.status}
            onChange={view.setStatus}
            options={STATUSES.map((s) => ({ value: s, label: STATUS[s].label }))}
          />
          <Button variant="ghost" icon={<Trash2 />} aria-label={`Delete ${a.name}`} title="Delete" onClick={() => setConfirming(true)} />
        </div>
      </header>
      <div className={styles.grid}>
        <div className={styles.column}>
          <RunPanel assistant={a} />
          <ContextCard id={a.id} />
        </div>
        <div className={styles.column}>
          <PolicyEditor key={`policy-${JSON.stringify(a.policy)}`} assistant={a} onSave={(policy) => view.save({ ...specOf(a), policy }, "Policy")} saving={view.saving} />
          <SpecCard key={`spec-${JSON.stringify(specOf(a))}`} assistant={a} onSave={view.save} saving={view.saving} />
        </div>
      </div>
      <Dialog
        open={confirming}
        onClose={() => setConfirming(false)}
        title="Delete assistant?"
        footer={
          <>
            <Button onClick={() => setConfirming(false)}>Cancel</Button>
            <Button variant="danger" loading={view.deleting} onClick={view.destroy}>
              Delete
            </Button>
          </>
        }
      >
        <p>
          <strong>{a.name}</strong> stops working at once. Its notes stay on the board.
        </p>
      </Dialog>
    </div>
  );
}

function SpecCard({ assistant, onSave, saving }: { assistant: AssistantInfo; onSave: ReturnType<typeof useAssistantView>["save"]; saving: boolean }) {
  const saved = toJson(specOf(assistant));
  const editor = useSpecEditor(saved);
  return (
    <Card
      title="Spec"
      actions={
        <Button size="sm" variant="primary" icon={<Save />} loading={saving} disabled={!editor.spec || editor.text === saved} onClick={() => editor.spec && onSave(editor.spec)}>
          Save spec
        </Button>
      }
    >
      <SpecEditor label="Assistant spec (JSON)" text={editor.text} onChange={editor.setText} errors={editor.errors} rows={22} />
    </Card>
  );
}

/** GET /v1/assistants/{id}/context: the layers its model receives, in order, and the tools offered. */
function ContextCard({ id }: { id: string }) {
  const context = useAssistantContext(id);
  return (
    <Card title="What it sees" actions={context.data && <span className="muted num">{formatCount(context.data.chars)} characters</span>}>
      {context.isError ? (
        <Alert>{errorMessage(context.error)}</Alert>
      ) : !context.data ? (
        <Skeleton height={100} />
      ) : (
        <div className={styles.context}>
          {context.data.layers.map((layer) => (
            <details key={layer.name} className={styles.layer}>
              <summary>
                <span className={styles.layerName}>{layer.name}</span>
                <span className="muted num">{formatCount(layer.text.length)} chars</span>
              </summary>
              <pre>{layer.text}</pre>
            </details>
          ))}
          <div className={styles.tools} aria-label="Tools offered">
            {context.data.tools.length ? context.data.tools.map((t) => <code key={t}>{t}</code>) : <span className="muted">No tools</span>}
          </div>
        </div>
      )}
    </Card>
  );
}
