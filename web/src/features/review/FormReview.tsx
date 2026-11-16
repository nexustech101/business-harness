import { CheckCircle2, RotateCcw, ShieldCheck } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import type { Check, DocumentDetail, FormDetail } from "../../api/types";
import { Alert } from "../../components/Alert";
import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { EmptyState } from "../../components/EmptyState";
import { Kbd } from "../../components/Kbd";
import { Progress } from "../../components/Progress";
import { Segmented } from "../../components/Segmented";
import { FLAGS } from "../../lib/flags";
import { formatDateTime, plural } from "../../lib/format";
import { CheckRow } from "./CheckRow";
import { useDecide, useReviewShortcuts, useRowSelection } from "./hooks";
import styles from "./FormReview.module.css";

export type Filter = "flagged" | "unchecked" | "all";

const FILTERS: Record<Filter, (c: Check) => boolean> = {
  flagged: (c) => c.flags.length > 0,
  unchecked: (c) => c.review === null,
  all: () => true,
};

type Props = {
  form: FormDetail;
  document: DocumentDetail;
  selected: string | null;
  onSelect: (field: string | null) => void;
};

/** The check list of one extracted form: progress, filter, decisions, approval and keyboard shortcuts. */
export function FormReview({ form, document, selected, onSelect }: Props) {
  const [filter, setFilter] = useState<Filter>(() => (form.open_flags > 0 ? "flagged" : "all"));
  const visible = useMemo(() => form.checks.filter(FILTERS[filter]), [form.checks, filter]);
  const undecided = form.checks.filter((c) => c.flags.length > 0 && c.review === null);
  const counts = { flagged: form.checks.filter(FILTERS.flagged).length, unchecked: form.checks.filter(FILTERS.unchecked).length, all: form.checks.length };
  const { move, rowRef } = useRowSelection(visible, selected, onSelect);
  const { decide, approve, reopen, statusPending, deciding, savingField, editing, setEditing, rowError } = useDecide(form, visible, onSelect, (field) => {
    setFilter("flagged");
    onSelect(field);
  });
  useReviewShortcuts({ current: form.checks.find((c) => c.field === selected) ?? null, move, decide, setEditing, paused: deciding });

  const approved = form.review_status === "approved";
  let group: string | null | undefined;

  return (
    <div className={styles.panel}>
      <div className={styles.head}>
        <div className={styles.titleRow}>
          <div className={styles.titleText}>
            <h2 className="truncate">{form.form_name ?? form.document_type}</h2>
            <span className={styles.sub}>
              {form.pages.length > 1 ? `Pages ${form.pages[0]}–${form.pages.at(-1)}` : `Page ${form.pages[0]}`} · {form.extraction_model ?? "no model"} ·{" "}
              classified by {form.classification.model}
            </span>
          </div>
          {approved ? (
            <Button size="sm" icon={<RotateCcw />} onClick={reopen} loading={statusPending}>
              Reopen
            </Button>
          ) : (
            <Button
              variant="primary"
              icon={<ShieldCheck />}
              onClick={approve}
              loading={statusPending}
              disabled={undecided.length > 0}
              title={undecided.length ? `Decide ${plural(undecided.length, "flagged field")} first` : "Mark this form reviewed"}
            >
              Approve
            </Button>
          )}
        </div>
        <div className={styles.progressRow}>
          <Progress value={form.checked} max={form.total} label="Fields checked" />
          <span className={`${styles.progressText} num`}>
            {form.checked} of {form.total} checked
          </span>
        </div>
        {approved ? (
          <p className={styles.approved}>
            <CheckCircle2 aria-hidden /> Approved by {form.approved_by}
            {form.approved_at && ` · ${formatDateTime(form.approved_at)}`}. A changed decision reopens it.
          </p>
        ) : undecided.length > 0 ? (
          <p className={styles.blocked} data-testid="approve-reason">
            Decide {plural(undecided.length, "flagged field")} to approve: confirm, correct or reject {undecided.length === 1 ? "it" : "each"}.
          </p>
        ) : (
          <p className={styles.ready}>Every flagged field has a decision. Approve when the rest looks right.</p>
        )}
        {form.flags.length > 0 && (
          <div className={styles.formFlags}>
            {form.flags.map((f, i) => (
              <Alert key={i} tone={FLAGS[f.code].tone === "danger" ? "danger" : "warning"} title={FLAGS[f.code].label}>
                {f.message}
              </Alert>
            ))}
          </div>
        )}
        <Segmented<Filter>
          label="Show fields"
          value={filter}
          onChange={setFilter}
          options={[
            { value: "flagged", label: <>Flagged <Count n={counts.flagged} /></> },
            { value: "unchecked", label: <>Unchecked <Count n={counts.unchecked} /></> },
            { value: "all", label: <>All <Count n={counts.all} /></> },
          ]}
        />
      </div>
      {visible.length === 0 ? (
        <EmptyState compact icon={<CheckCircle2 />} title={filter === "flagged" ? "No flagged fields" : "Every field is checked"}>
          {filter === "flagged" ? "The extraction raised no flags on this form." : "Switch to All to see the decisions."}
        </EmptyState>
      ) : (
        <ul className={styles.list} aria-label="Fields">
          {visible.map((check) => {
            const header = check.group !== group ? check.group : undefined;
            group = check.group;
            return (
              <FragmentRow key={check.field} header={header === undefined ? undefined : header ?? "Form fields"}>
                <CheckRow
                  ref={rowRef(check.field)}
                  check={check}
                  document={document}
                  selected={check.field === selected}
                  editing={check.field === editing}
                  busy={savingField === check.field}
                  error={rowError?.field === check.field ? rowError.message : null}
                  onSelect={() => onSelect(check.field)}
                  onDecide={(body) => decide(check, body)}
                  onEdit={(on) => setEditing(on ? check.field : null)}
                />
              </FragmentRow>
            );
          })}
        </ul>
      )}
      <div className={styles.legend} aria-label="Keyboard shortcuts">
        <span><Kbd>j</Kbd> <Kbd>k</Kbd> move</span>
        <span><Kbd>c</Kbd> confirm</span>
        <span><Kbd>e</Kbd> correct</span>
        <span><Kbd>r</Kbd> reject</span>
        <span><Kbd>u</Kbd> undo</span>
      </div>
    </div>
  );
}

function Count({ n }: { n: number }) {
  return <Badge>{n}</Badge>;
}

function FragmentRow({ header, children }: { header?: string; children: ReactNode }) {
  return (
    <>
      {header !== undefined && <li className={styles.group} aria-hidden>{header}</li>}
      {children}
    </>
  );
}
