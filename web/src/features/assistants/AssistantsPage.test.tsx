// @vitest-environment jsdom
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import type { AssistantInfo, AssistantSpec } from "../../api/types";
import { deferred, json } from "../../test/api";
import { renderApp } from "../../test/app";
import { assistant, specSchema } from "../../test/fixtures";
import { TEMPLATE } from "./specSchema";

it("checks the JSON spec against the schema while typing, creates the assistant and opens it", async () => {
  const user = userEvent.setup();
  const stored: AssistantInfo[] = [];
  const { sent } = renderApp("/assistants", (route, { body }) => {
    if (route === "GET /v1/assistants/schema") return json(200, { data: specSchema });
    if (route === "GET /v1/assistants") return json(200, { data: stored });
    if (route === "POST /v1/assistants") {
      stored.push(assistant("a9", (body as AssistantSpec).name, "draft", body as AssistantSpec));
      return json(201, { data: stored[0] });
    }
    if (route === "GET /v1/assistants/a9") return json(200, { data: stored[0] });
    if (route === "GET /v1/assistants/a9/context")
      return json(200, { data: { layers: [{ name: "business", text: "Acme Bakery sells bread." }, { name: "role", text: "You keep the books." }], tools: ["search_documents", "post_note"], chars: 42 } });
    return undefined;
  });
  await screen.findByText("No assistants yet");
  await user.click(screen.getByRole("button", { name: "New assistant" }));
  const editor = screen.getByRole("textbox", { name: "Assistant spec (JSON)" }) as HTMLTextAreaElement;
  expect(JSON.parse(editor.value)).toEqual(TEMPLATE);
  const create = screen.getByRole("button", { name: "Create assistant" }) as HTMLButtonElement;
  await waitFor(() => expect(create.disabled).toBe(false)); // valid once the schema arrived

  const replace = async (text: string) => {
    await user.clear(editor);
    await user.click(editor);
    await user.paste(text);
  };
  await replace('{"name": "Marketer",');
  expect(within(screen.getByRole("list", { name: "Spec errors" })).getByRole("listitem").textContent).toMatch(/^Not valid JSON: /);
  expect(create.disabled).toBe(true);
  await replace('{"name": "", "policy": {"default": "maybe"}}');
  expect(within(screen.getByRole("list", { name: "Spec errors" })).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
    "role is required", "name must not be empty", 'policy.default must be one of "auto", "ask", "deny"',
  ]);
  expect(editor.getAttribute("aria-invalid")).toBe("true");

  await user.click(screen.getByRole("button", { name: "Use template" }));
  expect(screen.queryByRole("list", { name: "Spec errors" })).toBeNull();
  await user.click(create);
  expect(sent("POST /v1/assistants")[0]!.body).toEqual(TEMPLATE);

  // The new assistant's page: status, what it sees, its spec.
  await screen.findByRole("heading", { name: "Accountant" });
  expect(screen.getByRole("radio", { name: "Draft" }).getAttribute("aria-checked")).toBe("true");
  expect((screen.getByRole("button", { name: "Run" }) as HTMLButtonElement).disabled).toBe(true); // drafts don't run
  expect(await screen.findByText("42 characters")).toBeTruthy();
  expect(within(screen.getByLabelText("Tools offered")).getAllByText(/./).map((c) => c.textContent)).toEqual(["search_documents", "post_note"]);
  expect(screen.getByText("No connectors in its spec: add connector ids to set a mode per tool.")).toBeTruthy();
});

