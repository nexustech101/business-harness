/** State of the databases page; `DatabasesPage` and its dialogs render it. */
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router";
import { errorMessage } from "../../api/client";
import { useAddConnector, useConnectors } from "../../api/connectors";
import { DATABASE_LISTING, PAGE_SIZE, useDeleteRow, useInsertRow, useRows, useTables, useUpdateRow } from "../../api/databases";
import type { CellValue, Column, ColumnType } from "../../api/types";
import { useAgentic, useScreenState } from "../../app/agentic";
import { useToast } from "../../components/Toast";

export const COLUMN_TYPES: { value: ColumnType; label: string }[] = [
  { value: "text", label: "Text" },
  { value: "integer", label: "Whole number" },
  { value: "real", label: "Decimal number" },
  { value: "date", label: "Date" },
  { value: "boolean", label: "Yes / no" },
];

const YES = new Set(["true", "yes", "y", "1"]);
const NO = new Set(["false", "no", "n", "0"]);

/** What the owner typed, as the value its column stores: empty -> null, numbers as numbers, yes/no as 1/0. */
export function toCell(text: string, type: ColumnType): CellValue {
  const value = text.trim();
  if (value === "") return null;
  if (type === "integer" || type === "real") return Number.isNaN(Number(value)) ? value : Number(value);
  if (type === "boolean") return YES.has(value.toLowerCase()) ? 1 : NO.has(value.toLowerCase()) ? 0 : value;
  return text;
}

export function fromCell(value: CellValue): string {
  return value === null || value === undefined ? "" : String(value);
}

/**
 * The owner's databases (installed `workspace-database` connectors), the selected one (`?db=`, else the first) and
 * its selected table (`?table=`, else the first).
 */
export function useDatabases() {
  const connectors = useConnectors();
  const [params, setParams] = useSearchParams();
  const databases = (connectors.data ?? []).filter((c) => c.listing_id === DATABASE_LISTING);
  const database = databases.find((d) => d.id === params.get("db")) ?? databases[0] ?? null;
  useScreenState({ entity: database ? { kind: "connector", id: database.id, title: database.name } : null, detail: { table: params.get("table") } });

  const select = (change: { db?: string; table?: string | null }) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (change.db !== undefined) {
          next.set("db", change.db);
          next.delete("table");
        }
        if (change.table === null) next.delete("table");
        else if (change.table !== undefined) next.set("table", change.table);
        return next;
      },
      { replace: true },
    );

  return { loading: connectors.isPending, error: connectors.error, databases, database, table: params.get("table"), select };
}

/** Creates a database: adds the built-in connector under `name`, then selects it. */
export function useCreateDatabase(onCreated: (id: string) => void) {
  const add = useAddConnector();
  const notify = useToast();
  const { track } = useAgentic();
  return {
    create: (name: string) => {
      track("action", "database:create");
      add.mutate(
        { listing_id: DATABASE_LISTING, name, transport: "builtin", auth: "none" },
        {
          onSuccess: (info) => {
            notify(`Created ${info.name}`);
            onCreated(info.id);
          },
        },
      );
    },
    creating: add.isPending,
    error: add.error ? errorMessage(add.error) : null,
  };
}

export type Editing = { rowid: number | "new"; draft: Record<string, string> } | null;

/**
 * One table's rows, a page at a time, with the row being edited (`rowid` of a stored row, or "new"): the draft keeps
 * every editable column as text and is converted by column type on save.
 */
export function useTableRows(id: string, table: string, columns: Column[]) {
  const [offset, setOffset] = useState(0);
  const [editing, setEditing] = useState<Editing>(null);
  const rows = useRows(id, table, offset);
  const insert = useInsertRow(id);
  const update = useUpdateRow(id);
  const remove = useDeleteRow(id);
  const notify = useToast();
  const editable = columns.filter((c) => !c.primary_key);
  const fail = (error: unknown) => notify(errorMessage(error), "danger");
  const total = rows.data?.total;
  useEffect(() => {
    // The last row of the last page was deleted: step back to the page that now ends the table.
    if (total !== undefined && offset > 0 && offset >= total) setOffset(Math.floor((total - 1) / PAGE_SIZE) * PAGE_SIZE);
  }, [total, offset]);

  const values = (draft: Record<string, string>, skipEmpty: boolean) =>
    Object.fromEntries(
      editable.flatMap((c): [string, CellValue][] => {
        const cell = toCell(draft[c.name] ?? "", c.type ?? "text");
        return skipEmpty && cell === null ? [] : [[c.name, cell]];
      }),
    );

  return {
    rows, offset, editable, editing,
    pageEnd: Math.min(offset + PAGE_SIZE, rows.data?.total ?? 0),
    previous: offset > 0 ? () => setOffset(Math.max(0, offset - PAGE_SIZE)) : null,
    next: rows.data && offset + PAGE_SIZE < rows.data.total ? () => setOffset(offset + PAGE_SIZE) : null,
    startNew: () => setEditing({ rowid: "new", draft: {} }),
    startEdit: (rowid: number, row: CellValue[]) =>
      setEditing({ rowid, draft: Object.fromEntries((rows.data?.columns ?? []).map((name, i) => [name, fromCell(row[i] ?? null)])) }),
    change: (column: string, text: string) => setEditing((e) => e && { ...e, draft: { ...e.draft, [column]: text } }),
    cancel: () => setEditing(null),
    saving: insert.isPending || update.isPending,
    save: () => {
      if (!editing) return;
      const done = { onSuccess: () => setEditing(null), onError: fail };
      if (editing.rowid === "new") {
        const row = values(editing.draft, true);
        if (Object.keys(row).length === 0) return notify("Fill in at least one column.", "danger");
        insert.mutate({ table, values: row }, done);
      } else {
        update.mutate({ table, rowid: editing.rowid, values: values(editing.draft, false) }, done);
      }
    },
    remove: (rowid: number) => remove.mutate({ table, rowid }, { onError: fail }),
  };
}

/** The tables of a database and the one shown: `wanted` when it exists, else the first. */
export function useSelectedTable(id: string, wanted: string | null) {
  const tables = useTables(id);
  const table = tables.data?.find((t) => t.name === wanted) ?? tables.data?.[0] ?? null;
  return { tables, table };
}
