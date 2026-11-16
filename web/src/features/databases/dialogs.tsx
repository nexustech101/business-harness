/** The dialogs of the databases page: a new database, a new table, a table from a CSV file. */
import { Plus, Trash2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import { errorMessage } from "../../api/client";
import { useCreateTable, useImportTable } from "../../api/databases";
import type { ColumnType } from "../../api/types";
import { Alert } from "../../components/Alert";
import { Button } from "../../components/Button";
import { Dialog } from "../../components/Dialog";
import { Field, Input, Select } from "../../components/Field";
import { useToast } from "../../components/Toast";
import { COLUMN_TYPES, useCreateDatabase } from "./hooks";
import styles from "./DatabasesPage.module.css";

const NAME_HINT = "Letters, digits and _ (no spaces), starting with a letter.";
const NAME = "[A-Za-z_][A-Za-z0-9_]*";

/** A name typed with spaces or dashes, as an identifier the database accepts: `Order items` -> `Order_items`. */
export function identifier(text: string): string {
  return text.trim().replace(/[^A-Za-z0-9_]+/g, "_").replace(/^_+|_+$/g, "");
}

type Created = { onClose: () => void; onCreated: (name: string) => void };

export function NewDatabaseDialog({ onClose, onCreated }: Created) {
  const [name, setName] = useState("");
  const database = useCreateDatabase((id) => {
    onCreated(id);
    onClose();
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (name.trim()) database.create(name.trim());
  };
  return (
    <Dialog
      open
      onClose={onClose}
      title="New database"
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" type="submit" form="new-database" loading={database.creating} disabled={!name.trim()}>
            Create database
          </Button>
        </>
      }
    >
      <form id="new-database" className={styles.form} onSubmit={submit}>
        {database.error && <Alert title="Not created">{database.error}</Alert>}
        <Field label="Name" hint="What you and your assistants call it, e.g. Orders or Inventory. It is stored in this workspace.">
          <Input value={name} onChange={(e) => setName(e.target.value)} maxLength={80} required />
        </Field>
      </form>
    </Dialog>
  );
}

type ColumnDraft = { name: string; type: ColumnType };

export function NewTableDialog({ id, onClose, onCreated }: Created & { id: string }) {
  const create = useCreateTable(id);
  const notify = useToast();
  const [name, setName] = useState("");
  const [columns, setColumns] = useState<ColumnDraft[]>([{ name: "", type: "text" }]);
  const named = columns.filter((c) => identifier(c.name));
  const change = (index: number, patch: Partial<ColumnDraft>) => setColumns((all) => all.map((c, i) => (i === index ? { ...c, ...patch } : c)));

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const table = identifier(name);
    if (!table || named.length === 0) return;
    create.mutate(
      { name: table, columns: named.map((c) => ({ name: identifier(c.name), type: c.type, required: false, primary_key: false })) },
      {
        onSuccess: () => {
          notify(`Created ${table}`);
          onCreated(table);
          onClose();
        },
      },
    );
  };

  return (
    <Dialog
      open
      onClose={onClose}
      title="New table"
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" type="submit" form="new-table" loading={create.isPending} disabled={!identifier(name) || named.length === 0}>
            Create table
          </Button>
        </>
      }
    >
      <form id="new-table" className={styles.form} onSubmit={submit}>
        {create.error && <Alert title="Not created">{errorMessage(create.error)}</Alert>}
        <Field label="Table name" hint={NAME_HINT}>
          <Input value={name} onChange={(e) => setName(e.target.value)} onBlur={() => setName(identifier(name))} maxLength={63} placeholder="customers" required />
        </Field>
        <fieldset className={styles.columns}>
          <legend>Columns</legend>
          <p className="muted">An id column is added automatically.</p>
          {columns.map((c, i) => (
            <div key={i} className={styles.column}>
              <Input aria-label={`Column ${i + 1} name`} value={c.name} onChange={(e) => change(i, { name: e.target.value })} onBlur={() => change(i, { name: identifier(c.name) })} maxLength={63} placeholder="column_name" />
              <Select aria-label={`Column ${i + 1} type`} value={c.type} onChange={(e) => change(i, { type: e.target.value as ColumnType })}>
                {COLUMN_TYPES.map((t) => (
                  <option key={t.value} value={t.value}>
                    {t.label}
                  </option>
                ))}
              </Select>
              <Button variant="ghost" icon={<Trash2 />} aria-label={`Remove column ${i + 1}`} disabled={columns.length === 1} onClick={() => setColumns((all) => all.filter((_, j) => j !== i))} />
            </div>
          ))}
          <Button size="sm" icon={<Plus />} onClick={() => setColumns((all) => [...all, { name: "", type: "text" }])}>
            Add column
          </Button>
        </fieldset>
      </form>
    </Dialog>
  );
}

export function ImportDialog({ id, onClose, onCreated }: Created & { id: string }) {
  const upload = useImportTable(id);
  const notify = useToast();
  const [name, setName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const table = identifier(name);

  const choose = (chosen: File | null) => {
    setFile(chosen);
    if (chosen && !name) setName(identifier(chosen.name.replace(/\.[^.]+$/, "")));
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!file || !table) return;
    upload.mutate(
      { name: table, file },
      {
        onSuccess: (created) => {
          notify(`Imported ${created.rows} rows into ${created.name}`);
          onCreated(created.name);
          onClose();
        },
      },
    );
  };

  return (
    <Dialog
      open
      onClose={onClose}
      title="Import a CSV file"
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" type="submit" form="import-table" loading={upload.isPending} disabled={!file || !table}>
            Import
          </Button>
        </>
      }
    >
      <form id="import-table" className={styles.form} onSubmit={submit}>
        {upload.error && <Alert title="Not imported">{errorMessage(upload.error)}</Alert>}
        <Field label="CSV file" hint="The first row names the columns; number columns are recognised from their values. Export a spreadsheet as CSV (UTF-8) first.">
          <input type="file" accept=".csv,text/csv" required onChange={(e) => choose(e.target.files?.[0] ?? null)} />
        </Field>
        <Field label="Table name" hint={NAME_HINT}>
          <Input value={name} onChange={(e) => setName(e.target.value)} onBlur={() => setName(table)} pattern={NAME} maxLength={63} required />
        </Field>
      </form>
    </Dialog>
  );
}
