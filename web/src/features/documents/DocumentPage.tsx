import { ChevronLeft, ChevronRight, Download, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { ApiError, errorMessage } from "../../api/client";
import { usePassages } from "../../api/knowledge";
import { downloadOriginal, useDocument, usePageImage } from "../../api/library";
import type { DocumentDetail } from "../../api/types";
import { useScreenState } from "../../app/agentic";
import { useAssistant } from "../../app/assistant";
import { Alert } from "../../components/Alert";
import { Button } from "../../components/Button";
import { Card } from "../../components/Card";
import { PageHeader } from "../../components/PageHeader";
import { Skeleton } from "../../components/Skeleton";
import { useToast } from "../../components/Toast";
import { formatBytes, plural, timeAgo } from "../../lib/format";
import { DeleteDialog } from "./DocumentsPage";
import styles from "./DocumentPage.module.css";

const PASSAGES = 20;

/**
 * `/documents/:id?page=<n>`: one uploaded document. Its pages as images (PDFs and scans) beside its passages exactly
 * as the assistants search them; a citation's link lands on its page.
 */
export function DocumentPage() {
  const { id = "" } = useParams();
  const document = useDocument(id);
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const notify = useToast();
  const [deleting, setDeleting] = useState(false);
  const d = document.data;
  const pages = d?.page_count ?? 0;
  const page = Math.min(Math.max(Number(params.get("page")) || 1, 1), Math.max(pages, 1));
  useScreenState({ entity: d ? { kind: "document", id: d.id, title: d.title } : null, detail: { page } });
  const { setCurrentDocument } = useAssistant();
  useEffect(() => {
    if (!d) return;
    setCurrentDocument({ id: d.id, title: d.title });
    return () => setCurrentDocument(null);
  }, [d?.id, d?.title, setCurrentDocument]); // eslint-disable-line react-hooks/exhaustive-deps -- by id and title only

  if (document.isError) {
    const missing = document.error instanceof ApiError && document.error.status === 404;
    return <Alert title={missing ? "This document does not exist" : "The document could not be loaded"}>{missing ? <Link to="/documents">Back to documents</Link> : errorMessage(document.error)}</Alert>;
  }
  if (!d) return <Skeleton height={320} />;
  const go = (n: number) => setParams({ page: String(n) }, { replace: true });
  return (
    <div>
      <PageHeader
        eyebrow={<Link to="/documents">Documents</Link>}
        title={d.title}
        description={`${d.location} · ${formatBytes(d.length_bytes)} · added ${timeAgo(d.created_at)}`}
        actions={
          <>
            <Button icon={<Download />} onClick={() => downloadOriginal(d.id, d.location).catch((e) => notify(errorMessage(e), "danger"))}>
              Download
            </Button>
            <Button icon={<Trash2 />} onClick={() => setDeleting(true)}>
              Delete
            </Button>
          </>
        }
      />
      <div className={styles.layout} data-pages={pages > 0}>
        {pages > 0 && (
          <Card
            flush
            title={`Page ${page} of ${pages}`}
            actions={
              <>
                <Button size="sm" icon={<ChevronLeft />} aria-label="Previous page" disabled={page <= 1} onClick={() => go(page - 1)} />
                <Button size="sm" icon={<ChevronRight />} aria-label="Next page" disabled={page >= pages} onClick={() => go(page + 1)} />
              </>
            }
          >
            <PageImage id={d.id} page={page} title={d.title} />
          </Card>
        )}
        <Passages document={d} page={pages > 0 ? page : null} />
      </div>
      <DeleteDialog document={deleting ? d : null} onClose={() => setDeleting(false)} onDeleted={() => navigate("/documents")} />
    </div>
  );
}

function PageImage({ id, page, title }: { id: string; page: number; title: string }) {
  const image = usePageImage(id, page);
  if (image.isError) return <p className={styles.pad}>This page could not be rendered.</p>;
  if (!image.url) return <div className={styles.pad}><Skeleton height={480} /></div>;
  return <img className={styles.page} src={image.url} alt={`Page ${page} of ${title}`} />;
}

/** The document's passages as indexed; those of the page on screen are marked. */
function Passages({ document: d, page }: { document: DocumentDetail; page: number | null }) {
  const [limit, setLimit] = useState(PASSAGES);
  const passages = usePassages(d.id, limit);
  return (
    <Card title={`Passages (${plural(d.chunks, "passage")} in the knowledge index)`}>
      {passages.isError ? (
        <Alert>{errorMessage(passages.error)}</Alert>
      ) : !passages.data ? (
        <Skeleton height={160} />
      ) : (
        <>
          <ol className={styles.passages} aria-label="Passages">
            {passages.data.passages.map((p) => (
              <li key={p.chunk_id} data-current={page !== null && p.page_number === page}>
                <header>
                  <span className="num">#{p.index + 1}</span>
                  <span className="truncate">{p.section_title || "No section"}</span>
                  <span className={styles.retrievals}>{p.retrievals === 0 ? "never retrieved" : `retrieved ${plural(p.retrievals, "time")}`}</span>
                </header>
                <p>{p.content}</p>
              </li>
            ))}
          </ol>
          {passages.data.count > passages.data.passages.length && (
            <Button size="sm" onClick={() => setLimit((n) => n + PASSAGES)} loading={passages.isFetching}>
              Show more passages
            </Button>
          )}
        </>
      )}
    </Card>
  );
}
