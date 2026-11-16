import { Database, Download, FileUp, Pencil, Play, Plus, Table2, Trash2 } from "lucide-react";
import { useState } from "react";
import { errorMessage } from "../../api/client";
import { downloadTable, useDropTable, useRunQuery } from "../../api/databases";
import type { CellValue, ConnectorInfo, QueryResult, TableInfo } from "../../api/types";
import { Alert } from "../../components/Alert";
import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Card } from "../../components/Card";
import { Dialog } from "../../components/Dialog";
import { EmptyState } from "../../components/EmptyState";
import { Select, Textarea } from "../../components/Field";
import { PageHeader } from "../../components/PageHeader";
import { Segmented } from "../../components/Segmented";
import { Skeleton } from "../../components/Skeleton";
import tableStyles from "../../components/Table.module.css";
import { useToast } from "../../components/Toast";
import { formatCount, plural } from "../../lib/format";
import { ImportDialog, NewDatabaseDialog, NewTableDialog } from "./dialogs";
import { fromCell, useDatabases, useSelectedTable, useTableRows } from "./hooks";
import styles from "./DatabasesPage.module.css";

type Tab = "rows" | "sql";
type Open = "database" | "table" | "import" | null;

/**
 * `/databases?db=&table=`: the owner's own SQLite databases (each an installed built-in `workspace-database`
 * connector): tables on the left, the selected table's rows or a SQL console on the right.
 */
