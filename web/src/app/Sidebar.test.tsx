// @vitest-environment jsdom
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import { json } from "../test/api";
import { renderApp } from "../test/app";
import { assistant } from "../test/fixtures";
import { COLLAPSED_KEY } from "./Sidebar";

const assistants = [assistant("a1", "Accountant"), assistant("a2", "Marketer", "draft")];

function renderAt(path: string) {
  return renderApp(path, (route) => {
    if (route === "GET /v1/assistants") return json(200, { data: assistants });
    if (route === "GET /v1/approvals") return json(200, { data: [] });
    return undefined;
  });
}

it("lists the sections, marks the active item, badges pending approvals and expands groups", async () => {
  const user = userEvent.setup();
  renderAt("/approvals");
  const nav = await screen.findByRole("navigation", { name: "Main" });
  expect([...nav.querySelectorAll("p")].map((p) => p.textContent)).toEqual(["Workspace", "Operations", "Knowledge", "Connect"]);
  expect(within(nav).getAllByRole("link").map((a) => a.getAttribute("href"))).toEqual([
    "/", "/partner", "/assistants", "/approvals", "/notes", "/profile", "/knowledge", "/documents", "/assistant", "/connectors",
    "/databases", "/settings",
  ]);
  const approvals = within(nav).getByRole("link", { name: /^Approvals/ });
  expect(approvals.getAttribute("aria-current")).toBe("page");
  await waitFor(() => expect(approvals.textContent).toBe("Approvals2 pending")); // pending_approvals from /v1/workspace
  expect(within(nav).getByRole("link", { name: "Dashboard" }).getAttribute("aria-current")).toBeNull();

  // Assistants expands to the active assistants; Business profile to its sections.
  await user.click(within(nav).getByRole("button", { name: "Expand Assistants" }));
  expect(within(nav).getByRole("link", { name: "Accountant" }).getAttribute("href")).toBe("/assistants/a1");
  expect(within(nav).queryByRole("link", { name: "Marketer" })).toBeNull(); // a draft
  await user.click(within(nav).getByRole("button", { name: "Expand Business profile" }));
  expect(within(nav).getByRole("link", { name: "Information flows" }).getAttribute("href")).toBe("/profile#flows");

  // The header: business name and key name; the store button.
  expect((await screen.findByTestId("business-name")).textContent).toBe("Acme Bakery");
  expect(screen.getByTestId("key-name").textContent).toBe("owner-key");
  expect(screen.getByRole("link", { name: "Browse plugins" }).getAttribute("href")).toBe("/connectors");
});

it("collapses to an icon rail and remembers it", async () => {
  const user = userEvent.setup();
  renderAt("/notes");
  const sidebar = await screen.findByRole("complementary", { name: "Sidebar" });
  await user.click(screen.getByRole("button", { name: "Expand Assistants" }));
  await user.click(screen.getByRole("button", { name: "Collapse sidebar" }));
  expect(sidebar.dataset.collapsed).toBe("true");
  expect(localStorage.getItem(COLLAPSED_KEY)).toBe("1");
  // Labels stay as accessible names and tooltips; group toggles and child links are hidden.
  expect(screen.getByRole("link", { name: "Notes" }).getAttribute("title")).toBe("Notes");
  expect(screen.queryByRole("button", { name: /Expand Assistants|Collapse Assistants/ })).toBeNull();
  expect(screen.queryByRole("link", { name: "Accountant" })).toBeNull();
  await user.click(screen.getByRole("button", { name: "Expand sidebar" }));
  expect(sidebar.dataset.collapsed).toBe("false");
  expect(localStorage.getItem(COLLAPSED_KEY)).toBe("0");
});

it("switches the theme from the sidebar's sun/moon toggle", async () => {
  const user = userEvent.setup();
  renderAt("/notes");
  const theme = await screen.findByRole("radiogroup", { name: "Theme" });
  expect(within(theme).getByRole("radio", { name: "Light" }).getAttribute("aria-checked")).toBe("true");
  await user.click(within(theme).getByRole("radio", { name: "Dark" }));
  expect(document.documentElement.dataset.theme).toBe("dark");
  expect(localStorage.getItem("tda.theme")).toBe("dark");
  expect(within(theme).getByRole("radio", { name: "Dark" }).getAttribute("aria-checked")).toBe("true");
  await user.click(within(theme).getByRole("radio", { name: "Light" }));
  expect(document.documentElement.dataset.theme).toBe("light");
});
