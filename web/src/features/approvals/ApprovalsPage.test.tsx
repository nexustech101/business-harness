// @vitest-environment jsdom
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import type { Approval } from "../../api/types";
import { json } from "../../test/api";
import { renderApp } from "../../test/app";
import { approval } from "../../test/fixtures";

/** The approvals routes over a stored queue: a decision executes (or rejects) the approval. */
function fakeApprovals() {
  const queue: Approval[] = [
    approval("p1"),
    approval("p2", { tool: "post_update", connector_id: "slack", assistant_name: "Marketer", arguments: { channel: "#news" } }),
    approval("old", { status: "executed", tool: "create_contact", decided_by: "owner-key", decided_at: "2026-01-02T00:00:00Z", result: "Created." }),
  ];
  const app = renderApp("/approvals", (route, { search, body, path }) => {
    if (route === "GET /v1/approvals") {
      const status = new URLSearchParams(search).get("status");
      return json(200, { data: queue.filter((a) => !status || a.status === status) });
    }
    const id = path.match(/^\/v1\/approvals\/(\w+)\/decision$/)?.[1];
    if (id) {
      const a = queue.find((x) => x.id === id)!;
      const { approve, note } = body as { approve: boolean; note: string | null };
      Object.assign(a, { status: approve ? "executed" : "rejected", result: approve ? "Sent." : null, note, decided_by: "owner-key", decided_at: "2026-01-03T00:00:00Z" });
      return json(200, { data: a });
    }
    return undefined;
  });
  return app;
}

it("shows pending approvals with their arguments and reason; Always allow and Reject decide them", async () => {
  const user = userEvent.setup();
  const { sent } = fakeApprovals();
  const list = await screen.findByRole("list", { name: "Approvals" });
  const cards = within(list).getAllByRole("listitem");
  expect(cards.map((c) => c.getAttribute("aria-label"))).toEqual(["Accountant: send_invoice", "Marketer: post_update"]);
  const first = cards[0]!;
  expect(within(first).getByLabelText("Arguments").textContent).toBe(JSON.stringify({ customer: "Lee", amount: 120 }, null, 2));
  expect(first.textContent).toContain("The order shipped, so the invoice is due.");
  expect(first.textContent).toContain("c1/send_invoice");

  await user.click(within(first).getByRole("button", { name: "Always allow" }));
  await screen.findByText("Ran send_invoice; Accountant may now use it without asking");
  await waitFor(() => expect(within(screen.getByRole("list", { name: "Approvals" })).getAllByRole("listitem")).toHaveLength(1));

  const second = screen.getByRole("listitem", { name: "Marketer: post_update" });
  await user.type(within(second).getByRole("textbox", { name: "Note on post_update" }), "Not this week");
  await user.click(within(second).getByRole("button", { name: "Reject" }));
  await screen.findByText("Nothing waiting for you");
  expect(sent("POST /v1/approvals/p1/decision")[0]!.body).toEqual({ approve: true, always: true, note: null });
  expect(sent("POST /v1/approvals/p2/decision")[0]!.body).toEqual({ approve: false, always: false, note: "Not this week" });

  // History: every status, pending first (none left), with who decided.
  await user.click(screen.getByRole("radio", { name: "All" }));
  const history = await screen.findByRole("listitem", { name: "Marketer: post_update" });
  expect(history.dataset.status).toBe("rejected");
  expect(history.textContent).toContain("Rejected by owner-key");
  expect(history.textContent).toContain("“Not this week”");
  expect(within(history).queryByRole("button", { name: "Approve" })).toBeNull();
  expect(sent("GET /v1/approvals").map((r) => r.search)).toContain("?status=pending");
  expect(sent("GET /v1/approvals").at(-1)!.search).toBe("");
});
