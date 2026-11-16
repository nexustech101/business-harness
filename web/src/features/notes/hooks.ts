/** State of the notes board; `NotesPage` renders it. */
import { useState, type FormEvent } from "react";
import { useSearchParams } from "react-router";
import { useNotes, usePostNote } from "../../api/business";
import { errorMessage } from "../../api/client";
import type { Note } from "../../api/types";
import { useAgentic, useScreenState } from "../../app/agentic";
import { useToast } from "../../components/Toast";

/**
 * The board grouped by topic (topics ordered by their newest note; notes newest first as the API sends them),
 * narrowed by `?topic=`, and the owner's post form (the topic defaults to the one shown).
 */
export function useNotesBoard() {
  const notes = useNotes();
  const [params, setParams] = useSearchParams();
  const topic = params.get("topic");
  const post = usePostNote();
  const notify = useToast();
  const { track } = useAgentic();
  const [draft, setDraft] = useState({ topic: topic ?? "", text: "" });
  useScreenState({ detail: { topic } });

  // Topics compare case-insensitively, as in the API; a group is shown under its newest note's spelling.
  const groups = new Map<string, [string, Note[]]>();
  for (const note of notes.data ?? []) {
    const [label, list] = groups.get(note.topic.toLowerCase()) ?? [note.topic, []];
    groups.set(note.topic.toLowerCase(), [label, [...list, note]]);
  }
  const topics = [...groups.values()].map(([label]) => label);
  const shown = topic ? [[topic, groups.get(topic.toLowerCase())?.[1] ?? []] as const] : [...groups.values()];

  const selectTopic = (next: string | null) => {
    setParams(next ? { topic: next } : {}, { replace: true });
    setDraft((d) => ({ ...d, topic: next ?? d.topic }));
    track("select", next ? `topic:${next}` : "topic:all");
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const body = { topic: draft.topic.trim(), text: draft.text.trim() };
    if (!body.topic || !body.text) return;
    track("action", "note:post", { topic: body.topic });
    post.mutate(body, {
      onSuccess: () => {
        setDraft((d) => ({ ...d, text: "" }));
        notify(`Posted to ${body.topic}`);
      },
    });
  };

  return { notes, topics, topic, shown, selectTopic, draft, setDraft, submit, posting: post.isPending, postError: post.error ? errorMessage(post.error) : null };
}
