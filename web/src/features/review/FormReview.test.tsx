// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { expect, it } from "vitest";
import { useForm } from "../../api/review";
import type { FormDetail, ReviewRequest } from "../../api/types";
import { ToastProvider } from "../../components/Toast";
import { apiError, json, serve } from "../../test/api";
import { document, w2 } from "../../test/fixtures";
import { FormReview } from "./FormReview";

/** The review routes over one stored form, with the API's counting and approval rule. */
function fakeApi(form: FormDetail) {
  const calls: string[] = [];
  serve(async (request) => {
    const path = new URL(request.url).pathname;
    const field = path.match(/\/reviews\/(.+)$/)?.[1];
    calls.push(`${request.method} ${field ?? path}`);
    if (field) {
      const body = request.method === "PUT" ? ((await request.json()) as ReviewRequest) : null;
      const check = form.checks.find((c) => c.field === field)!;
      const value = body?.decision === "corrected" ? Number(String(body.value).replace(/,/g, "")) : null;
      check.review = body && { decision: body.decision, value, note: body.note ?? null, reviewer: "firm", reviewer_id: 2, updated_at: "2026-01-02T00:00:00Z" };
      form.checked = form.checks.filter((c) => c.review).length;
      form.open_flags = form.checks.filter((c) => c.flags.length && !c.review).length;
      return json(200, { data: check });
    }
    if (path.endsWith("/approve")) {
      const undecided = form.checks.filter((c) => c.flags.length && !c.review).map((c) => c.field);
      if (undecided.length) return apiError(409, "review_incomplete", "Decide every flagged field first.", { undecided });
      Object.assign(form, { review_status: "approved", approved_by: "firm", approved_at: "2026-01-02T00:00:00Z" });
    }
    return json(200, { data: form });
  });
  return calls;
}

function Review() {
  const form = useForm("f1");
  const [selected, setSelected] = useState<string | null>(null);
  return form.data ? <FormReview form={form.data} document={document()} selected={selected} onSelect={setSelected} /> : null;
}

function renderReview() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <Review />
      </ToastProvider>
    </QueryClientProvider>,
  );
  const selected = () => view.container.querySelector<HTMLElement>("[aria-current]")?.dataset.field;
  return { selected, decision: (field: string) => view.container.querySelector<HTMLElement>(`[data-field="${field}"]`)?.dataset.decision };
}

it("moves, confirms, corrects, rejects and undoes by keyboard; approves once every flag is decided", async () => {
  const calls = fakeApi(w2());
  const user = userEvent.setup();
  const { selected, decision } = renderReview();
  const approve = await screen.findByRole<HTMLButtonElement>("button", { name: "Approve" });
  expect(selected()).toBe("wages"); // Flagged filter, first row
  expect(approve.disabled).toBe(true);
  expect(screen.getByTestId("approve-reason").textContent).toMatch(/^Decide 3 flagged fields to approve/);

  await user.keyboard("j");
  expect(selected()).toBe("federal");
  await user.keyboard("{ArrowUp}");
  expect(selected()).toBe("wages");

  await user.keyboard("c");
  await waitFor(() => expect(selected()).toBe("federal")); // the next row after a decision
  expect(decision("wages")).toBe("confirmed");

  await user.keyboard("e");
  const input = screen.getByRole("textbox", { name: "Corrected value for Federal tax" });
  expect((input as HTMLInputElement).value).toBe("1000.00");
  await user.keyboard("j"); // typing, not a shortcut
  expect(selected()).toBe("federal");
  await user.clear(input);
  await user.type(input, "2,500.00{Enter}");
  await waitFor(() => expect(selected()).toBe("state"));
  expect(decision("federal")).toBe("corrected");
  expect(screen.queryByRole("textbox", { name: /Corrected value/ })).toBeNull();

  await user.keyboard("r");
  await waitFor(() => expect(decision("state")).toBe("rejected"));
  expect(selected()).toBe("state"); // last row: stays
  await user.keyboard("u");
  await waitFor(() => expect(decision("state")).toBe("none"));
  await waitFor(() => expect(screen.getByTestId("approve-reason").textContent).toMatch(/^Decide 1 flagged field to approve/));
  expect(approve.disabled).toBe(true);

  await user.keyboard("r");
  await waitFor(() => expect(approve.disabled).toBe(false));
  await user.click(approve);
  await screen.findByText("W-2 approved"); // toast
  await screen.findByText(/Approved by firm/);
  expect(calls.filter((c) => !c.startsWith("GET"))).toEqual([
    "PUT wages", "PUT federal", "PUT state", "DELETE state", "PUT state", "POST /v1/library/forms/f1/approve",
  ]);
});

it("an approval the API refuses shows the flagged field it names", async () => {
  const form = w2();
  for (const c of form.checks) c.review = { decision: "confirmed", value: null, note: null, reviewer: "firm", reviewer_id: 2, updated_at: "2026-01-02T00:00:00Z" };
  form.open_flags = 0;
  fakeApi(form);
  const user = userEvent.setup();
  const { selected } = renderReview();
  await user.click(await screen.findByRole("radio", { name: /^All/ }));
  form.checks[1]!.review = null; // undone elsewhere since this page loaded
  await user.click(screen.getByRole("button", { name: "Approve" }));
  await screen.findByText("Decide every flagged field first."); // toast
  await waitFor(() => expect(selected()).toBe("federal"));
  expect(screen.getByRole("radio", { name: /^Flagged/ }).getAttribute("aria-checked")).toBe("true");
});
