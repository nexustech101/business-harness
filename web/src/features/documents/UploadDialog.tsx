import { CheckCircle2, CircleAlert, FileUp, X } from "lucide-react";
import { useRef, useState, type DragEvent } from "react";
import { Link } from "react-router";
import { useStats } from "../../api/library";
import { Button } from "../../components/Button";
import { Dialog } from "../../components/Dialog";
import { Field, Input } from "../../components/Field";
import { Spinner } from "../../components/Spinner";
import { formatBytes, plural } from "../../lib/format";
import { useUploadQueue, type UploadItem } from "./hooks";
import styles from "./UploadDialog.module.css";

const ACCEPT = ".pdf,.png,.jpg,.jpeg,.tif,.tiff,.bmp,.webp,.txt,.md,.csv,.xlsx";

/** Files are sent one at a time (the API processes uploads one per extraction slot); each shows its own result. */
export function UploadDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const clients = useStats().data?.clients.flatMap((c) => (c.client ? [c.client] : [])) ?? [];
  const { items, add, remove, start, clear, running, remaining } = useUploadQueue();
  const [client, setClient] = useState("");
  const [year, setYear] = useState("");
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const close = () => {
    if (running) return;
    clear();
    onClose();
  };

  const drop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    add(e.dataTransfer.files);
  };

  return (
    <Dialog
      open={open}
      onClose={close}
      title="Upload documents"
      wide
      footer={
        <>
          <Button onClick={close} disabled={running}>
            {items.length > 0 && remaining === 0 ? "Done" : "Cancel"}
          </Button>
          <Button variant="primary" onClick={() => start(client, year)} loading={running} disabled={remaining === 0}>
            {remaining > 0 ? `Upload ${plural(remaining, "file")}` : "Upload"}
          </Button>
        </>
      }
    >
      <div className={styles.body}>
        <div className={styles.fields}>
          <Field label="Client" hint="Applies to every file in this upload.">
            <Input value={client} onChange={(e) => setClient(e.target.value)} list="upload-clients" placeholder="e.g. Gonzalez" disabled={running} />
            <datalist id="upload-clients">
              {clients.map((c) => (
                <option key={c} value={c} />
              ))}
            </datalist>
          </Field>
          <Field label="Tax year" hint="Used when the form has none.">
            <Input value={year} onChange={(e) => setYear(e.target.value.replace(/\D/g, "").slice(0, 4))} inputMode="numeric" placeholder="e.g. 2025" disabled={running} />
          </Field>
        </div>
        <button
          type="button"
          className={`${styles.drop} ${dragging ? styles.dragging : ""}`}
          onClick={() => input.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={drop}
          disabled={running}
        >
          <FileUp aria-hidden />
          <span className={styles.dropTitle}>Drop files here or click to choose</span>
          <span className={styles.dropHint}>PDF, PNG, JPEG, TIFF, WEBP, TXT, MD, CSV or XLSX</span>
        </button>
        <input
          ref={input}
          type="file"
          multiple
          accept={ACCEPT}
          hidden
          data-testid="upload-input"
          onChange={(e) => {
            add(e.target.files);
            e.target.value = "";
          }}
        />
        {items.length > 0 && (
          <ul className={styles.list}>
            {items.map((item, i) => (
              <li key={`${item.file.name}-${i}`} className={styles.item} data-state={item.state}>
                <ItemIcon state={item.state} />
                <div className={styles.itemText}>
                  <span className={`${styles.name} truncate`}>{item.file.name}</span>
                  <span className={styles.detail}>
                    <ItemDetail item={item} />
                  </span>
                </div>
                {item.state === "queued" && !running && (
                  <Button variant="ghost" size="sm" icon={<X />} aria-label={`Remove ${item.file.name}`} onClick={() => remove(i)} />
                )}
                {item.result && (
                  <Link to={`/documents/${item.result.id}`} onClick={close} className={styles.open}>
                    Review
                  </Link>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </Dialog>
  );
}

function ItemIcon({ state }: { state: UploadItem["state"] }) {
  if (state === "uploading") return <Spinner size={16} />;
  if (state === "done") return <CheckCircle2 className={styles.ok} aria-label="Done" />;
  if (state === "failed") return <CircleAlert className={styles.failed} aria-label="Failed" />;
  return <FileUp className={styles.queued} aria-hidden />;
}

function ItemDetail({ item }: { item: UploadItem }) {
  if (item.state === "uploading") return <>Extracting forms…</>;
  if (item.state === "failed") return <span className={styles.failed}>{item.error}</span>;
  if (item.result) {
    const extracted = item.result.forms.filter((f) => f.status === "ok").length;
    return (
      <>
        {item.result.forms.length ? plural(extracted, "form") + " extracted" : "Stored as text"}
        {item.result.open_flags > 0 && ` · ${plural(item.result.open_flags, "flagged field")}`}
      </>
    );
  }
  return <>{formatBytes(item.file.size)} · waiting</>;
}
