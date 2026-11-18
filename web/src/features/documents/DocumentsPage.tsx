import { ChevronLeft, ChevronRight, FileText, Search, Trash2, Upload } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { useBusinessDocuments } from "../../api/business";
import { errorMessage } from "../../api/client";
import { useDeleteDocument, useDocuments } from "../../api/library";
import type { LibraryDocument, OrganizedDocument } from "../../api/types";
import { useScreenState } from "../../app/agentic";
import { Alert } from "../../components/Alert";
import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Card } from "../../components/Card";
import { Dialog } from "../../components/Dialog";
import { EmptyState } from "../../components/EmptyState";
import { Input } from "../../components/Field";
import { PageHeader } from "../../components/PageHeader";
import { Skeleton } from "../../components/Skeleton";
import table from "../../components/Table.module.css";
import { useToast } from "../../components/Toast";
import { formatBytes, formatCount, plural, timeAgo } from "../../lib/format";
import { UploadDialog } from "./UploadDialog";
import styles from "./DocumentsPage.module.css";

const PAGE_SIZE = 25;

/** The title search and the page live in the URL (`?q=&offset=`), so the top bar's search lands on a filtered list. */
function useFilters() {
  const [params, setParams] = useSearchParams();
  const set = (changes: Record<string, string | number | undefined>) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        for (const [key, value] of Object.entries(changes)) {
          if (value === undefined || value === "") next.delete(key);
          else next.set(key, String(value));
        }
        if (!("offset" in changes)) next.delete("offset");
        return next;
      },
      { replace: true },
    );
  return { q: params.get("q") || undefined, offset: Number(params.get("offset")) || 0, uploading: params.get("upload") === "1", set };
}

/** `/documents?q=&offset=&upload=1`: the uploaded files, how each is filed in the business profile, upload and delete. */
export function DocumentsPage() {
  const { q, offset, uploading, set } = useFilters();
  const list = useDocuments({ q, limit: PAGE_SIZE, offset });
  const filed = useBusinessDocuments();
  const [toDelete, setToDelete] = useState<LibraryDocument | null>(null);
  useScreenState({ detail: { q: q ?? null, offset, shown: list.data?.documents.length ?? null } });
  const placed = new Map((filed.data ?? []).map((d) => [d.document_id, d]));

  return (
    <div>
      <PageHeader
        title="Documents"
        description="The files you uploaded. Each is searchable knowledge as soon as it is stored; the partner files it by department and kind."
        actions={
          <Button variant="primary" icon={<Upload />} onClick={() => set({ upload: 1, offset })}>
            Upload
          </Button>
        }
      />
      <Card flush>
        <TitleSearch q={q} onChange={(text) => set({ q: text })} />
        {list.isError ? (
          <div className={styles.pad}>
            <Alert title="Documents could not be loaded">{errorMessage(list.error)}</Alert>
          </div>
        ) : !list.data ? (
          <div className={styles.pad}>
            {Array.from({ length: 5 }, (_, i) => (
              <div key={i} className={styles.skeletonRow}>
                <Skeleton height={16} />
              </div>
            ))}
          </div>
        ) : list.data.documents.length === 0 ? (
          q ? (
            <EmptyState icon={<Search />} title="No matching documents" action={<Button onClick={() => set({ q: undefined })}>Clear search</Button>}>
              No title contains “{q}”. To search inside documents, use the Knowledge page.
            </EmptyState>
          ) : (
            <EmptyState
              icon={<FileText />}
              title="No documents yet"
              action={<Button variant="primary" icon={<Upload />} onClick={() => set({ upload: 1 })}>Upload documents</Button>}
            >
              Upload contracts, price lists, policies, reports or spreadsheets: PDFs, scans and text files.
            </EmptyState>
          )
        ) : (
          <>
            <DocumentTable documents={list.data.documents} placed={placed} onDelete={setToDelete} />
            <Pager count={list.data.count} offset={offset} shown={list.data.documents.length} onChange={(o) => set({ offset: o || undefined })} />
          </>
        )}
      </Card>
      <UploadDialog open={uploading} onClose={() => set({ upload: undefined, offset })} />
      <DeleteDialog document={toDelete} onClose={() => setToDelete(null)} />
    </div>
  );
}

