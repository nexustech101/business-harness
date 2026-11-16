/** State of the business profile page; `ProfilePage` and its sections render it. */
import { useEffect, useState } from "react";
import { useLocation } from "react-router";
import { useBusinessDocuments, useOrganizeDocument, useProfile, useSaveProfile } from "../../api/business";
import { errorMessage } from "../../api/client";
import { useCatalog, useConnectors } from "../../api/connectors";
import type { BusinessProfile, OrganizedDocument } from "../../api/types";
import { useAgentic, useScreenState } from "../../app/agentic";
import { useToast } from "../../components/Toast";
import { fromDraft, toDraft, type Draft, type FieldSpec, type ListSection } from "./sections";

/**
 * The profile, the section being edited (one at a time) and `commit`, which PUTs the whole profile with the
 * section's change. `/profile#<section id>` scrolls to that section once the profile is loaded.
 */
export function useProfilePage() {
  const profile = useProfile();
  const save = useSaveProfile();
  const [editing, setEditing] = useState<string | null>(null);
  const notify = useToast();
  const { track } = useAgentic();
  const { hash } = useLocation();
  const loaded = profile.data !== undefined;
  useScreenState({ detail: { section: hash.slice(1) || null, editing } });

  useEffect(() => {
    if (loaded && hash) document.getElementById(hash.slice(1))?.scrollIntoView({ block: "start" });
  }, [hash, loaded]);

  const edit = (id: string) => {
    save.reset();
    setEditing(id);
    track("select", `profile:${id}`);
  };
  const commit = (change: Partial<BusinessProfile>) => {
    if (!profile.data) return;
    track("action", `profile:${editing ?? "save"}:save`);
    save.mutate({ ...profile.data, ...change }, {
      onSuccess: () => {
        setEditing(null);
        notify("Profile saved");
      },
    });
  };
  return { profile, editing, edit, cancel: () => setEditing(null), commit, saving: save.isPending, error: save.error ? errorMessage(save.error) : null };
}

/** Form values for one object (the overview, financials, compliance); `result` converts them back onto `value`. */
export function useRecordDraft<T extends object>(fields: FieldSpec[], value: T) {
  const [draft, setDraft] = useState(() => toDraft(fields, value as Record<string, unknown>));
  return { draft, set: (key: string, v: string) => setDraft((d) => ({ ...d, [key]: v })), result: () => fromDraft(fields, draft, value) };
}

/** Form values for a list section: edit, add and remove items; `result` is the new list. */
export function useListDraft(section: ListSection, items: object[]) {
  const [rows, setRows] = useState<{ base: object; draft: Draft }[]>(() =>
    items.map((base) => ({ base, draft: toDraft(section.fields, base as Record<string, unknown>) })),
  );
  return {
    drafts: rows.map((r) => r.draft),
    set: (i: number, key: string, v: string) => setRows((all) => all.map((r, j) => (j === i ? { ...r, draft: { ...r.draft, [key]: v } } : r))),
    add: () => setRows((all) => [...all, { base: {}, draft: toDraft(section.fields, {}) }]),
    remove: (i: number) => setRows((all) => all.filter((_, j) => j !== i)),
    result: () => rows.map((r) => fromDraft(section.fields, r.draft, r.base)),
  };
}

/** For a tool's `listing_id`: its store listing and whether it is installed (then no "Connect"). */
export function useToolConnection() {
  const catalog = useCatalog();
  const connectors = useConnectors();
  return (listingId: string | null | undefined) => ({
    listing: listingId ? catalog.data?.find((l) => l.id === listingId) : undefined,
    installed: (connectors.data ?? []).some((c) => c.listing_id === listingId),
  });
}

/** Organized documents and the inline edit of one row's department and kind (PUT /v1/business/documents/{id}). */
export function useOrganizedDocuments() {
  const documents = useBusinessDocuments();
  const organize = useOrganizeDocument();
  const notify = useToast();
  const [editing, setEditing] = useState<{ id: string; department: string; kind: string } | null>(null);
  return {
    documents, editing,
    start: (d: OrganizedDocument) => setEditing({ id: d.document_id, department: d.department ?? "", kind: d.kind }),
    change: (change: Partial<{ department: string; kind: string }>) => setEditing((e) => e && { ...e, ...change }),
    cancel: () => setEditing(null),
    save: (d: OrganizedDocument) =>
      editing &&
      organize.mutate(
        { id: d.document_id, body: { department: editing.department || null, kind: editing.kind.trim(), summary: d.summary } },
        { onSuccess: () => setEditing(null), onError: (e) => notify(errorMessage(e), "danger") },
      ),
    saving: organize.isPending,
  };
}
