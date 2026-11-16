/** The composer's state; `Composer` renders it. */
import { useEffect, useLayoutEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { useUploadDocument } from "../../api/library";
import { useAssistant, withDocument, type ScopedDocument } from "../../app/assistant";

const LINE = 24;
const MAX_ROWS = 8;

/**
 * The question (the textarea grows to `MAX_ROWS` lines), sending (Enter sends, Shift+Enter breaks the line; not
 * while an answer or an upload is pending), and adding documents to the scope: an upload with the scope's client
 * and year is attached once stored.
 */
export function useComposer(autoFocus?: boolean) {
  const { ask, pending, stop, scope, setScope } = useAssistant();
  const [text, setText] = useState("");
  const area = useRef<HTMLTextAreaElement>(null);
  const upload = useUploadDocument();
  const uploading = upload.isPending ? (upload.variables?.file.name ?? "") : null;
  const canSend = text.trim() !== "" && !pending && uploading === null;

  useLayoutEffect(() => {
    const el = area.current;
    if (!el) return;
    el.style.height = "auto";
    const max = LINE * MAX_ROWS + el.offsetHeight - el.clientHeight + paddingY(el);
    el.style.height = `${Math.min(el.scrollHeight + el.offsetHeight - el.clientHeight, max)}px`;
    el.style.overflowY = el.scrollHeight + el.offsetHeight - el.clientHeight > max ? "auto" : "hidden";
  }, [text]);

  useEffect(() => {
    if (autoFocus) area.current?.focus();
  }, [autoFocus]);

  const submit = (e?: FormEvent) => {
    e?.preventDefault();
    if (!canSend) return;
    ask(text.trim());
    setText("");
  };

  const keyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      submit();
    }
  };

  const attach = (document: ScopedDocument) => {
    setScope((s) => withDocument(s, document));
    area.current?.focus();
  };

  const uploadFile = (file: File) =>
    upload.mutate(
      { file, client: scope.client, tax_year: scope.tax_year },
      {
        onSuccess: (doc) => attach({ id: doc.id, title: doc.title }),
      },
    );

  return { text, setText, area, submit, keyDown, attach, uploadFile, upload, uploading, canSend, pending, stop, scope, setScope };
}

function paddingY(el: HTMLElement): number {
  const style = getComputedStyle(el);
  return parseFloat(style.paddingTop) + parseFloat(style.paddingBottom);
}
