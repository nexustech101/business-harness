/** The knowledge index: every source the assistants can search, its passages, and search across all of it. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, unwrap } from "./client";

export type KnowledgeFilter = { q?: string; origin?: "upload" | "workspace"; unused?: boolean; limit?: number };

export const knowledgeKeys = {
  all: ["knowledge"] as const,
  map: (filter: KnowledgeFilter) => ["knowledge", "map", filter] as const,
  passages: (id: string, limit: number) => ["knowledge", "passages", id, limit] as const,
};

/** The map of the index (GET /v1/knowledge): totals, and the sources matching `filter`. */
export function useKnowledgeMap(filter: KnowledgeFilter = {}) {
  return useQuery({
    queryKey: knowledgeKeys.map(filter),
    queryFn: () => unwrap(api.GET("/v1/knowledge", { params: { query: filter } })),
    placeholderData: (previous) => previous, // keep the list while a filter or "more" loads
  });
}

/** The first `limit` passages of a source, as indexed. */
export function usePassages(id: string, limit: number) {
  return useQuery({
    queryKey: knowledgeKeys.passages(id, limit),
    queryFn: () => unwrap(api.GET("/v1/knowledge/{document_id}/passages", { params: { path: { document_id: id }, query: { limit } } })),
    placeholderData: (previous) => previous,
  });
}

/** Search files and workspace records together; the hits count as retrieved, so the map refetches. */
export function useKnowledgeSearch() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (query: string) => unwrap(api.POST("/v1/knowledge/search", { body: { query, filters: {} } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: knowledgeKeys.all }),
  });
}
