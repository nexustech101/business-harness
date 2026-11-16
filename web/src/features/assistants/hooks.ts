/** State of the assistants pages; `AssistantsPage`, `AssistantDetailPage` and their parts render it. */
import { useMemo, useState } from "react";
import { useNavigate } from "react-router";
import {
  useAssistant, useAssistants, useCreateAssistant, useDeleteAssistant, useRunAssistant, useSetAssistantStatus, useSpecSchema, useUpdateAssistant,
} from "../../api/assistants";
import { errorMessage } from "../../api/client";
import { useToolsOf } from "../../api/connectors";
import type { AssistantInfo, AssistantSpec, AssistantStatus, WriteMode } from "../../api/types";
import { useAgentic } from "../../app/agentic";
import { useToast } from "../../components/Toast";
import type { NavChild } from "../index";
import { parseSpec, TEMPLATE, type JsonSchema } from "./specSchema";

/** Sidebar entries under Assistants: the active ones. */
export function useActiveAssistantLinks(): NavChild[] {
  const { data } = useAssistants();
  return useMemo(() => (data ?? []).filter((a) => a.status === "active").map((a) => ({ to: `/assistants/${a.id}`, label: a.name })), [data]);
}

/** The spec part of an assistant (what PUT /v1/assistants/{id} takes). */
export function specOf(a: AssistantInfo): AssistantSpec {
  const { name, role, department, instructions, connectors, knowledge, shares, policy, max_tool_rounds } = a;
  return { name, role, department, instructions, connectors, knowledge, shares, policy, max_tool_rounds };
}

export const toJson = (value: unknown) => JSON.stringify(value, null, 2);

/** A JSON text editor checked against GET /v1/assistants/schema while typing (no errors until the schema loads). */
export function useSpecEditor(initial: string) {
  const schema = useSpecSchema();
  const [text, setText] = useState(initial);
  const checked = useMemo(
    () => (schema.data ? parseSpec(text, schema.data as JsonSchema) : { spec: null, errors: [] }),
    [text, schema.data],
  );
  return { text, setText, ...checked, schemaError: schema.error, ready: schema.data !== undefined };
}

/** The "New assistant" editor: starts from the template; a created assistant opens its page. */
export function useCreateAssistantFlow() {
  const editor = useSpecEditor(toJson(TEMPLATE));
  const create = useCreateAssistant();
  const navigate = useNavigate();
  const { track } = useAgentic();
  const submit = () => {
    if (!editor.spec) return;
    track("action", "assistant:create", { name: editor.spec.name });
    create.mutate(editor.spec, { onSuccess: (created) => navigate(`/assistants/${created.id}`) });
  };
  return { editor, submit, creating: create.isPending, error: create.error ? errorMessage(create.error) : null, applyTemplate: () => editor.setText(toJson(TEMPLATE)) };
}

/** One assistant: status changes, spec saves (the JSON editor) and deletion. */
export function useAssistantView(id: string) {
  const assistant = useAssistant(id);
  const update = useUpdateAssistant(id);
  const status = useSetAssistantStatus(id);
  const remove = useDeleteAssistant();
  const notify = useToast();
  const navigate = useNavigate();
  const { track } = useAgentic();

  const setStatus = (next: AssistantStatus) => {
    track("action", `assistant:${id}:status`, { status: next });
    status.mutate(next, { onError: (e) => notify(errorMessage(e), "danger") });
  };
  const save = (spec: AssistantSpec, what = "Spec") =>
    update.mutate(spec, { onSuccess: () => notify(`${what} saved`), onError: (e) => notify(errorMessage(e), "danger") });
  const destroy = () =>
    remove.mutate(id, {
      onSuccess: () => {
        notify(`Deleted ${assistant.data?.name ?? "the assistant"}`);
        navigate("/assistants");
      },
      onError: (e) => notify(errorMessage(e), "danger"),
    });
  return { assistant, setStatus, statusPending: status.isPending, save, saving: update.isPending, destroy, deleting: remove.isPending };
}

export type ToolMode = WriteMode | "";

/**
 * The write policy as a form: the default mode and a mode per write tool of the assistant's connectors (`""` keeps
 * the default). Overrides for tools no longer offered are listed too, so they can be cleared.
 */
export function usePolicyEditor(assistant: AssistantInfo) {
  const connectors = assistant.connectors ?? [];
  const { tools, pending, errors } = useToolsOf(connectors);
  const saved = assistant.policy ?? { default: "ask" as WriteMode, tools: {} };
  const [mode, setMode] = useState<WriteMode>(saved.default);
  const [overrides, setOverrides] = useState<Record<string, WriteMode>>(saved.tools ?? {});
  const writeTools = tools.filter((t) => !t.read_only);
  const known = new Map(writeTools.map((t) => [`${t.connector_id}/${t.name}`, t.description]));
  const keys = [...new Set([...known.keys(), ...Object.keys(overrides)])];
  const dirty = mode !== saved.default || JSON.stringify(overrides) !== JSON.stringify(saved.tools ?? {});

  const setTool = (key: string, value: ToolMode) =>
    setOverrides((all) => {
      const next = { ...all };
      if (value) next[key] = value;
      else delete next[key];
      return next;
    });

  return {
    mode, setMode, overrides, setTool, dirty,
    rows: keys.map((key) => ({ key, description: known.get(key) ?? null })),
    readOnly: tools.length - writeTools.length,
    pending: connectors.length > 0 && pending,
    errors,
    policy: { default: mode, tools: overrides },
  };
}

/** One task for the assistant (a single user message); the reply and its tool runs. */
export function useRunPanel(id: string, active: boolean) {
  const run = useRunAssistant(id);
  const [task, setTask] = useState("");
  const { track } = useAgentic();
  const submit = () => {
    if (!task.trim() || !active || run.isPending) return; // Ctrl+Enter must not start a second run
    track("action", `assistant:${id}:run`);
    run.mutate([{ role: "user", content: task.trim() }]);
  };
  return { task, setTask, submit, running: run.isPending, result: run.data, error: run.error ? errorMessage(run.error) : null };
}
