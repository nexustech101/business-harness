import { ArrowLeft, ArrowUp, ChevronRight, CircleAlert, FileText, FolderOpen, Plus, Search, Upload, X } from "lucide-react";
import { useDeferredValue, useEffect, useRef, useState } from "react";
import { errorMessage } from "../../api/client";
import { useDocuments } from "../../api/library";
import type { ScopedDocument } from "../../app/assistant";
import { Menu, MenuHeading, MenuItem, MenuSeparator } from "../../components/Menu";
import { Spinner } from "../../components/Spinner";
import { useComposer } from "./hooks";
import styles from "./Composer.module.css";

const ACCEPT = ".pdf,.png,.jpg,.jpeg,.tif,.tiff,.bmp,.webp,.txt,.md,.csv,.xlsx";

type Props = {
  /** Where menus open: above a composer docked at the bottom, below one in the middle of the page. */
  placement: "top" | "bottom";
  minRows?: number;
  autoFocus?: boolean;
};

/**
 * The question box shared by the page and the panel: auto-growing textarea (Enter sends, Shift+Enter breaks the
 * line), the "+" menu (upload or attach a document), the chips of attached documents, and send / stop.
 */
export function Composer({ placement, minRows = 1, autoFocus }: Props) {
  const { text, setText, area, submit, keyDown, attach, uploadFile, upload, uploading, canSend, pending, stop, scope, setScope } = useComposer(autoFocus);

  return (
    <form className={styles.composer} onSubmit={submit} onClick={(e) => e.target === e.currentTarget && area.current?.focus()}>
      <textarea
        ref={area}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={keyDown}
        placeholder={placeholder(scope.documents)}
        rows={minRows}
        aria-label="Question"
        maxLength={20000}
        className={styles.input}
      />
      {upload.isError && (
        <div className={styles.uploadError} role="alert">
          <CircleAlert aria-hidden />
          <span>Upload failed: {errorMessage(upload.error)}</span>
          <button type="button" aria-label="Dismiss" onClick={() => upload.reset()}>
            <X />
          </button>
        </div>
      )}
      <div className={styles.toolbar}>
        <div className={styles.tools}>
          <AddMenu placement={placement} onUpload={uploadFile} onAttach={attach} attached={scope.documents} disabled={uploading !== null} />
          {uploading !== null ? (
            <span className={`${styles.chip} ${styles.uploading}`} role="status">
              <Spinner size={13} />
              <span className="truncate">{uploading}</span>
              <span className={styles.chipNote}>Uploading…</span>
            </span>
          ) : scope.documents.length ? (
            scope.documents.map((d) => (
              <span key={d.id} className={styles.chip} data-testid="scope-document">
                <FileText aria-hidden />
                <span className="truncate" title={d.title}>
                  {d.title}
                </span>
                <button
                  type="button"
                  aria-label={`Remove ${d.title}`}
                  onClick={() => setScope((s) => ({ ...s, documents: s.documents.filter((x) => x.id !== d.id) }))}
                >
                  <X />
                </button>
              </span>
            ))
          ) : null}
        </div>
        {pending ? (
          <button type="button" className={`${styles.send} ${styles.stop}`} onClick={stop} aria-label="Stop" title="Stop">
            <svg viewBox="0 0 10 10" aria-hidden>
              <rect width="10" height="10" rx="2.5" />
            </svg>
          </button>
        ) : (
          <button type="submit" className={styles.send} disabled={!canSend} aria-label="Send" title="Send (Enter)">
            <ArrowUp aria-hidden />
          </button>
        )}
      </div>
    </form>
  );
}

function placeholder(documents: ScopedDocument[]): string {
  if (documents.length === 1) return `Ask about ${documents[0]!.title}`;
  if (documents.length > 1) return "Ask about these documents";
  return "Ask about your documents and your business";
}

type AddMenuProps = {
  placement: "top" | "bottom";
  onUpload: (file: File) => void;
  onAttach: (document: ScopedDocument) => void;
  attached: ScopedDocument[];
  disabled: boolean;
};

function AddMenu({ placement, onUpload, onAttach, attached, disabled }: AddMenuProps) {
  const [view, setView] = useState<"root" | "attach">("root");
  const file = useRef<HTMLInputElement>(null);
  return (
    <>
      <Menu
        label="Add a document"
        title="Add a document"
        placement={placement}
        disabled={disabled}
        triggerClassName={styles.plus}
        trigger={() => <Plus aria-hidden />}
        onOpenChange={(open) => !open && setView("root")}
      >
        {(close) =>
          view === "root" ? (
            <>
              <MenuItem
                icon={<Upload />}
                onClick={() => {
                  close();
                  file.current?.click();
                }}
              >
                Upload a document
              </MenuItem>
              <MenuItem icon={<FolderOpen />} hint={<ChevronRight className={styles.hintIcon} aria-hidden />} onClick={() => setView("attach")}>
                Attach a library document
              </MenuItem>
            </>
          ) : (
            <DocumentPicker
              attached={attached}
              onBack={() => setView("root")}
              onPick={(d) => {
                onAttach(d);
                close();
              }}
            />
          )
        }
      </Menu>
      <input
        ref={file}
        type="file"
        accept={ACCEPT}
        hidden
        data-testid="assistant-upload"
        onChange={(e) => {
          const picked = e.target.files?.[0];
          e.target.value = "";
          if (picked) onUpload(picked);
        }}
      />
    </>
  );
}

function DocumentPicker({ attached, onPick, onBack }: { attached: ScopedDocument[]; onPick: (d: ScopedDocument) => void; onBack: () => void }) {
  const [q, setQ] = useState("");
  const query = useDeferredValue(q.trim());
  const { data, isPending } = useDocuments({ q: query || undefined, limit: 8 });
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => input.current?.focus(), []);
  const ids = new Set(attached.map((d) => d.id));
  const documents = data?.documents ?? [];
  return (
    <div className={styles.picker}>
      <div className={styles.pickerHead}>
        <button type="button" className={styles.back} aria-label="Back" onClick={onBack}>
          <ArrowLeft />
        </button>
        <label className={styles.search}>
          <Search aria-hidden />
          <input
            ref={input}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              const first = documents.find((d) => !ids.has(d.id));
              if (e.key === "Enter" && first) {
                e.preventDefault();
                onPick({ id: first.id, title: first.title });
              }
            }}
            placeholder="Search documents"
            aria-label="Search documents"
          />
        </label>
      </div>
      <MenuSeparator />
      {isPending ? (
        <div className={styles.pickerNote}>
          <Spinner size={13} /> Loading…
        </div>
      ) : documents.length === 0 ? (
        <div className={styles.pickerNote}>{query ? "No matching documents" : "No documents yet"}</div>
      ) : (
        <>
          <MenuHeading>{query ? "Matching documents" : "Recent documents"}</MenuHeading>
          {documents.map((d) => (
            <MenuItem
              key={d.id}
              icon={<FileText />}
              disabled={ids.has(d.id)}
              onClick={() => onPick({ id: d.id, title: d.title })}
            >
              {d.title}
            </MenuItem>
          ))}
        </>
      )}
    </div>
  );
}
