import { Plug } from "lucide-react";
import { Link } from "react-router";
import { errorMessage } from "../../api/client";
import type { BusinessProfile, OrganizedDocument } from "../../api/types";
import { Alert } from "../../components/Alert";
import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Card } from "../../components/Card";
import { Input, Select } from "../../components/Field";
import { PageHeader } from "../../components/PageHeader";
import { Skeleton } from "../../components/Skeleton";
import table from "../../components/Table.module.css";
import { formatDateTime, timeAgo } from "../../lib/format";
import { useOrganizedDocuments, useProfilePage, useToolConnection } from "./hooks";
import { FINANCIAL_FIELDS, LISTS, OVERVIEW_FIELDS, SECTIONS, type FieldSpec } from "./sections";
import { ListSectionCard, RecordSection, type Editing } from "./SectionCards";
import styles from "./ProfilePage.module.css";

const NO_FINANCIALS: NonNullable<BusinessProfile["financials"]> = { pricing: "", currency: "USD", fiscal_year_end: "", accounting_method: "" };
const COMPLIANCE: FieldSpec[] = [{ key: "compliance", label: "Licenses, regulations and filing duties", kind: "lines" }];

/** `/profile#<section>`: what the partner knows about the business; every section is editable (PUT the profile). */
export function ProfilePage() {
  const page = useProfilePage();
  const connection = useToolConnection();
  const profile = page.profile.data;
  const editing = (id: string): Editing => ({
    editing: page.editing === id,
    onEdit: () => page.edit(id),
    onCancel: page.cancel,
    saving: page.saving,
    error: page.editing === id ? page.error : null,
  });

  return (
    <div className={styles.page}>
      <PageHeader
        title="Business profile"
        description={profile?.updated_at ? `Filled from the interview and your documents. Updated ${timeAgo(profile.updated_at)}.` : "Filled from the interview and your documents."}
      />
      <nav className={styles.toc} aria-label="Profile sections">
        {SECTIONS.map((s) => (
          <Link key={s.id} to={`#${s.id}`}>
            {s.label}
          </Link>
        ))}
      </nav>
      {page.profile.isError ? (
        <Alert title="The profile could not be loaded">{errorMessage(page.profile.error)}</Alert>
      ) : !profile ? (
        <Skeleton height={240} />
      ) : (
        <>
          <RecordSection {...editing("overview")} id="overview" title="Overview" fields={OVERVIEW_FIELDS} value={profile} onSave={page.commit} />
          {LISTS.map((section) => (
            <ListSectionCard
              key={section.id}
              {...editing(section.id)}
              section={section}
              items={profile[section.key] ?? []}
              onSave={(items) => page.commit({ [section.key]: items } as Partial<BusinessProfile>)}
              extra={section.key === "tools" ? (tool) => <ToolConnect listingId={tool.listing_id as string | null} connection={connection} /> : undefined}
            />
          ))}
          <RecordSection {...editing("financials")} id="financials" title="Financials" fields={FINANCIAL_FIELDS} value={profile.financials ?? NO_FINANCIALS} onSave={(financials) => page.commit({ financials })} />
          <RecordSection {...editing("compliance")} id="compliance" title="Compliance" fields={COMPLIANCE} value={profile} onSave={page.commit} />
          <OrganizedDocuments departments={(profile.departments ?? []).map((d) => d.name)} />
        </>
      )}
    </div>
  );
}

function ToolConnect({ listingId, connection }: { listingId: string | null; connection: ReturnType<typeof useToolConnection> }) {
  const { listing, installed } = connection(listingId);
  if (!listing) return null;
  if (installed) return <Badge tone="success">Connected</Badge>;
  return (
    <Link to={`/connectors?add=${encodeURIComponent(listing.id)}`} className={styles.connect} aria-label={`Connect ${listing.name}`}>
      <Plug aria-hidden /> Connect
    </Link>
  );
}

function OrganizedDocuments({ departments }: { departments: string[] }) {
  const docs = useOrganizedDocuments();
  const row = (d: OrganizedDocument) => {
    const edit = docs.editing?.id === d.document_id ? docs.editing : null;
    const options = [...new Set([...departments, ...(d.department ? [d.department] : [])])];
    return (
      <tr key={d.document_id}>
        <td>
          <Link to={`/documents/${d.document_id}`}>{d.title}</Link>
        </td>
        <td>
          {edit ? (
            <Select aria-label={`Department of ${d.title}`} value={edit.department} onChange={(e) => docs.change({ department: e.target.value })}>
              <option value="">No department</option>
              {options.map((o) => (
                <option key={o}>{o}</option>
              ))}
            </Select>
          ) : (
            d.department ?? <span className="muted">—</span>
          )}
        </td>
        <td>
          {edit ? (
            <Input aria-label={`Kind of ${d.title}`} value={edit.kind} maxLength={60} onChange={(e) => docs.change({ kind: e.target.value })} />
          ) : (
            <Badge>{d.kind}</Badge>
          )}
        </td>
        <td className={styles.summary}>{d.summary}</td>
        <td className={`${table.num} muted`} title={formatDateTime(d.organized_at)}>
          {timeAgo(d.organized_at)}
        </td>
        <td className={table.shrink}>
          {edit ? (
            <div className={styles.rowActions}>
              <Button size="sm" onClick={docs.cancel}>Cancel</Button>
              <Button size="sm" variant="primary" loading={docs.saving} disabled={!edit.kind.trim()} onClick={() => docs.save(d)}>
                Save
              </Button>
            </div>
          ) : (
            <Button size="sm" variant="ghost" onClick={() => docs.start(d)} aria-label={`Edit ${d.title}`}>
              Edit
            </Button>
          )}
        </td>
      </tr>
    );
  };
  return (
    <section id="documents" className={styles.anchor}>
      <Card title="Organized documents" flush actions={<Link to="/documents">All documents</Link>}>
        {docs.documents.isError ? (
          <div className={styles.pad}>
            <Alert>{errorMessage(docs.documents.error)}</Alert>
          </div>
        ) : !docs.documents.data ? (
          <div className={styles.pad}>
            <Skeleton height={80} />
          </div>
        ) : docs.documents.data.length === 0 ? (
          <p className={`${styles.pad} muted`}>No documents organized yet. Upload them on the Partner page; the partner files them here.</p>
        ) : (
          <div className={table.wrap}>
            <table className={table.table}>
              <thead>
                <tr>
                  <th>Document</th>
                  <th>Department</th>
                  <th>Kind</th>
                  <th>Summary</th>
                  <th className={table.num}>Organized</th>
                  <th className={table.shrink}><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>{docs.documents.data.map(row)}</tbody>
            </table>
          </div>
        )}
      </Card>
    </section>
  );
}
