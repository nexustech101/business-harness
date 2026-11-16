/** Display of assistant, connector and approval statuses and tool-run outcomes: a short label and a tone each. */
import type { ApprovalStatus, AssistantStatus, ConnectorStatus, ToolRun } from "../api/types";
import type { Tone } from "./flags";

type Display = { label: string; tone: Tone };

export const ASSISTANT_STATUS: Record<AssistantStatus, Display> = {
  active: { label: "Active", tone: "success" },
  draft: { label: "Draft", tone: "neutral" },
  paused: { label: "Paused", tone: "warning" },
};

export const CONNECTOR_STATUS: Record<ConnectorStatus, Display> = {
  connected: { label: "Connected", tone: "success" },
  needs_auth: { label: "Needs sign-in", tone: "warning" },
  error: { label: "Error", tone: "danger" },
  untested: { label: "Untested", tone: "neutral" },
};

export const APPROVAL_STATUS: Record<ApprovalStatus, Display> = {
  pending: { label: "Pending", tone: "warning" },
  executing: { label: "Running", tone: "info" },
  executed: { label: "Executed", tone: "success" },
  rejected: { label: "Rejected", tone: "neutral" },
  failed: { label: "Failed", tone: "danger" },
};

export const TOOL_OUTCOME: Record<ToolRun["outcome"], Display> = {
  ran: { label: "Ran", tone: "success" },
  pending_approval: { label: "Waiting for approval", tone: "warning" },
  denied: { label: "Denied", tone: "danger" },
  failed: { label: "Failed", tone: "danger" },
};
