/** Assistants (one JSON spec each), what they see, runs, and the approvals queue for their write actions. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { businessKeys } from "./business";
import { api, ok, unwrap } from "./client";
import type { ApprovalStatus, AssistantSpec, AssistantStatus, ChatMessage } from "./types";

export const assistantKeys = {
  all: ["assistants"] as const,
  schema: ["assistant-schema"] as const,
  one: (id: string) => ["assistants", id] as const,
  context: (id: string) => ["assistants", id, "context"] as const,
  approvals: ["approvals"] as const,
};

type QueryClient = ReturnType<typeof useQueryClient>;

function refresh(queryClient: QueryClient) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: assistantKeys.all }),
    queryClient.invalidateQueries({ queryKey: businessKeys.workspace }),
  ]);
}

export function useAssistants() {
  return useQuery({ queryKey: assistantKeys.all, queryFn: () => unwrap(api.GET("/v1/assistants")) });
}

/** JSON Schema of a spec (what POST /v1/assistants takes). Fetched once per session. */
export function useSpecSchema() {
  return useQuery({
    queryKey: assistantKeys.schema,
    queryFn: () => unwrap(api.GET("/v1/assistants/schema")),
    staleTime: Infinity,
  });
}

export function useAssistant(id: string) {
  return useQuery({
    queryKey: assistantKeys.one(id),
    queryFn: () => unwrap(api.GET("/v1/assistants/{assistant_id}", { params: { path: { assistant_id: id } } })),
  });
}

export function useCreateAssistant() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (spec: AssistantSpec) => unwrap(api.POST("/v1/assistants", { body: spec })),
    onSuccess: () => refresh(queryClient),
  });
}

/** Replaces the spec (the status stays). */
export function useUpdateAssistant(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (spec: AssistantSpec) =>
      unwrap(api.PUT("/v1/assistants/{assistant_id}", { params: { path: { assistant_id: id } }, body: spec })),
    onSuccess: (saved) => {
      queryClient.setQueryData(assistantKeys.one(id), saved);
      return refresh(queryClient);
    },
  });
}

export function useSetAssistantStatus(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (status: AssistantStatus) =>
      unwrap(api.PUT("/v1/assistants/{assistant_id}/status", { params: { path: { assistant_id: id } }, body: { status } })),
    onSuccess: (saved) => {
      queryClient.setQueryData(assistantKeys.one(id), saved);
      return refresh(queryClient);
    },
  });
}

export function useDeleteAssistant() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => ok(api.DELETE("/v1/assistants/{assistant_id}", { params: { path: { assistant_id: id } } })),
    onSuccess: (_, id) => {
      queryClient.removeQueries({ queryKey: assistantKeys.one(id) });
      return refresh(queryClient);
    },
  });
}

/** Exactly what the assistant's model receives before a task: layers and offered tools. */
export function useAssistantContext(id: string) {
  return useQuery({
    queryKey: assistantKeys.context(id),
    queryFn: () => unwrap(api.GET("/v1/assistants/{assistant_id}/context", { params: { path: { assistant_id: id } } })),
  });
}

/** Runs a task; write calls the policy sends to `ask` show up in the approvals queue. */
export function useRunAssistant(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (messages: ChatMessage[]) =>
      unwrap(api.POST("/v1/assistants/{assistant_id}/run", { params: { path: { assistant_id: id } }, body: { messages } })),
    onSuccess: () =>
      Promise.all([
        queryClient.invalidateQueries({ queryKey: assistantKeys.approvals }),
        queryClient.invalidateQueries({ queryKey: businessKeys.workspace }),
        queryClient.invalidateQueries({ queryKey: businessKeys.notes }),
      ]),
  });
}

/** Approvals, newest first; `status` limits them to one status. */
export function useApprovals(status?: ApprovalStatus) {
  return useQuery({
    queryKey: [...assistantKeys.approvals, status ?? "all"],
    queryFn: () => unwrap(api.GET("/v1/approvals", { params: { query: { status } } })),
  });
}

export type Decision = { id: string; approve: boolean; always?: boolean; note?: string | null };

/** Approve (the call runs now; `always` also sets the tool to `auto` for the assistant) or reject. */
export function useDecideApproval() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, approve, always = false, note = null }: Decision) =>
      unwrap(api.POST("/v1/approvals/{approval_id}/decision", { params: { path: { approval_id: id } }, body: { approve, always, note } })),
    // Also on error: a 409 means someone else decided it, so the list shown is stale.
    onSettled: () =>
      Promise.all([queryClient.invalidateQueries({ queryKey: assistantKeys.approvals }), refresh(queryClient)]),
  });
}
