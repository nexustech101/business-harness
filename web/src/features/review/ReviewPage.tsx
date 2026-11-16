import { ArrowLeft, Copy, Download, FileQuestion } from "lucide-react";
import { Link, useParams } from "react-router";
import { ApiError, errorMessage } from "../../api/client";
import { downloadOriginal, useDocument, useTypeName } from "../../api/library";
import type { DocumentDetail, FormSummary } from "../../api/types";
import { useScreenState } from "../../app/agentic";
import { useAssistant } from "../../app/assistant";
import { Alert } from "../../components/Alert";
import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { EmptyState } from "../../components/EmptyState";
import { Spinner } from "../../components/Spinner";
import { useToast } from "../../components/Toast";
import { plural } from "../../lib/format";
import { ReviewState } from "../documents/ReviewState";
import { Mark } from "../assistant/Mark";
import { FormReview } from "./FormReview";
import { useWorkspace } from "./hooks";
import { PageViewer } from "./PageViewer";
import styles from "./ReviewPage.module.css";

/** `/documents/:id?form=<form id>&page=<n>`: the page viewer beside the selected form's checks. */
export function ReviewPage() {
  const { id = "" } = useParams();
  const doc = useDocument(id);
  if (doc.isError) {
    const missing = doc.error instanceof ApiError && doc.error.status === 404;
    return (
      <div className={styles.center}>
        {missing ? (
          <EmptyState icon={<FileQuestion />} title="Document not found" action={<Link to="/documents">Back to documents</Link>}>
            It was deleted, or it belongs to another API key.
          </EmptyState>
        ) : (
          <Alert title="The document could not be loaded">{errorMessage(doc.error)}</Alert>
        )}
      </div>
    );
  }
  if (!doc.data) {
    return (
      <div className={styles.center}>
        <Spinner size={20} label="Loading document" />
      </div>
    );
  }
  return <Workspace document={doc.data} />;
}

function Workspace({ document }: { document: DocumentDetail }) {
  const assistant = useAssistant();
  const notify = useToast();
  const typeName = useTypeName();
  const forms = document.forms;
  const { formId, summary, form, page, setPage, selectForm, selected, select, overlays } = useWorkspace(document);
  useScreenState({ entity: { kind: "document", id: document.id, title: document.title }, detail: { form: formId, page, field: selected } });

  return (
    <div className={styles.workspace}>
      <header className={styles.header}>
        <div className={styles.headText}>
          <Link to="/documents" className={styles.back}>
            <ArrowLeft aria-hidden /> Documents
          </Link>
          <div className={styles.titleLine}>
            <h1 className="truncate">{document.title}</h1>
            <ReviewState document={document} />
          </div>
          <p className={styles.meta}>
            {[document.client ?? "No client", document.tax_year ? `Tax year ${document.tax_year}` : null, plural(document.page_count, "page"), plural(forms.length, "form")]
              .filter(Boolean)
              .join(" · ")}
          </p>
        </div>
        <div className={styles.headActions}>
          <Button
            icon={<Download />}
            onClick={() => downloadOriginal(document.id, document.location).catch((e) => notify(errorMessage(e), "danger"))}
          >
            Original
          </Button>
          <Button icon={<Mark size={16} />} onClick={assistant.openPanel}>
            Ask about this document
          </Button>
        </div>
      </header>
      {forms.length > 0 && (
        <div className={styles.tabs} role="tablist" aria-label="Forms in this document">
          {forms.map((f) => (
            <button
              key={f.id}
              role="tab"
              aria-selected={f.id === formId}
              className={styles.tab}
              onClick={() => selectForm(f)}
            >
              <span className={styles.tabName}>{f.status === "ok" ? typeName(f.document_type) : f.status === "duplicate" ? `${typeName(f.document_type)} copy` : "Unidentified"}</span>
              <span className={styles.tabPages}>p. {f.pages.join(", ")}</span>
              <FormBadge form={f} />
            </button>
          ))}
        </div>
      )}
      <div className={styles.split}>
        <PageViewer document={document} page={page} onPage={setPage} overlays={overlays} selected={selected} onSelect={select} />
        <aside className={styles.side}>
          {!summary ? (
            <EmptyState compact title="No forms in this document">Text files are stored for search only; there is nothing to review.</EmptyState>
          ) : summary.status !== "ok" ? (
            <NotReviewed form={summary} forms={forms} onOpen={selectForm} />
          ) : form.isError ? (
            <div className={styles.pad}>
              <Alert title="The form could not be loaded">{errorMessage(form.error)}</Alert>
            </div>
          ) : !form.data ? (
            <div className={styles.center}>
              <Spinner size={20} label="Loading form" />
            </div>
          ) : (
            <FormReview key={form.data.id} form={form.data} document={document} selected={selected} onSelect={select} />
          )}
        </aside>
      </div>
    </div>
  );
}

function FormBadge({ form }: { form: FormSummary }) {
  if (form.status !== "ok") return <Badge>Not reviewed</Badge>;
  if (form.review_status === "approved") return <Badge tone="success">Approved</Badge>;
  if (form.open_flags > 0) return <Badge tone="warning">{form.open_flags}</Badge>;
  return <Badge tone="accent">Pending</Badge>;
}

function NotReviewed({ form, forms, onOpen }: { form: FormSummary; forms: FormSummary[]; onOpen: (f: FormSummary) => void }) {
  const original = form.duplicate_of !== null ? forms.find((f) => f.index === form.duplicate_of) : undefined;
  return form.status === "duplicate" ? (
    <EmptyState
      icon={<Copy />}
      title="Duplicate copy"
      action={original && <Button onClick={() => onOpen(original)}>Open the original</Button>}
    >
      Every value on this {form.form_name ?? "form"} matches an earlier form in the file{original ? ` (pages ${original.pages.join(", ")})` : ""}. Only the
      original is reviewed.
    </EmptyState>
  ) : (
    <EmptyState icon={<FileQuestion />} title="Not a supported form">
      Pages {form.pages.join(", ")} could not be identified as one of the supported tax forms. Their text is stored for search.
    </EmptyState>
  );
}
