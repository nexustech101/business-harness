/** State of the approvals page; `ApprovalsPage` renders it. */
import { useSearchParams } from "react-router";
import { useApprovals, useDecideApproval } from "../../api/assistants";
import { useWorkspaceSummary } from "../../api/business";
import { errorMessage } from "../../api/client";
import type { Approval, ApprovalStatus } from "../../api/types";
import { useAgentic, useScreenState } from "../../app/agentic";
import { useToast } from "../../components/Toast";

export type Filter = ApprovalStatus | "all";
export const FILTERS: Filter[] = ["pending", "all", "executing", "executed", "rejected", "failed"];

/** The sidebar badge: pending approvals from the workspace summary (hidden at 0). */
export function usePendingApprovals(): number | undefined {
  return useWorkspaceSummary().data?.pending_approvals || undefined;
}

/**
 * The list for the `?status=` filter (default `pending`; `all` is the history with pending first) and the decision:
 * approve (the call runs now), reject, or approve with `always` (the tool becomes `auto` for that assistant).
 */
export function useApprovalsView() {
  const [params, setParams] = useSearchParams();
  const status = params.get("status") as Filter | null;
  const filter: Filter = status && FILTERS.includes(status) ? status : "pending";
  const list = useApprovals(filter === "all" ? undefined : filter);
  const decision = useDecideApproval();
  const notify = useToast();
  const { track } = useAgentic();
  const approvals = [...(list.data ?? [])].sort((a, b) => Number(b.status === "pending") - Number(a.status === "pending"));
  useScreenState({ detail: { filter, shown: approvals.length } });

  const setFilter = (next: Filter) => {
    setParams(next === "pending" ? {} : { status: next }, { replace: true });
    track("select", `filter:${next}`);
  };

  const decide = (approval: Approval, approve: boolean, always: boolean, note: string) => {
    track("action", `approval:${approval.id}`, { approve, always, tool: `${approval.connector_id}/${approval.tool}` });
    decision.mutate(
      { id: approval.id, approve, always, note: note.trim() || null },
      {
        onSuccess: (done) =>
          notify(
            done.status === "executed" ? `Ran ${done.tool}${always ? `; ${done.assistant_name} may now use it without asking` : ""}`
              : done.status === "failed" ? `${done.tool} failed: ${done.result ?? "no details"}`
              : `Rejected ${done.tool}`,
            done.status === "failed" ? "danger" : "success",
          ),
        onError: (e) => notify(errorMessage(e), "danger"),
      },
    );
  };

  return { filter, setFilter, list, approvals, decide, deciding: decision.isPending ? decision.variables?.id : undefined };
}
