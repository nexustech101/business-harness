import { Pencil, Plus, Trash2 } from "lucide-react";
import type { ReactNode } from "react";
import { Alert } from "../../components/Alert";
import { Button } from "../../components/Button";
import { Card } from "../../components/Card";
import { Field, Input, Select, Textarea } from "../../components/Field";
import { useListDraft, useRecordDraft } from "./hooks";
import type { Draft, FieldSpec, ListSection } from "./sections";
import styles from "./ProfilePage.module.css";

/** What every section gets from the page: whether it is being edited, and the edit/save/cancel actions. */
export type Editing = { editing: boolean; onEdit: () => void; onCancel: () => void; saving: boolean; error: string | null };

function EditActions({ editing, onEdit, onCancel, saving, form }: Editing & { form: string }) {
  return editing ? (
    <>
      <Button size="sm" onClick={onCancel}>Cancel</Button>
      <Button size="sm" variant="primary" type="submit" form={form} loading={saving}>
        Save
      </Button>
    </>
  ) : (
    <Button size="sm" variant="ghost" icon={<Pencil />} onClick={onEdit}>
      Edit
    </Button>
  );
}

export function FieldInput({ spec, value, onChange }: { spec: FieldSpec; value: string; onChange: (value: string) => void }) {
  const control =
    spec.kind === "textarea" || spec.kind === "lines" ? (
      <Textarea value={value} onChange={(e) => onChange(e.target.value)} rows={spec.kind === "lines" ? 3 : 2} />
    ) : spec.kind === "select" ? (
      <Select value={value} onChange={(e) => onChange(e.target.value)}>
        {spec.options?.map((o) => (
          <option key={o} value={o}>
            {o || "Not set"}
          </option>
        ))}
      </Select>
    ) : (
      <Input value={value} onChange={(e) => onChange(e.target.value)} inputMode={spec.kind === "number" ? "numeric" : undefined} />
    );
  return (
    <Field label={spec.label} hint={spec.kind === "lines" ? "One per line." : undefined}>
      {control}
    </Field>
  );
}

function Value({ value }: { value: unknown }) {
  if (Array.isArray(value)) return value.length ? <span>{value.join(" · ")}</span> : <span className="muted">—</span>;
  if (value === null || value === undefined || value === "") return <span className="muted">—</span>;
  return <span>{String(value)}</span>;
}

export function Facts({ fields, value }: { fields: FieldSpec[]; value: Record<string, unknown> }) {
  return (
    <dl className={styles.facts}>
      {fields.map((f) => (
        <div key={f.key}>
          <dt>{f.label}</dt>
          <dd>
            <Value value={value[f.key]} />
          </dd>
        </div>
      ))}
    </dl>
  );
}

type RecordProps<T extends object> = Editing & { id: string; title: string; fields: FieldSpec[]; value: T; onSave: (value: T) => void };

/** One object of the profile (overview, financials, compliance): facts, or the form while editing. */
export function RecordSection<T extends object>(props: RecordProps<T>) {
  const { id, title, fields, value } = props;
  return (
    <section id={id} className={styles.anchor}>
      <Card title={title} actions={<EditActions {...props} form={`${id}-form`} />}>
        {props.editing ? <RecordForm {...props} /> : <Facts fields={fields} value={value as Record<string, unknown>} />}
      </Card>
    </section>
  );
}

function RecordForm<T extends object>({ id, fields, value, onSave, error }: RecordProps<T>) {
  const { draft, set, result } = useRecordDraft(fields, value);
  return (
    <form
      id={`${id}-form`}
      className={styles.form}
      onSubmit={(e) => {
        e.preventDefault();
        onSave(result());
      }}
    >
      {error && <Alert title="Not saved">{error}</Alert>}
      <div className={styles.fields}>
        {fields.map((f) => (
          <FieldInput key={f.key} spec={f} value={draft[f.key] ?? ""} onChange={(v) => set(f.key, v)} />
        ))}
      </div>
    </form>
  );
}

type ListProps = Editing & { section: ListSection; items: object[]; onSave: (items: object[]) => void; extra?: (item: Record<string, unknown>) => ReactNode };

/** A list of the profile (departments, roles, tools, flows): one card per item, or item forms while editing. */
export function ListSectionCard(props: ListProps) {
  const { section, items, extra } = props;
  return (
    <section id={section.id} className={styles.anchor}>
      <Card title={section.label} actions={<EditActions {...props} form={`${section.id}-form`} />}>
        {props.editing ? (
          <ListForm {...props} />
        ) : items.length === 0 ? (
          <p className="muted">No {section.label.toLowerCase()} yet. The partner fills this in from the interview, or edit it.</p>
        ) : (
          <ul className={styles.items}>
            {items.map((item, i) => {
              const value = item as Record<string, unknown>;
              return (
                <li key={i} className={styles.item}>
                  <header className={styles.itemHead}>
                    <h3 className="truncate">{section.title(value)}</h3>
                    {extra?.(value)}
                  </header>
                  <Facts fields={section.fields.slice(1)} value={value} />
                </li>
              );
            })}
          </ul>
        )}
      </Card>
    </section>
  );
}

function ListForm({ section, items, onSave, error }: ListProps) {
  const list = useListDraft(section, items);
  return (
    <form
      id={`${section.id}-form`}
      className={styles.form}
      onSubmit={(e) => {
        e.preventDefault();
        onSave(list.result());
      }}
    >
      {error && <Alert title="Not saved">{error}</Alert>}
      {list.drafts.map((draft: Draft, i) => (
        <fieldset key={i} className={styles.itemForm}>
          <legend className="sr-only">
            {section.item} {i + 1}
          </legend>
          <div className={styles.fields}>
            {section.fields.map((f) => (
              <FieldInput key={f.key} spec={f} value={draft[f.key] ?? ""} onChange={(v) => list.set(i, f.key, v)} />
            ))}
          </div>
          <Button size="sm" variant="ghost" icon={<Trash2 />} onClick={() => list.remove(i)}>
            Remove {section.item}
          </Button>
        </fieldset>
      ))}
      <Button size="sm" icon={<Plus />} onClick={list.add}>
        Add {section.item}
      </Button>
    </form>
  );
}
