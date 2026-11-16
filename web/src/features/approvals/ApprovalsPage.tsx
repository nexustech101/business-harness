import { Check, CheckCheck, ShieldCheck, X } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { errorMessage } from "../../api/client";
import type { Approval } from "../../api/types";
import { Alert } from "../../components/Alert";
import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Card } from "../../components/Card";
import { EmptyState } from "../../components/EmptyState";
import { Input } from "../../components/Field";
import { PageHeader } from "../../components/PageHeader";
import { Segmented } from "../../components/Segmented";
import { Skeleton } from "../../components/Skeleton";
import { formatDateTime, timeAgo } from "../../lib/format";
import { APPROVAL_STATUS } from "../../lib/status";
import { FILTERS, useApprovalsView, type Filter } from "./hooks";
import styles from "./ApprovalsPage.module.css";

const LABELS: Record<Filter, string> = { pending: "Pending", all: "All", executing: "Running", executed: "Executed", rejected: "Rejected", failed: "Failed" };

/** `/approvals?status=`: write actions the assistants asked to take, pending first. */
export function ApprovalsPage() {
  const { filter, setFilter, list, approvals, decide, deciding } = useApprovalsView();
  return (
    <div className={styles.page}>
      <PageHeader
        title="Approvals"
        description="Write actions your assistants asked to take. Approving runs the call now; reads never need approval."
        actions={<Segmented label="Show" value={filter} onChange={setFilter} options={FILTERS.map((f) => ({ value: f, label: LABELS[f] }))} />}
      />
      {list.isError ? (
        <Alert title="Approvals could not be loaded">{errorMessage(list.error)}</Alert>
      ) : !list.data ? (
        <Skeleton height={160} />
      ) : approvals.length === 0 ? (
        <Card>
          <EmptyState icon={<ShieldCheck />} title={filter === "pending" ? "Nothing waiting for you" : "No approvals"}>
            When an assistant's policy says "ask", its write actions wait here.
          </EmptyState>
        </Card>
      ) : (
        <ul className={styles.list} aria-label="Approvals">
          {approvals.map((a) => (
            <ApprovalCard key={a.id} approval={a} busy={deciding === a.id} onDecide={(approve, always, note) => decide(a, approve, always, note)} />
          ))}
        </ul>
      )}
    </div>
  );
}

type CardProps = { approval: Approval; busy: boolean; onDecide: (approve: boolean, always: boolean, note: string) => void };

function ApprovalCard({ approval: a, busy, onDecide }: CardProps) {
  const [note, setNote] = useState("");
  const pending = a.status === "pending";
  return (
    <li className={styles.card} aria-label={`${a.assistant_name}: ${a.tool}`} data-status={a.status}>
      <header className={styles.head}>
        <Link to={`/assistants/${a.assistant_id}`} className={styles.assistant}>
          {a.assistant_name}
        </Link>
        <code className={styles.tool}>
          {a.connector_id}/{a.tool}
        </code>
        <span className={styles.when} title={formatDateTime(a.created_at)}>
          {timeAgo(a.created_at)}
        </span>
        <Badge tone={APPROVAL_STATUS[a.status].tone}>{APPROVAL_STATUS[a.status].label}</Badge>
      </header>
      {a.reason && <blockquote className={styles.reason}>{a.reason}</blockquote>}
      <pre className={styles.args} aria-label="Arguments">{JSON.stringify(a.arguments, null, 2)}</pre>
      {pending ? (
        <footer className={styles.actions}>
          <Input value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} placeholder="Note (optional)" aria-label={`Note on ${a.tool}`} />
          <Button icon={<X />} disabled={busy} onClick={() => onDecide(false, false, note)}>
            Reject
          </Button>
          <Button icon={<CheckCheck />} disabled={busy} title={`Approve, and let ${a.assistant_name} run ${a.tool} without asking from now on`} onClick={() => onDecide(true, true, note)}>
            Always allow
          </Button>
          <Button variant="primary" icon={<Check />} loading={busy} onClick={() => onDecide(true, false, note)}>
            Approve
          </Button>
        </footer>
      ) : (
        <footer className={styles.decided}>
          <p className="muted">
            {a.status === "rejected" ? "Rejected" : "Approved"}
            {a.decided_by && ` by ${a.decided_by}`}
            {a.decided_at && ` · ${formatDateTime(a.decided_at)}`}
            {a.note && ` · “${a.note}”`}
          </p>
          {a.result && <pre className={styles.result}>{a.result}</pre>}
        </footer>
      )}
    </li>
  );
}