it("sets per-tool modes for its connectors' write tools and shows each tool run's outcome", async () => {
  const user = userEvent.setup();
  let saved = assistant("a1", "Accountant", "active", { connectors: ["qb"] });
  const { sent } = renderApp("/assistants/a1", (route, { body }) => {
    if (route === "GET /v1/assistants/schema") return json(200, { data: specSchema });
    if (route === "GET /v1/assistants/a1") return json(200, { data: saved });
    if (route === "PUT /v1/assistants/a1") {
      saved = { ...saved, ...(body as AssistantSpec), updated_at: "2026-01-05T00:00:00Z" };
      return json(200, { data: saved });
    }
    if (route === "GET /v1/assistants/a1/context") return json(200, { data: { layers: [], tools: [], chars: 0 } });
    if (route === "GET /v1/connectors/qb/tools")
      return json(200, {
        data: [
          { connector_id: "qb", name: "list_invoices", description: "List invoices", read_only: true, input_schema: {} },
          { connector_id: "qb", name: "send_invoice", description: "Send an invoice", read_only: false, input_schema: {} },
        ],
      });
    if (route === "POST /v1/assistants/a1/run")
      return json(200, {
        data: {
          message: { role: "assistant", content: "I listed the invoices and asked to send one." }, model: "fake", usage: {},
          tool_runs: [
            { connector_id: "qb", tool: "list_invoices", arguments: {}, read_only: true, outcome: "ran", approval_id: null, result: "3 invoices" },
            { connector_id: "qb", tool: "send_invoice", arguments: { id: 7 }, read_only: false, outcome: "pending_approval", approval_id: "p1", result: "Waiting." },
          ],
        },
      });
    return undefined;
  });
  const modes = await screen.findByRole("list", { name: "Per-tool modes" });
  expect(within(modes).getAllByRole("combobox").map((s) => s.getAttribute("aria-label"))).toEqual(["Mode for qb/send_invoice"]); // writes only
  expect(screen.getByText("1 read-only tool always run.")).toBeTruthy();
  await user.click(screen.getByRole("radio", { name: "Deny" }));
  await user.selectOptions(within(modes).getByRole("combobox"), "auto");
  await user.click(screen.getByRole("button", { name: "Save policy" }));
  await screen.findByText("Policy saved");
  expect((sent("PUT /v1/assistants/a1")[0]!.body as AssistantSpec).policy).toEqual({ default: "deny", tools: { "qb/send_invoice": "auto" } });

  await user.type(screen.getByRole("textbox", { name: "Task" }), "Send the overdue invoices");
  await user.click(screen.getByRole("button", { name: "Run" }));
  const runs = await screen.findByRole("list", { name: "Tool calls" });
  const items = within(runs).getAllByRole("listitem");
  expect(items.map((li) => li.dataset.outcome)).toEqual(["ran", "pending_approval"]);
  expect(within(items[1]!).getByRole("link", { name: "Review in approvals" }).getAttribute("href")).toBe("/approvals");
  expect(screen.getByText("I listed the invoices and asked to send one.")).toBeTruthy();
  expect(sent("POST /v1/assistants/a1/run")[0]!.body).toEqual({ messages: [{ role: "user", content: "Send the overdue invoices" }] });
});

it("a run in progress is not started again by Ctrl+Enter", async () => {
  const user = userEvent.setup();
  const answer = deferred<Response>();
  const { sent } = renderApp("/assistants/a1", (route) => {
    if (route === "GET /v1/assistants/schema") return json(200, { data: specSchema });
    if (route === "GET /v1/assistants/a1") return json(200, { data: assistant("a1", "Accountant") });
    if (route === "GET /v1/assistants/a1/context") return json(200, { data: { layers: [], tools: [], chars: 0 } });
    if (route === "POST /v1/assistants/a1/run") return answer.promise;
    return undefined;
  });
  const task = await screen.findByRole("textbox", { name: "Task" });
  await user.type(task, "Send the overdue invoices");
  await user.keyboard("{Control>}{Enter}{/Control}");
  await user.keyboard("{Control>}{Enter}{/Control}");
  answer.resolve(json(200, { data: { message: { role: "assistant", content: "Done." }, model: "fake", usage: {}, tool_runs: [] } }));
  await screen.findByText("Done.");
  expect(sent("POST /v1/assistants/a1/run")).toHaveLength(1);
});
