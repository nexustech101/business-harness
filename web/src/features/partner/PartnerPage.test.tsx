// @vitest-environment jsdom
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import type { InterviewState, PartnerResponse } from "../../api/types";
import { json, sentForm } from "../../test/api";
import { renderApp } from "../../test/app";
import { document, workspace } from "../../test/fixtures";
import { MAX_TURNS, recent } from "./hooks";

type Body = { messages: { role: string; content: string }[]; ui_state: unknown };

function reply(content: string, change: Partial<PartnerResponse> = {}): PartnerResponse {
  return {
    message: { role: "assistant", content }, sources: [], tool_calls: [], model: "fake", usage: {},
    profile_changed: false, assistants_changed: false, interview: workspace().interview, ...change,
  };
}

it("sends the conversation with the screen state; profile_changed refetches the workspace", async () => {
  const user = userEvent.setup();
  let name = "Acme Bakery";
  const { sent } = renderApp("/notes", (route) => {
    if (route === "GET /v1/business/notes") return json(200, { data: [] });
    if (route === "GET /v1/workspace") return json(200, { data: workspace({ business_name: name }) });
    if (route === "POST /v1/partner/chat") {
      name = "Acme Bakery & Cafe";
      return json(200, { data: reply("Noted: you also run a cafe. Who keeps the books?", { profile_changed: true }) });
    }
    return undefined;
  });
  await waitFor(() => expect(screen.getByTestId("business-name").textContent).toBe("Acme Bakery"));
  // "Ask the partner" on the notes board: the next message carries that screen.
  await user.click(screen.getByRole("button", { name: "Ask the partner" }));
  await screen.findByText(/Sending with the screen you came from/);
  await user.type(screen.getByRole("textbox", { name: "Message" }), "We also run a cafe{Enter}");
  await screen.findByText("Noted: you also run a cafe. Who keeps the books?");
  const first = sent("POST /v1/partner/chat")[0]!.body as Body;
  expect(first).toEqual({ messages: [{ role: "user", content: "We also run a cafe" }], ui_state: { page: "/notes", entity: null, detail: { topic: null } } });
  await waitFor(() => expect(screen.getByTestId("business-name").textContent).toBe("Acme Bakery & Cafe")); // refetched

  // The next message: the whole conversation, this page's state.
  expect(screen.queryByText(/Sending with the screen you came from/)).toBeNull();
  await user.type(screen.getByRole("textbox", { name: "Message" }), "I do{Enter}");
  await waitFor(() => expect(sent("POST /v1/partner/chat")).toHaveLength(2));
  const second = sent("POST /v1/partner/chat")[1]!.body as Body;
  expect(second.messages.map((m) => m.role)).toEqual(["user", "assistant", "user"]);
  expect(second.ui_state).toMatchObject({ page: "/partner", entity: null });
});

it("uploads files, then tells the partner their ids and titles; next questions ask", async () => {
  const user = userEvent.setup();
  const interview: InterviewState = { ...workspace().interview, next: [{ id: "finance.method", area: "finance", text: "Cash or accrual?", purpose: "Sets up the books.", fills: [] }] };
  const { sent } = renderApp("/partner", (route, { request }) => {
    if (route === "GET /v1/business/interview") return json(200, { data: interview });
    if (route === "POST /v1/library/documents") {
      const file = sentForm(request).get("file") as File;
      return json(201, { data: document(`d-${file.name}`, file.name.replace(".pdf", "")) });
    }
    if (route === "POST /v1/partner/chat") return json(200, { data: reply("Filed both under Sales.", { interview }) });
    return undefined;
  });
  const files = [new File(["%PDF"], "prices.pdf", { type: "application/pdf" }), new File(["%PDF"], "menu.pdf", { type: "application/pdf" })];
  await user.upload(await screen.findByTestId("partner-upload"), files);
  await screen.findByText("Filed both under Sales.");
  const uploads = sent("POST /v1/library/documents").map((r) => sentForm(r.request));
  expect(uploads.map((f) => (f.get("file") as File).name)).toEqual(["prices.pdf", "menu.pdf"]);
  expect((sent("POST /v1/partner/chat")[0]!.body as Body).messages).toEqual([
    {
      role: "user",
      content: "I uploaded 2 documents for you to organize into the business profile:\n- prices (document id d-prices.pdf)\n- menu (document id d-menu.pdf)\n" +
        "Read them, file each one, and add what they tell you about the business to the profile. " +
        "Then tell me what you learned and ask me what you still need to know.",
    },
  ]);

  const next = screen.getByRole("list", { name: "Next questions" });
  await user.click(within(next).getByRole("button", { name: "Cash or accrual?" }));
  await waitFor(() => expect(sent("POST /v1/partner/chat")).toHaveLength(2));
  expect((sent("POST /v1/partner/chat")[1]!.body as Body).messages.at(-1)).toEqual({ role: "user", content: "Ask me this next: Cash or accrual?" });
});

it("sends at most the newest 50 turns, starting with the owner's", () => {
  const turns = Array.from({ length: 61 }, (_, i) => ({ role: i % 2 ? "assistant" : "user", content: String(i) }));
  const sent = recent(turns);
  expect(sent.length).toBeLessThanOrEqual(MAX_TURNS);
  expect(sent[0]!.role).toBe("user");
  expect(sent.at(-1)!.content).toBe("60");
  expect(recent(turns.slice(0, 3))).toEqual(turns.slice(0, 3));
});
