/** State and effects of the review workspace; `ReviewPage` and `FormReview` render what these return. */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import { ApiError, errorMessage } from "../../api/client";
import { useForm, useFormStatus, useReviewField } from "../../api/review";
import type { Check, DocumentDetail, FormDetail, FormSummary, ReviewRequest } from "../../api/types";
import { useAssistant } from "../../app/assistant";
import { useToast } from "../../components/Toast";
import type { Box } from "./geometry";
import type { Overlay } from "./PageViewer";

/**
 * The document's selected form and page from `?form` / `?page` (a link to a page opens the form on it), the
 * selected check (selecting one shows its source page), overlays for the page, and the assistant's document.
 */
export function useWorkspace(document: DocumentDetail) {
  const [params, setParams] = useSearchParams();
  const { setCurrentDocument } = useAssistant();
  const forms = document.forms;
  const pageParam = Number(params.get("page")) || null;
  const formId =
    params.get("form") ??
    (forms.find((f) => f.status === "ok" && pageParam !== null && f.pages.includes(pageParam)) ??
      forms.find((f) => f.status === "ok") ??
      forms[0])?.id ??
    null;
  const summary = forms.find((f) => f.id === formId) ?? null;
  const form = useForm(summary?.status === "ok" ? summary.id : null);
  const [selected, setSelected] = useState<string | null>(null);
  const page = pageParam ?? summary?.pages[0] ?? 1;

  useEffect(() => {
    setCurrentDocument({ id: document.id, title: document.title });
    return () => setCurrentDocument(null);
  }, [document.id, document.title, setCurrentDocument]);

  const setPage = useCallback(
    (n: number) =>
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          next.set("page", String(n));
          return next;
        },
        { replace: true },
      ),
    [setParams],
  );

  const selectForm = (f: FormSummary) => {
    setSelected(null);
    setParams({ form: f.id, page: String(f.pages[0] ?? 1) }, { replace: true });
  };

  const checks = form.data?.checks;
  const select = useCallback(
    (field: string | null) => {
      setSelected(field);
      const source = checks?.find((c) => c.field === field)?.source;
      if (source && source.page !== page) setPage(source.page);
    },
    [checks, page, setPage],
  );

  const overlays = useMemo(() => toOverlays(form.data, page), [form.data, page]);
  return { formId, summary, form, page, setPage, selectForm, selected, select, overlays };
}

function toOverlays(form: FormDetail | undefined, page: number): Overlay[] {
  if (!form) return [];
  return form.checks.flatMap((c) =>
    c.source && c.source.page === page
      ? [{ field: c.field, box: c.source.box as Box, label: c.label, tone: c.review ? "done" : c.flags.length ? "flag" : "plain" } as Overlay]
      : [],
  );
}

/** Keeps a visible row selected and scrolled into view; `move` steps through the visible rows. */
export function useRowSelection(visible: Check[], selected: string | null, onSelect: (field: string) => void) {
  const rows = useRef(new Map<string, HTMLLIElement>());
  useEffect(() => {
    if (!visible.length) return;
    if (!selected || !visible.some((c) => c.field === selected)) onSelect(visible[0]!.field);
  }, [visible, selected, onSelect]);
  useEffect(() => {
    if (selected) rows.current.get(selected)?.scrollIntoView({ block: "nearest" });
  }, [selected]);

  const move = (step: number) => {
    const at = visible.findIndex((c) => c.field === selected);
    const next = visible[Math.min(visible.length - 1, Math.max(0, at + step))];
    if (next) onSelect(next.field);
  };
  const rowRef = (field: string) => (el: HTMLLIElement | null) => {
    if (el) rows.current.set(field, el);
    else rows.current.delete(field);
  };
  return { move, rowRef };
}

/**
 * Decisions on one form: `decide` sets (or with `null` clears) a field's decision and selects the next visible row
 * after a set; `approve` reports a 409's first undecided field to `onBlocked`. Also the field being edited, the
 * row whose decision failed and the field being saved.
 */
export function useDecide(form: FormDetail, visible: Check[], onSelect: (field: string) => void, onBlocked: (field: string) => void) {
  const notify = useToast();
  const review = useReviewField(form);
  const status = useFormStatus(form);
  const [editing, setEditing] = useState<string | null>(null);
  const [rowError, setRowError] = useState<{ field: string; message: string } | null>(null);

  const decide = (check: Check, body: ReviewRequest | null) => {
    setRowError(null);
    const at = visible.findIndex((c) => c.field === check.field);
    review.mutate(
      { field: check.field, review: body },
      {
        onSuccess: () => {
          setEditing(null);
          // Advance after a decision, so a reviewer can work down the list with the keyboard.
          const next = body && visible[at + 1];
          if (next) onSelect(next.field);
        },
        onError: (e) => setRowError({ field: check.field, message: errorMessage(e) }),
      },
    );
  };

  const approve = () =>
    status.mutate("approve", {
      onSuccess: () => notify(`${form.form_name ?? "Form"} approved`),
      onError: (e) => {
        const undecided = e instanceof ApiError ? (e.details?.undecided as string[] | undefined) : undefined;
        notify(errorMessage(e), "danger");
        if (undecided?.[0]) onBlocked(undecided[0]);
      },
    });

  return {
    decide,
    approve,
    reopen: () => status.mutate("reopen"),
    statusPending: status.isPending,
    deciding: review.isPending,
    savingField: review.isPending ? review.variables?.field : undefined,
    editing,
    setEditing,
    rowError,
  };
}

type Shortcuts = {
  current: Check | null;
  move: (step: number) => void;
  decide: (check: Check, body: ReviewRequest | null) => void;
  setEditing: (field: string | null) => void;
  paused: boolean;
};

/** `j`/`k`/arrows move, `c` confirm, `e` correct, `r` reject, `u` undo, `Esc` cancel; ignored while typing or `paused`. */
export function useReviewShortcuts(shortcuts: Shortcuts) {
  const latest = useRef(shortcuts);
  latest.current = shortcuts;
  useEffect(() => {
    const listener = (e: KeyboardEvent) => {
      const { current, move, decide, setEditing, paused } = latest.current;
      const typing = e.target instanceof Element && e.target.closest("input, textarea, select, [contenteditable], dialog");
      if (e.metaKey || e.ctrlKey || e.altKey || typing) return;
      const actions: Record<string, () => void> = {
        j: () => move(1),
        ArrowDown: () => move(1),
        k: () => move(-1),
        ArrowUp: () => move(-1),
        c: () => current && decide(current, { decision: "confirmed" }),
        e: () => current && setEditing(current.field),
        r: () => current && decide(current, { decision: "rejected" }),
        u: () => current?.review && decide(current, null),
        Escape: () => setEditing(null),
      };
      const action = actions[e.key];
      if (action && !paused) {
        e.preventDefault();
        action();
      }
    };
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  }, []);
}
