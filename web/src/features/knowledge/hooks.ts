/** State of the knowledge page; `KnowledgePage` renders it. */
import { useState, type FormEvent } from "react";
import { useSearchParams } from "react-router";
import { useKnowledgeMap, useKnowledgeSearch, type KnowledgeFilter } from "../../api/knowledge";
import { useAgentic, useScreenState } from "../../app/agentic";

export const VIEWS = ["all", "files", "workspace", "unused"] as const;
export type View = (typeof VIEWS)[number];

const PAGE = 50;
const FILTERS: Record<View, KnowledgeFilter> = {
  all: {},
  files: { origin: "upload" },
  workspace: { origin: "workspace" },
  unused: { unused: true },
};

/**
 * The map of the index. `?view=` picks what is listed (everything, files, the workspace's own records, or only
 * sources with passages never retrieved, most first), `?source=` the source whose passages are open; the title
 * filter and "Show more" are page state.
 */
export function useKnowledge() {
  const [params, setParams] = useSearchParams();
  const view = (VIEWS as readonly string[]).includes(params.get("view") ?? "") ? (params.get("view") as View) : "all";
  const open = params.get("source");
  const [q, setQ] = useState("");
  const [limit, setLimit] = useState(PAGE);
  const { track } = useAgentic();
  const map = useKnowledgeMap({ ...FILTERS[view], q: q.trim() || undefined, limit });
  useScreenState({ entity: open ? { kind: "document", id: open, title: "" } : null, detail: { view, q } });

  const set = (key: string, value: string | null) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (value) next.set(key, value);
        else next.delete(key);
        return next;
      },
      { replace: true },
    );

  return {
    map, view, q, open,
    setQ: (text: string) => {
      setQ(text);
      setLimit(PAGE);
    },
    setView: (next: View) => {
      track("select", `knowledge:${next}`);
      setLimit(PAGE);
      set("view", next === "all" ? null : next);
    },
    toggle: (id: string) => set("source", open === id ? null : id),
    /** Open a source (a search result's): it stays open when it already is. */
    show: (id: string) => set("source", id),
    close: () => set("source", null),
    hasMore: (map.data?.count ?? 0) > (map.data?.items.length ?? 0),
    more: () => setLimit((n) => n + PAGE),
  };
}

/** The search box: one query at a time over files and workspace records. */
export function useSearchBox() {
  const search = useKnowledgeSearch();
  const { track } = useAgentic();
  const [text, setText] = useState("");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const query = text.trim();
    if (!query) return;
    track("action", "knowledge:search");
    search.mutate(query);
  };
  return {
    text, setText, submit,
    searching: search.isPending,
    error: search.error,
    result: search.data,
    asked: search.variables,
    clear: () => {
      search.reset();
      setText("");
    },
  };
}
