import { Play } from "lucide-react";
import { Link } from "react-router";
import type { AssistantInfo } from "../../api/types";
import { Alert } from "../../components/Alert";
import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Card } from "../../components/Card";
import { Textarea } from "../../components/Field";
import { TOOL_OUTCOME as OUTCOMES } from "../../lib/status";
import { AssistantMessage } from "../assistant/Message";
import { useRunPanel } from "./hooks";
import styles from "./AssistantDetailPage.module.css";

/** POST /v1/assistants/{id}/run with one task: the answer, then every tool call with its outcome. */
export function RunPanel({ assistant }: { assistant: AssistantInfo }) {
  const active = assistant.status === "active";
  const { task, setTask, submit, running, result, error } = useRunPanel(assistant.id, active);
  return (
    <Card title="Run a task">
      <div className={styles.run}>
        <Textarea
          aria-label="Task"
          value={task}
          onChange={(e) => setTask(e.target.value)}
          rows={3}
          placeholder={`What should ${assistant.name} do?`}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit();
          }}
        />
        <div className={styles.runActions}>
          <span className="muted">{active ? "Ctrl+Enter runs it." : "Activate the assistant to run it."}</span>
          <Button variant="primary" icon={<Play />} loading={running} disabled={!active || !task.trim()} onClick={submit}>
            Run
          </Button>
        </div>
        {error && <Alert title="The run failed">{error}</Alert>}
        {result && (
          <div className={styles.result} aria-label="Run result">
            <AssistantMessage
              last
              turn={{ role: "assistant", content: result.message.content, reply: { message: result.message, sources: [], tool_calls: [], model: result.model, usage: result.usage } }}
            />
            {result.tool_runs.length > 0 && (
              <ol className={styles.toolRuns} aria-label="Tool calls">
                {result.tool_runs.map((run, i) => (
                  <li key={i} data-outcome={run.outcome}>
                    <div className={styles.toolRunHead}>
                      <code>{run.connector_id ? `${run.connector_id}/${run.tool}` : run.tool}</code>
                      <Badge>{run.read_only ? "Read" : "Write"}</Badge>
                      <Badge tone={OUTCOMES[run.outcome].tone}>{OUTCOMES[run.outcome].label}</Badge>
                      {run.outcome === "pending_approval" && <Link to="/approvals">Review in approvals</Link>}
                    </div>
                    <details>
                      <summary>Arguments and result</summary>
                      <pre>{JSON.stringify(run.arguments, null, 2)}</pre>
                      {run.result && <pre>{run.result}</pre>}
                    </details>
                  </li>
                ))}
              </ol>
            )}
          </div>
        )}
      </div>
    </Card>
  );
}
