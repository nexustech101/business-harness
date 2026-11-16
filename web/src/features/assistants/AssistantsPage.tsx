import { Bot, FileJson, Plus } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { useAssistants } from "../../api/assistants";
import { errorMessage } from "../../api/client";
import { useScreenState } from "../../app/agentic";
import { Alert } from "../../components/Alert";
import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Card } from "../../components/Card";
import { EmptyState } from "../../components/EmptyState";
import { PageHeader } from "../../components/PageHeader";
import { Skeleton } from "../../components/Skeleton";
import table from "../../components/Table.module.css";
import { ASSISTANT_STATUS as STATUS } from "../../lib/status";
import { useCreateAssistantFlow } from "./hooks";
import { SpecEditor } from "./SpecEditor";
import styles from "./AssistantsPage.module.css";

/** `/assistants`: every assistant with its status, and "New assistant" (a JSON spec checked against the schema). */
export function AssistantsPage() {
  const list = useAssistants();
  const navigate = useNavigate();
  const [creating, setCreating] = useState(false);
  useScreenState({ detail: { assistants: list.data?.length ?? null, creating } });
  return (
    <div className={styles.page}>
      <PageHeader
        title="Assistants"
        description="Role assistants that act through your connectors. Each one is a JSON spec; the partner drafts them, you activate them."
        actions={!creating && <Button variant="primary" icon={<Plus />} onClick={() => setCreating(true)}>New assistant</Button>}
      />
      {creating && <CreateAssistant onCancel={() => setCreating(false)} />}
      <Card flush>
        {list.isError ? (
          <div className={styles.pad}>
            <Alert title="Assistants could not be loaded">{errorMessage(list.error)}</Alert>
          </div>
        ) : !list.data ? (
          <div className={styles.pad}>
            <Skeleton height={120} />
          </div>
        ) : list.data.length === 0 ? (
          <EmptyState icon={<Bot />} title="No assistants yet">
            Tell the partner about your business and it drafts assistants for the roles it finds, or write a spec yourself.
          </EmptyState>
        ) : (
          <div className={table.wrap}>
            <table className={table.table}>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Role</th>
                  <th>Department</th>
                  <th>Status</th>
                  <th className={table.num}>Connectors</th>
                  <th>Created by</th>
                </tr>
              </thead>
              <tbody>
                {list.data.map((a) => (
                  <tr key={a.id} className={table.link} onClick={() => navigate(`/assistants/${a.id}`)}>
                    <td>
                      <Link to={`/assistants/${a.id}`} onClick={(e) => e.stopPropagation()} className={styles.name}>
                        {a.name}
                      </Link>
                    </td>
                    <td className={styles.role}>{a.role}</td>
                    <td className={a.department ? undefined : "muted"}>{a.department ?? "—"}</td>
                    <td>
                      <Badge tone={STATUS[a.status].tone} dot>
                        {STATUS[a.status].label}
                      </Badge>
                    </td>
                    <td className={table.num}>{a.connectors?.length ?? 0}</td>
                    <td className="muted">{a.created_by === "partner" ? "Partner" : "You"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}

function CreateAssistant({ onCancel }: { onCancel: () => void }) {
  const { editor, submit, creating, error, applyTemplate } = useCreateAssistantFlow();
  return (
    <Card
      title="New assistant"
      actions={
        <Button size="sm" icon={<FileJson />} onClick={applyTemplate}>
          Use template
        </Button>
      }
    >
      <div className={styles.create}>
        {editor.schemaError && <Alert title="The spec schema could not be loaded">{errorMessage(editor.schemaError)}</Alert>}
        {error && <Alert title="Not created">{error}</Alert>}
        <SpecEditor label="Assistant spec (JSON)" text={editor.text} onChange={editor.setText} errors={editor.errors} />
        <div className={styles.createActions}>
          <span className="muted">It starts as a draft; activate it on its page.</span>
          <Button onClick={onCancel}>Cancel</Button>
          <Button variant="primary" loading={creating} disabled={!editor.spec} onClick={submit}>
            Create assistant
          </Button>
        </div>
      </div>
    </Card>
  );
}
