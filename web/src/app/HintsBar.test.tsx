// @vitest-environment jsdom
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import type { HintsRequest } from "../api/types";
import { json } from "../test/api";
import { me, renderApp } from "../test/app";
import { dismissedKey } from "./agentic";

const hint = { id: "connect-stripe", title: "Connect Stripe", body: "You take payments with Stripe.", tone: "suggestion", action: { label: "Add", href: "/connectors?add=stripe" } };

it("asks for hints after each navigation with the screen and recent events; a dismissed hint stays dismissed", async () => {
  const user = userEvent.setup();
  const { sent } = renderApp("/", (route) => {
    if (route === "POST /v1/workspace/hints") return json(200, { data: { hints: [hint] } });
    if (route === "GET /v1/business/notes") return json(200, { data: [] });
    return undefined;
  });
  const bar = await screen.findByRole("region", { name: "Hints" }, { timeout: 2000 });
  expect(bar.textContent).toContain("Connect Stripe");
  expect(screen.getByRole("link", { name: "Add" }).getAttribute("href")).toBe("/connectors?add=stripe");
  const first = sent("POST /v1/workspace/hints")[0]!.body as HintsRequest;
  expect(first.state).toEqual({ page: "/", entity: null, detail: {} });
  expect(first.events?.map((e) => [e.type, e.page])).toEqual([["navigate", "/"]]);

  await user.click(screen.getByRole("button", { name: "Dismiss hint: Connect Stripe" }));
  expect(screen.queryByRole("region", { name: "Hints" })).toBeNull();
  expect(JSON.parse(localStorage.getItem(dismissedKey(me.id))!)).toEqual(["connect-stripe"]);

  await user.click(screen.getByRole("link", { name: "Notes" }));
  await waitFor(() => expect(sent("POST /v1/workspace/hints")).toHaveLength(2), { timeout: 2000 });
  const second = sent("POST /v1/workspace/hints")[1]!.body as HintsRequest;
  expect(second.state).toEqual({ page: "/notes", entity: null, detail: { topic: null } });
  expect(second.events?.map((e) => [e.type, e.page])).toEqual([["navigate", "/"], ["navigate", "/notes"]]);
  await screen.findByRole("heading", { name: "Notes" });
  expect(screen.queryByText("Connect Stripe")).toBeNull(); // answered again, still dismissed
});

it("records failed API calls and tracked actions as events, and asks again after an action", async () => {
  const user = userEvent.setup();
  const { sent } = renderApp("/notes", (route) => {
    if (route === "GET /v1/business/notes") return json(200, { data: [] });
    if (route === "POST /v1/business/notes") return json(422, { error: { code: "validation_error", message: "Too long.", details: null } });
    return undefined;
  });
  await waitFor(() => expect(sent("POST /v1/workspace/hints")).toHaveLength(1), { timeout: 2000 });
  await user.type(screen.getByRole("combobox", { name: "Topic" }), "finance");
  await user.type(screen.getByRole("textbox", { name: "Note" }), "Month end is on the 3rd.");
  await user.click(screen.getByRole("button", { name: "Post" }));
  await screen.findByText("Too long.");
  await waitFor(() => expect(sent("POST /v1/workspace/hints")).toHaveLength(2), { timeout: 2000 });
  const events = (sent("POST /v1/workspace/hints")[1]!.body as HintsRequest).events!;
  expect(events.map((e) => [e.type, e.target])).toEqual([
    ["navigate", null], ["action", "note:post"], ["error", "POST /v1/business/notes"],
  ]);
  expect(events[2]!.detail).toEqual({ status: 422 });
});

it("shows the most relevant hint and the rest behind +n more", async () => {
  const user = userEvent.setup();
  const others = [{ ...hint, id: "approvals", title: "2 approvals waiting", action: null }, { ...hint, id: "interview", title: "Continue the interview", action: null }];
  renderApp("/", (route) => (route === "POST /v1/workspace/hints" ? json(200, { data: { hints: [hint, ...others] } }) : undefined));
  const bar = await screen.findByRole("region", { name: "Hints" }, { timeout: 2000 });
  expect(bar.textContent).toContain("Connect Stripe");
  expect(bar.textContent).not.toContain("2 approvals waiting");
  await user.click(screen.getByRole("button", { name: "+2 more" }));
  expect(bar.textContent).toContain("2 approvals waiting");
  expect(bar.textContent).toContain("Continue the interview");
  await user.click(screen.getByRole("button", { name: "Show less" }));
  expect(bar.textContent).not.toContain("Continue the interview");
});
