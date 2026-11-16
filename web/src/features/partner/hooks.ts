/** State of the partner page; `PartnerPage` renders it. */
import { useCallback, useEffect, useRef, useState, type DragEvent, type FormEvent, type KeyboardEvent } from "react";
import { usePartnerChat } from "../../api/business";
import { errorMessage } from "../../api/client";
import { useUploadDocument } from "../../api/library";
import type { PartnerResponse } from "../../api/types";
import { useAgentic, useScreenState } from "../../app/agentic";

export type PartnerTurn = { role: "user"; content: string } | { role: "assistant"; content: string; reply: PartnerResponse };
export type Uploaded = { id: string; title: string };
export type UploadState = { id: number; name: string; state: "uploading" | "failed"; error?: string };

/**
 * The message that tells the partner what was uploaded: it reads the documents, files them, records what they
 * reveal about the business, then continues the discovery with what is still unknown.
 */
export function describeUploads(documents: Uploaded[]): string {
  const lines = documents.map((d) => `- ${d.title} (document id ${d.id})`);
  const what = documents.length === 1 ? "a document" : `${documents.length} documents`;
  return (
    `I uploaded ${what} for you to organize into the business profile:\n${lines.join("\n")}\n` +
    "Read them, file each one, and add what they tell you about the business to the profile. " +
    "Then tell me what you learned and ask me what you still need to know."
  );
}

/**
 * The partner conversation, kept in this page's memory (the API is stateless: every turn sends the whole
 * conversation). Each message carries `ui_state`: the screen "Ask the partner" was used on when there is one
 * (taken once), else this page's. The reply's flags refetch the profile, documents, assistants and workspace
 * (`usePartnerChat`).
 */
/** `PartnerRequest.messages` allows 50: the newest turns, starting at a user turn. The profile and interview travel in
 * the server's own state message, so older turns are not needed to continue. */
export const MAX_TURNS = 50;

export function recent<T extends { role: string }>(turns: T[]): T[] {
  const tail = turns.slice(-MAX_TURNS);
  const start = tail.findIndex((t) => t.role === "user");
  return start < 0 ? tail : tail.slice(start);
}

export function usePartnerConversation() {
  const chat = usePartnerChat();
  const { uiState, attached, clearAttached, track } = useAgentic();
  const [turns, setTurns] = useState<PartnerTurn[]>([]);
  const controller = useRef<AbortController | null>(null);
  const conversation = useRef(0);
  useScreenState({ detail: { turns: turns.length, attached: attached?.page ?? null } });

  const send = useCallback(
    (history: PartnerTurn[]) => {
      controller.current?.abort();
      const abort = (controller.current = new AbortController());
      const id = conversation.current;
      const ui_state = attached ?? uiState();
      clearAttached();
      chat.mutate(
        { messages: recent(history).map(({ role, content }) => ({ role, content })), ui_state, signal: abort.signal },
        { onSuccess: (reply) => id === conversation.current && setTurns([...history, { role: "assistant", content: reply.message.content, reply }]) },
      );
    },
    [chat, attached, uiState, clearAttached],
  );

  const ask = useCallback(
    (text: string) => {
      const history: PartnerTurn[] = [...turns, { role: "user", content: text }];
      setTurns(history);
      track("action", "partner:send");
      send(history);
    },
    [turns, send, track],
  );

  return {
    turns, ask, attached,
    pending: chat.isPending,
    failure: { error: chat.error, stopped: chat.error?.name === "AbortError", retry: () => send(turns) },
    stop: () => controller.current?.abort(),
    reset: () => {
      conversation.current++;
      controller.current?.abort();
      chat.reset();
      setTurns([]);
    },
  };
}

/**
 * Files dropped on the page or picked with "+": each is stored with `extract=false` (one after another), then,
 * once the partner is free, one message lists what was uploaded (ids and titles) so it organizes them.
 */
export function usePartnerUploads(ask: (text: string) => void, busy: boolean) {
  const upload = useUploadDocument();
  const { track } = useAgentic();
  const [states, setStates] = useState<UploadState[]>([]);
  const nextUpload = useRef(0); // ids for the upload rows: two files may share a name
  const [done, setDone] = useState<Uploaded[]>([]);
  const running = states.some((s) => s.state === "uploading");

  const add = async (files: FileList | File[] | null) => {
    const list = Array.from(files ?? []);
    if (!list.length) return;
    track("action", "partner:upload", { files: list.length });
    const first = nextUpload.current;
    nextUpload.current += list.length;
    setStates((all) => [...all, ...list.map((f, i): UploadState => ({ id: first + i, name: f.name, state: "uploading" }))]);
    for (const [i, file] of list.entries()) {
      const id = first + i;
      try {
        const doc = await upload.mutateAsync({ file, extract: false });
        setDone((all) => [...all, { id: doc.id, title: doc.title }]);
        setStates((all) => all.filter((s) => s.id !== id));
      } catch (error) {
        setStates((all) => all.map((s) => (s.id === id ? { ...s, state: "failed", error: errorMessage(error) } : s)));
      }
    }
  };

  useEffect(() => {
    if (!done.length || running || busy) return;
    ask(describeUploads(done));
    setDone([]);
  }, [done, running, busy, ask]);

  return { add, states, waiting: done, dismiss: (id: number) => setStates((all) => all.filter((s) => s.id !== id)) };
}

/** The message box: Enter sends, Shift+Enter breaks the line; not while the partner is answering. */
export function usePartnerComposer(ask: (text: string) => void, pending: boolean) {
  const [text, setText] = useState("");
  const canSend = text.trim() !== "" && !pending;
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
  return { text, setText, submit, keyDown, canSend };
}

/** Drag-and-drop over the page: `over` while files are dragged over it. */
export function useDropZone(onFiles: (files: FileList) => void) {
  const [over, setOver] = useState(false);
  const depth = useRef(0);
  const hasFiles = (e: DragEvent) => e.dataTransfer.types.includes("Files");
  return {
    over,
    handlers: {
      onDragEnter: (e: DragEvent) => {
        if (!hasFiles(e)) return;
        depth.current++;
        setOver(true);
      },
      onDragLeave: () => {
        depth.current = Math.max(0, depth.current - 1);
        if (!depth.current) setOver(false);
      },
      onDragOver: (e: DragEvent) => {
        if (hasFiles(e)) e.preventDefault();
      },
      onDrop: (e: DragEvent) => {
        if (!hasFiles(e)) return;
        e.preventDefault();
        depth.current = 0;
        setOver(false);
        onFiles(e.dataTransfer.files);
      },
    },
  };
}