export function DatabasesPage() {
  const state = useDatabases();
  const [open, setOpen] = useState<Open>(null);
  const { database } = state;
  return (
    <div className={styles.page}>
      <PageHeader
        title="Databases"
        description="Your own data, in tables you design. Assistants you give a database can read it freely; anything they change follows their write policy."
        actions={
          <>
            {state.databases.length > 1 && database && (
              <Select aria-label="Database" value={database.id} onChange={(e) => state.select({ db: e.target.value })} className={styles.picker}>
                {state.databases.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </Select>
            )}
            <Button icon={<Plus />} variant={database ? "secondary" : "primary"} onClick={() => setOpen("database")}>
              New database
            </Button>
          </>
        }
      />
      {state.error ? (
        <Alert title="Your databases could not be loaded">{errorMessage(state.error)}</Alert>
      ) : state.loading ? (
        <Skeleton height={320} />
      ) : !database ? (
        <Card>
          <EmptyState
            icon={<Database />}
            title="Create your first database"
            action={
              <Button variant="primary" icon={<Plus />} onClick={() => setOpen("database")}>
                New database
              </Button>
            }
          >
            Keep customers, orders, inventory or anything else in tables. Import a spreadsheet as CSV, edit rows here, and let your assistants query it.
          </EmptyState>
        </Card>
      ) : (
        <Workspace key={database.id} database={database} wanted={state.table} onSelect={(table) => state.select({ table })} onOpen={setOpen} />
      )}
      {open === "database" && <NewDatabaseDialog onClose={() => setOpen(null)} onCreated={(id) => state.select({ db: id })} />}
      {database && open === "table" && <NewTableDialog id={database.id} onClose={() => setOpen(null)} onCreated={(table) => state.select({ table })} />}
      {database && open === "import" && <ImportDialog id={database.id} onClose={() => setOpen(null)} onCreated={(table) => state.select({ table })} />}
    </div>
  );
}

type WorkspaceProps = { database: ConnectorInfo; wanted: string | null; onSelect: (table: string | null) => void; onOpen: (open: Open) => void };

function Workspace({ database, wanted, onSelect, onOpen }: WorkspaceProps) {
  const { tables, table } = useSelectedTable(database.id, wanted);
  const [tab, setTab] = useState<Tab>("rows");
  if (tables.isError) return <Alert title={`${database.name} could not be opened`}>{errorMessage(tables.error)}</Alert>;
  if (!tables.data) return <Skeleton height={320} />;
  return (
    <div className={styles.workspace}>
      <Card
        flush
        title={database.name}
        className={styles.side}
        actions={
          <>
            <Button size="sm" variant="ghost" icon={<FileUp />} aria-label="Import CSV" title="Import a CSV file as a new table" onClick={() => onOpen("import")} />
            <Button size="sm" icon={<Plus />} onClick={() => onOpen("table")}>
              Table
            </Button>
          </>
        }
      >
        {tables.data.length === 0 ? (
          <p className={styles.noTables}>No tables yet. Create one, or import a CSV file.</p>
        ) : (
          <ul className={styles.tables} aria-label="Tables">
            {tables.data.map((t) => (
              <li key={t.name}>
                <button type="button" aria-current={t.name === table?.name ? "true" : undefined} onClick={() => onSelect(t.name)}>
                  <Table2 aria-hidden />
                  <span className="truncate">{t.name}</span>
                  <span className="muted num">{formatCount(t.rows)}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <div className={styles.main}>
        <Segmented
          label="View"
          value={tab}
          onChange={setTab}
          options={[
            { value: "rows", label: "Rows" },
            { value: "sql", label: "SQL" },
          ]}
        />
        {tab === "sql" ? (
          <SqlConsole id={database.id} />
        ) : table ? (
          <Rows key={table.name} id={database.id} table={table} onDropped={() => onSelect(null)} />
        ) : (
          <Card>
            <EmptyState
              icon={<Table2 />}
              title="This database is empty"
              action={
                <div className={styles.emptyActions}>
                  <Button variant="primary" icon={<Plus />} onClick={() => onOpen("table")}>
                    New table
                  </Button>
                  <Button icon={<FileUp />} onClick={() => onOpen("import")}>
                    Import CSV
                  </Button>
                </div>
              }
            >
              Add a table and its columns, or bring in a spreadsheet.
            </EmptyState>
          </Card>
        )}
      </div>
    </div>
  );
}

function Rows({ id, table, onDropped }: { id: string; table: TableInfo; onDropped: () => void }) {
  const t = useTableRows(id, table.name, table.columns);
  const drop = useDropTable(id);
  const notify = useToast();
  const [dropping, setDropping] = useState(false);
  const page = t.rows.data;
  const editingNew = t.editing?.rowid === "new";
  return (
    <Card
      flush
      title={
        <span className={styles.tableTitle}>
          {table.name} <Badge>{plural(table.rows, "row")}</Badge>
        </span>
      }
      actions={
        <>
          <Button size="sm" variant="ghost" icon={<Download />} onClick={() => downloadTable(id, table.name).catch((e) => notify(errorMessage(e), "danger"))}>
            Export
          </Button>
          <Button size="sm" variant="ghost" icon={<Trash2 />} onClick={() => setDropping(true)}>
            Delete table
          </Button>
          <Button size="sm" variant="primary" icon={<Plus />} disabled={t.editing !== null} onClick={t.startNew}>
            Add row
          </Button>
        </>
      }
    >
      {t.rows.isError ? (
        <div className={styles.pad}>
          <Alert>{errorMessage(t.rows.error)}</Alert>
        </div>
      ) : !page ? (
        <div className={styles.pad}>
          <Skeleton height={120} />
        </div>
      ) : (
        <div className={tableStyles.wrap}>
          <table className={`${tableStyles.table} ${styles.grid}`} aria-label={`Rows of ${table.name}`}>
            <thead>
              <tr>
                {table.columns.map((c) => (
                  <th key={c.name} title={c.type}>
                    {c.name}
                    <span className={styles.type}>{c.primary_key ? "key" : c.type}</span>
                  </th>
                ))}
                <th className={tableStyles.shrink}><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {editingNew && <EditRow table={table} rows={t} label="New row" />}
              {page.rows.map((row, i) => {
                const rowid = page.rowids[i]; // undefined for a table without rowids: readable, edited through SQL
                if (rowid !== undefined && t.editing?.rowid === rowid) return <EditRow key={rowid} table={table} rows={t} label={`Row ${rowid}`} />;
                return (
                  <tr key={rowid ?? `at-${i}`}>
                    {row.map((value, column) => (
                      <td key={column} className={typeof value === "number" ? tableStyles.num : undefined}>
                        <Cell value={value} />
                      </td>
                    ))}
                    <td className={tableStyles.shrink}>
                      {rowid !== undefined && (
                        <div className={styles.rowActions}>
                          <Button size="sm" variant="ghost" icon={<Pencil />} aria-label={`Edit row ${rowid}`} title="Edit" disabled={t.editing !== null} onClick={() => t.startEdit(rowid, row)} />
                          <Button size="sm" variant="ghost" icon={<Trash2 />} aria-label={`Delete row ${rowid}`} title="Delete" onClick={() => t.remove(rowid)} />
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
              {page.rows.length === 0 && !editingNew && (
                <tr>
                  <td colSpan={table.columns.length + 1} className={styles.noRows}>
                    No rows yet. Use “Add row”, or let an assistant fill the table.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
      {page && page.total > 0 && (
        <footer className={styles.pager}>
          <span className="muted num">
            {formatCount(t.offset + 1)}–{formatCount(t.pageEnd)} of {formatCount(page.total)}
          </span>
          <Button size="sm" disabled={!t.previous} onClick={t.previous ?? undefined}>
            Previous
          </Button>
          <Button size="sm" disabled={!t.next} onClick={t.next ?? undefined}>
            Next
          </Button>
        </footer>
      )}
      <Dialog
        open={dropping}
        onClose={() => setDropping(false)}
        title={`Delete ${table.name}?`}
        footer={
          <>
            <Button onClick={() => setDropping(false)}>Cancel</Button>
            <Button
              variant="danger"
              loading={drop.isPending}
              onClick={() =>
                drop.mutate(table.name, {
                  onSuccess: () => {
                    notify(`Deleted ${table.name}`);
                    onDropped();
                  },
                  onError: (e) => notify(errorMessage(e), "danger"),
                })
              }
            >
              Delete table
            </Button>
          </>
        }
      >
        <p>
          The table and its {plural(table.rows, "row")} are deleted for good. Export it first if you may need it.
        </p>
      </Dialog>
    </Card>
  );
}

function Cell({ value }: { value: CellValue }) {
  if (value === null || value === undefined) return <span className={styles.null}>empty</span>;
  return <span className={styles.cell}>{fromCell(value)}</span>;
}

/** A row as inputs (the key column is set by the database); Enter saves, Escape cancels. */
function EditRow({ table, rows: t, label }: { table: TableInfo; rows: ReturnType<typeof useTableRows>; label: string }) {
  const draft = t.editing?.draft ?? {};
  return (
    <tr className={styles.editing} aria-label={label}>
      {table.columns.map((c) => (
        <td key={c.name}>
          {c.primary_key ? (
            <span className="muted num">{draft[c.name] || "auto"}</span>
          ) : (
            <input
              className={styles.input}
              aria-label={c.name}
              type={c.type === "date" ? "date" : "text"}
              inputMode={c.type === "integer" || c.type === "real" ? "decimal" : undefined}
              value={draft[c.name] ?? ""}
              onChange={(e) => t.change(c.name, e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") t.save();
                if (e.key === "Escape") t.cancel();
              }}
            />
          )}
        </td>
      ))}
      <td className={tableStyles.shrink}>
        <div className={styles.rowActions}>
          <Button size="sm" variant="primary" loading={t.saving} onClick={t.save}>
            Save
          </Button>
          <Button size="sm" variant="ghost" onClick={t.cancel}>
            Cancel
          </Button>
        </div>
      </td>
    </tr>
  );
}

const SAMPLE = "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name";

function SqlConsole({ id }: { id: string }) {
  const run = useRunQuery(id);
  const [sql, setSql] = useState(SAMPLE);
  const [write, setWrite] = useState(false);
  return (
    <Card title="SQL console">
      <div className={styles.console}>
        <Textarea aria-label="SQL statement" className={styles.sql} rows={5} spellCheck={false} value={sql} onChange={(e) => setSql(e.target.value)} />
        <div className={styles.consoleBar}>
          <label className={styles.allow}>
            <input type="checkbox" checked={write} onChange={(e) => setWrite(e.target.checked)} />
            Allow this statement to change data
          </label>
          <Button variant="primary" icon={<Play />} loading={run.isPending} disabled={!sql.trim()} onClick={() => run.mutate({ sql, write })}>
            Run
          </Button>
        </div>
        {run.error && <Alert title="The statement did not run">{errorMessage(run.error)}</Alert>}
        {run.data && <QueryOutput result={run.data} wrote={run.variables?.write === true} />}
      </div>
    </Card>
  );
}

function QueryOutput({ result, wrote }: { result: QueryResult; wrote: boolean }) {
  if (result.columns.length === 0) return <p className="muted">{wrote ? `Done. ${plural(result.changed, "row")} changed.` : "The statement returned nothing."}</p>;
  return (
    <>
      <div className={`${tableStyles.wrap} ${styles.output}`}>
        <table className={`${tableStyles.table} ${styles.grid}`} aria-label="Query result">
          <thead>
            <tr>
              {result.columns.map((c, i) => (
                <th key={i}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {result.rows.map((row, i) => (
              <tr key={i}>
                {row.map((value, column) => (
                  <td key={column} className={typeof value === "number" ? tableStyles.num : undefined}>
                    <Cell value={value} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted">
        {plural(result.rows.length, "row")}
        {result.truncated && " shown; more matched. Add LIMIT and OFFSET to page through them."}
      </p>
    </>
  );
}