/** The title filter: typing updates `?q=` after a short pause. */
function TitleSearch({ q, onChange }: { q?: string; onChange: (text: string) => void }) {
  const [text, setText] = useState(q ?? "");
  useEffect(() => {
    setText(q ?? "");
  }, [q]);
  useEffect(() => {
    const timer = setTimeout(() => {
      if (text.trim() !== (q ?? "")) onChange(text.trim());
    }, 250);
    return () => clearTimeout(timer);
  }, [text]); // eslint-disable-line react-hooks/exhaustive-deps -- only typing should debounce
  return (
    <div className={styles.filters}>
      <div className={styles.search}>
        <Search aria-hidden />
        <Input value={text} onChange={(e) => setText(e.target.value)} placeholder="Search by title" aria-label="Search by title" />
      </div>
    </div>
  );
}

type TableProps = { documents: LibraryDocument[]; placed: Map<string, OrganizedDocument>; onDelete: (d: LibraryDocument) => void };

function DocumentTable({ documents, placed, onDelete }: TableProps) {
  const navigate = useNavigate();
  return (
    <div className={table.wrap}>
      <table className={table.table}>
        <thead>
          <tr>
            <th>Document</th>
            <th>Filed as</th>
            <th className={table.num}>Pages</th>
            <th className={table.num}>Passages</th>
            <th className={table.num}>Uploaded</th>
            <th className={table.shrink}>
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {documents.map((d) => {
            const filing = placed.get(d.id);
            return (
              <tr key={d.id} className={table.link} onClick={() => navigate(`/documents/${d.id}`)}>
                <td>
                  <div className={styles.titleCell}>
                    <span className={styles.fileIcon} aria-hidden>
                      <FileText />
                    </span>
                    <div className={styles.titleText}>
                      <Link to={`/documents/${d.id}`} className={`${styles.title} truncate`} onClick={(e) => e.stopPropagation()}>
                        {d.title}
                      </Link>
                      <span className={`${styles.meta} truncate`}>
                        {d.location} · {formatBytes(d.length_bytes)}
                      </span>
                    </div>
                  </div>
                </td>
                <td>
                  <div className={styles.types}>
                    {filing ? (
                      <>
                        <Badge tone="accent">{filing.kind}</Badge>
                        {filing.department && <Badge>{filing.department}</Badge>}
                      </>
                    ) : (
                      <span className="muted">Not filed yet</span>
                    )}
                  </div>
                </td>
                <td className={table.num}>{d.page_count ? formatCount(d.page_count) : <span className="muted">—</span>}</td>
                <td className={table.num}>{formatCount(d.chunks)}</td>
                <td className={`${table.num} muted`} title={new Date(d.created_at).toLocaleString()}>
                  {timeAgo(d.created_at)}
                </td>
                <td className={table.shrink}>
                  <Button
                    variant="ghost"
                    size="sm"
                    icon={<Trash2 />}
                    aria-label={`Delete ${d.title}`}
                    title="Delete"
                    onClick={(e) => {
                      e.stopPropagation();
                      onDelete(d);
                    }}
                  />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Pager({ count, offset, shown, onChange }: { count: number; offset: number; shown: number; onChange: (offset: number) => void }) {
  return (
    <div className={styles.pager}>
      <span className="muted num">
        {formatCount(offset + 1)}–{formatCount(offset + shown)} of {plural(count, "document")}
      </span>
      {count > PAGE_SIZE && (
        <div className={styles.pagerButtons}>
          <Button size="sm" icon={<ChevronLeft />} aria-label="Previous page" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - PAGE_SIZE))} />
          <Button size="sm" icon={<ChevronRight />} aria-label="Next page" disabled={offset + shown >= count} onClick={() => onChange(offset + PAGE_SIZE)} />
        </div>
      )}
    </div>
  );
}

export function DeleteDialog({ document, onClose, onDeleted }: { document: LibraryDocument | null; onClose: () => void; onDeleted?: () => void }) {
  const remove = useDeleteDocument();
  const notify = useToast();
  return (
    <Dialog
      open={document !== null}
      onClose={onClose}
      title="Delete document?"
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button
            variant="danger"
            loading={remove.isPending}
            onClick={() =>
              document &&
              remove.mutate(document.id, {
                onSuccess: () => {
                  notify(`Deleted ${document.title}`);
                  onClose();
                  onDeleted?.();
                },
                onError: (e) => notify(errorMessage(e), "danger"),
              })
            }
          >
            Delete
          </Button>
        </>
      }
    >
      <p>
        <strong className={styles.strong}>{document?.title}</strong> will be removed with its passages in the knowledge index and the original file.
        This can't be undone.
      </p>
    </Dialog>
  );
}
