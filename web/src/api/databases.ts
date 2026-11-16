/** Workspace databases (the built-in `workspace-database` connector): tables, rows, SQL, CSV import and export. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ok, unwrap } from "./client";
import type { CellValue, TableCreate } from "./types";

export const DATABASE_LISTING = "workspace-database";
export const PAGE_SIZE = 50;

export const databaseKeys = {
  all: (id: string) => ["databases", id] as const,
  tables: (id: string) => ["databases", id, "tables"] as const,
  rows: (id: string, table: string, offset: number) => ["databases", id, "rows", table, offset] as const,
};

type Row = { table: string; rowid: number };

export function useTables(id: string) {
  return useQuery({
    queryKey: databaseKeys.tables(id),
    queryFn: () => unwrap(api.GET("/v1/databases/{connector_id}/tables", { params: { path: { connector_id: id } } })),
  });
}

/** One page of a table's rows (`PAGE_SIZE`), in key order. */
export function useRows(id: string, table: string, offset: number) {
  return useQuery({
    queryKey: databaseKeys.rows(id, table, offset),
    queryFn: () =>
      unwrap(
        api.GET("/v1/databases/{connector_id}/tables/{table}/rows", {
          params: { path: { connector_id: id, table }, query: { limit: PAGE_SIZE, offset } },
        }),
      ),
    placeholderData: (previous) => previous,
  });
}

/** Every write refetches the database's tables (row counts) and rows; `changes` says whether a call was one. */
function useDatabaseMutation<V, R>(id: string, run: (variables: V) => Promise<R>, changes: (variables: V) => boolean = () => true) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: run,
    onSuccess: (_, variables) => (changes(variables) ? queryClient.invalidateQueries({ queryKey: databaseKeys.all(id) }) : undefined),
  });
}

export function useCreateTable(id: string) {
  return useDatabaseMutation(id, (body: TableCreate) =>
    unwrap(api.POST("/v1/databases/{connector_id}/tables", { params: { path: { connector_id: id } }, body })),
  );
}

export function useDropTable(id: string) {
  return useDatabaseMutation(id, (table: string) =>
    ok(api.DELETE("/v1/databases/{connector_id}/tables/{table}", { params: { path: { connector_id: id, table } } })),
  );
}

export function useInsertRow(id: string) {
  return useDatabaseMutation(id, ({ table, values }: { table: string; values: Record<string, CellValue> }) =>
    unwrap(api.POST("/v1/databases/{connector_id}/tables/{table}/rows", { params: { path: { connector_id: id, table } }, body: { values } })),
  );
}

export function useUpdateRow(id: string) {
  return useDatabaseMutation(id, ({ table, rowid, values }: Row & { values: Record<string, CellValue> }) =>
    ok(api.PUT("/v1/databases/{connector_id}/tables/{table}/rows/{rowid}", { params: { path: { connector_id: id, table, rowid } }, body: { values } })),
  );
}

export function useDeleteRow(id: string) {
  return useDatabaseMutation(id, ({ table, rowid }: Row) =>
    ok(api.DELETE("/v1/databases/{connector_id}/tables/{table}/rows/{rowid}", { params: { path: { connector_id: id, table, rowid } } })),
  );
}

/** One SQL statement: a SELECT, or with `write` one that changes the database. */
export function useRunQuery(id: string) {
  return useDatabaseMutation(
    id,
    (body: { sql: string; write: boolean }) => unwrap(api.POST("/v1/databases/{connector_id}/query", { params: { path: { connector_id: id } }, body })),
    (body) => body.write, // a SELECT changes nothing: no refetch
  );
}

/** A new table from a CSV file (header row first). */
export function useImportTable(id: string) {
  return useDatabaseMutation(id, ({ name, file }: { name: string; file: File }) =>
    unwrap(
      api.POST("/v1/databases/{connector_id}/tables/import", {
        params: { path: { connector_id: id } },
        // `file` is binary in the schema (typed as string); the serializer sends the File itself.
        body: { name, file: file as unknown as string },
        bodySerializer() {
          const form = new FormData();
          form.set("name", name);
          form.set("file", file, file.name);
          return form;
        },
      }),
    ),
  );
}

/** Downloads a table as `<table>.csv` (fetched with the API key, then saved through an object URL). */
export async function downloadTable(id: string, table: string) {
  const blob = await ok(
    api.GET("/v1/databases/{connector_id}/tables/{table}/export", { params: { path: { connector_id: id, table } }, parseAs: "blob" }),
  );
  const url = URL.createObjectURL(blob as Blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${table}.csv`;
  link.click();
  URL.revokeObjectURL(url);
}
