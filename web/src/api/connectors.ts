/** MCP connectors: the store, installed connectors, their tools, and OAuth sign-in for remote servers. */
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { businessKeys } from "./business";
import { api, ok, unwrap } from "./client";
import type { ConnectorCreate } from "./types";

export const connectorKeys = {
  catalog: ["connector-catalog"] as const,
  all: ["connectors"] as const,
  tools: (id: string) => ["connectors", id, "tools"] as const,
};

function refresh(queryClient: ReturnType<typeof useQueryClient>) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: connectorKeys.all }),
    queryClient.invalidateQueries({ queryKey: businessKeys.workspace }),
  ]);
}

/** The store, featured first. Fetched once per session. */
export function useCatalog() {
  return useQuery({ queryKey: connectorKeys.catalog, queryFn: () => unwrap(api.GET("/v1/connectors/catalog")), staleTime: Infinity });
}

export function useConnectors() {
  return useQuery({ queryKey: connectorKeys.all, queryFn: () => unwrap(api.GET("/v1/connectors")) });
}

/** Adds and checks a connector (the result is in `status`). */
export function useAddConnector() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ConnectorCreate) => unwrap(api.POST("/v1/connectors", { body })),
    onSuccess: () => refresh(queryClient),
    gcTime: 0, // the body holds the token: drop it from the mutation cache once nothing observes it
  });
}

export function useRemoveConnector() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => ok(api.DELETE("/v1/connectors/{connector_id}", { params: { path: { connector_id: id } } })),
    onSuccess: () => refresh(queryClient),
  });
}

/** Connects and lists its tools again; status, error and tool count are updated. */
export function useCheckConnector() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => unwrap(api.POST("/v1/connectors/{connector_id}/check", { params: { path: { connector_id: id } } })),
    onSuccess: (_, id) => Promise.all([refresh(queryClient), queryClient.invalidateQueries({ queryKey: connectorKeys.tools(id) })]),
  });
}

function toolsQuery(id: string) {
  return {
    queryKey: connectorKeys.tools(id),
    queryFn: () => unwrap(api.GET("/v1/connectors/{connector_id}/tools", { params: { path: { connector_id: id } } })),
  };
}

export function useConnectorTools(id: string) {
  return useQuery(toolsQuery(id));
}

/** The tools of several connectors (an assistant's), flattened; `pending` until every list arrived. */
export function useToolsOf(ids: string[]) {
  return useQueries({
    queries: ids.map(toolsQuery),
    combine: (results) => ({ tools: results.flatMap((r) => r.data ?? []), pending: results.some((r) => r.isPending), errors: results.flatMap((r) => (r.error ? [r.error] : [])) }),
  });
}

/** Starts the provider's sign-in; the browser goes to `authorize_url` and comes back to /connectors. */
export function useStartOAuth() {
  return useMutation({
    mutationFn: (id: string) => unwrap(api.POST("/v1/connectors/{connector_id}/oauth", { params: { path: { connector_id: id } } })),
    onSuccess: ({ authorize_url }) => window.location.assign(authorize_url),
  });
}
