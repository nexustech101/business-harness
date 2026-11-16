/** The business workspace: summary and hints, profile and interview, partner chat, organized documents, notes. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, unwrap } from "./client";
import type { BusinessProfile, ChatMessage, HintsRequest, OrganizeRequest, UiState } from "./types";

export const businessKeys = {
  workspace: ["workspace"] as const,
  profile: ["business", "profile"] as const,
  interview: ["business", "interview"] as const,
  documents: ["business", "documents"] as const,
  notes: ["business", "notes"] as const,
};

export function useWorkspaceSummary() {
  return useQuery({ queryKey: businessKeys.workspace, queryFn: () => unwrap(api.GET("/v1/workspace")) });
}

/** Contextual hints for the screen in `state`, given the recent events (see app/agentic.tsx). */
export function fetchHints(body: HintsRequest) {
  return unwrap(api.POST("/v1/workspace/hints", { body }));
}

export function useProfile() {
  return useQuery({ queryKey: businessKeys.profile, queryFn: () => unwrap(api.GET("/v1/business/profile")) });
}

/** Replaces the whole profile (PUT); the cached profile and the workspace summary follow. */
export function useSaveProfile() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (profile: BusinessProfile) => unwrap(api.PUT("/v1/business/profile", { body: profile })),
    onSuccess: (saved) => {
      queryClient.setQueryData(businessKeys.profile, saved);
      return queryClient.invalidateQueries({ queryKey: businessKeys.workspace });
    },
  });
}

export function useInterview() {
  return useQuery({ queryKey: businessKeys.interview, queryFn: () => unwrap(api.GET("/v1/business/interview")) });
}

type PartnerChat = { messages: ChatMessage[]; ui_state: UiState | null; signal?: AbortSignal };

/**
 * One partner turn (stateless: the whole conversation each time). The reply's interview replaces the cached one;
 * `profile_changed` refetches the profile and organized documents, `assistants_changed` the assistants, either
 * the workspace summary.
 */
export function usePartnerChat() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ messages, ui_state, signal }: PartnerChat) =>
      unwrap(api.POST("/v1/partner/chat", { body: { messages, ui_state }, signal })),
    onSuccess: (reply) => {
      queryClient.setQueryData(businessKeys.interview, reply.interview);
      const refetch: (readonly string[])[] = [];
      if (reply.profile_changed) refetch.push(businessKeys.profile, businessKeys.documents);
      if (reply.assistants_changed) refetch.push(["assistants"]);
      if (reply.profile_changed || reply.assistants_changed) refetch.push(businessKeys.workspace);
      return Promise.all(refetch.map((queryKey) => queryClient.invalidateQueries({ queryKey })));
    },
  });
}

export function useBusinessDocuments() {
  return useQuery({ queryKey: businessKeys.documents, queryFn: () => unwrap(api.GET("/v1/business/documents")) });
}

export function useOrganizeDocument() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: OrganizeRequest }) =>
      unwrap(api.PUT("/v1/business/documents/{document_id}", { params: { path: { document_id: id } }, body })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: businessKeys.documents }),
  });
}

/** The notes board, newest first (every topic; the page groups them). */
export function useNotes() {
  return useQuery({ queryKey: businessKeys.notes, queryFn: () => unwrap(api.GET("/v1/business/notes")) });
}

export function usePostNote() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { topic: string; text: string }) => unwrap(api.POST("/v1/business/notes", { body })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: businessKeys.notes }),
  });
}
