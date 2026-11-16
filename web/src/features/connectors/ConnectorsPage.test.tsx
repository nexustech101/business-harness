// @vitest-environment jsdom
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import type { ConnectorCreate, ConnectorInfo } from "../../api/types";
import { apiError, json } from "../../test/api";
import { renderApp } from "../../test/app";
import { connector, listing } from "../../test/fixtures";

const catalog = [
  listing("stripe", "Stripe", { featured: true }),
  listing("gws", "Google Workspace", { category: "Productivity", auth: "oauth", url: null, publisher: "Google" }),
];

/** The store and an installed list that POST /v1/connectors adds to. */
function renderStore(path: string) {
  const installed: ConnectorInfo[] = [];
  const app = renderApp(path, (route, { body }) => {
    if (route === "GET /v1/connectors/catalog") return json(200, { data: catalog });
    if (route === "GET /v1/connectors") return json(200, { data: installed });
    if (route === "POST /v1/connectors") {
      const create = body as ConnectorCreate;
      if (create.transport === "stdio") return apiError(403, "forbidden", "stdio connectors need an admin key.");
      const info = connector(`c${installed.length + 1}`, create.name, { listing_id: create.listing_id ?? null, url: create.url ?? null, auth: create.auth });
      installed.push(info);
      return json(201, { data: info });
    }
    return undefined;
  });
  return { ...app, installed };
}

it("?add=<listing> opens the add dialog prefilled from the listing; a bearer token is required and sent", async () => {
  const user = userEvent.setup();
  const { sent } = renderStore("/connectors?add=stripe");
  const dialog = await screen.findByRole("dialog", { name: "Add Stripe" });
  expect((within(dialog).getByRole("textbox", { name: "Name" }) as HTMLInputElement).value).toBe("Stripe");
  expect(within(dialog).queryByRole("textbox", { name: "Server URL" })).toBeNull(); // the listing has one
  const add = within(dialog).getByRole("button", { name: "Add connector" }) as HTMLButtonElement;
  expect(add.disabled).toBe(true);
  await user.type(within(dialog).getByLabelText(/^API key or token/), "sk_test_1");
  await user.click(add);
  await screen.findByText("Added Stripe");
  expect(sent("POST /v1/connectors")[0]!.body).toEqual({
    listing_id: "stripe", name: "Stripe", transport: "streamable_http", url: "https://mcp.example.com/stripe", command: null, args: [],
    auth: "bearer", token: "sk_test_1",
  });
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  const row = await screen.findByRole("row", { name: "Stripe" });
  expect(within(row).getByText("Connected")).toBeTruthy();
  expect(within(screen.getByRole("region", { name: "Featured" })).getByText("Added")).toBeTruthy(); // no Add button any more
});

it("adds a connector by hand, and an OAuth listing asks for an optional client then offers sign-in", async () => {
  const user = userEvent.setup();
  const { sent } = renderStore("/connectors");
  await user.click(await screen.findByRole("button", { name: "Add manually" }));
  let dialog = screen.getByRole("dialog", { name: "Add a connector manually" });
  await user.type(within(dialog).getByRole("textbox", { name: "Name" }), "Internal CRM");
  await user.type(within(dialog).getByRole("textbox", { name: "Server URL" }), "https://crm.example.com/mcp");
  await user.selectOptions(within(dialog).getByRole("combobox", { name: "Transport" }), "sse");
  await user.click(within(dialog).getByRole("button", { name: "Add connector" }));
  await screen.findByText("Added Internal CRM");
  expect(sent("POST /v1/connectors")[0]!.body).toEqual({
    listing_id: null, name: "Internal CRM", transport: "sse", url: "https://crm.example.com/mcp", command: null, args: [], auth: "none", token: null,
  });

  // stdio: command and arguments, no authentication; the API's refusal is shown in the dialog.
  await user.click(screen.getByRole("button", { name: "Add manually" }));
  dialog = screen.getByRole("dialog", { name: "Add a connector manually" });
  await user.type(within(dialog).getByRole("textbox", { name: "Name" }), "Files");
  await user.selectOptions(within(dialog).getByRole("combobox", { name: "Transport" }), "stdio");
  expect(within(dialog).queryByRole("combobox", { name: "Authentication" })).toBeNull();
  await user.type(within(dialog).getByRole("textbox", { name: /^Command/ }), "npx");
  await user.type(within(dialog).getByRole("textbox", { name: /^Arguments/ }), "-y{Enter}@modelcontextprotocol/server-filesystem");
  await user.click(within(dialog).getByRole("button", { name: "Add connector" }));
  await within(dialog).findByText("stdio connectors need an admin key.");
  expect(sent("POST /v1/connectors")[1]!.body).toMatchObject({ transport: "stdio", url: null, command: "npx", args: ["-y", "@modelcontextprotocol/server-filesystem"], auth: "none", token: null });
  await user.click(within(dialog).getByRole("button", { name: "Cancel" }));

  // OAuth listing: the token field is the optional pre-registered client.
  await user.click(screen.getByRole("button", { name: "Add Google Workspace" }));
  dialog = screen.getByRole("dialog", { name: "Add Google Workspace" });
  await user.type(within(dialog).getByRole("textbox", { name: /^Server URL/ }), "https://gws.example.com/mcp");
  await user.type(within(dialog).getByLabelText(/^OAuth client \(client_id:client_secret\)/), "cid:secret");
  await user.click(within(dialog).getByRole("button", { name: "Add connector" }));
  await within(dialog).findByRole("button", { name: "Sign in" });
  expect(sent("POST /v1/connectors")[2]!.body).toMatchObject({ listing_id: "gws", auth: "oauth", token: "cid:secret", url: "https://gws.example.com/mcp" });
});

it("lists built-in apps apart, filters by category (also_in included), and creating a database opens it", async () => {
  const user = userEvent.setup();
  catalog.unshift(
    listing("workspace-database", "Workspace database", { builtin: true, transport: "builtin", url: null, auth: "none", category: "Data", docs_url: "" }),
    listing("drive", "Drive", { category: "Storage", auth: "oauth" }),
    listing("m365", "Microsoft 365", { category: "Productivity", also_in: ["Storage"], auth: "oauth" }),
  );
  const { sent } = renderStore("/connectors");
  const apps = await screen.findByRole("region", { name: "Built-in apps" });
  expect(within(apps).getAllByRole("article").map((a) => a.getAttribute("aria-label"))).toEqual(["Workspace database"]);
  expect(within(screen.getByRole("region", { name: "Featured" })).getAllByRole("article")).toHaveLength(1); // Stripe only

  await user.click(screen.getByRole("radio", { name: "Storage" }));
  const store = await screen.findByRole("region", { name: "Store" });
  expect(within(store).getAllByRole("article").map((a) => a.getAttribute("aria-label"))).toEqual(["Drive", "Microsoft 365"]);
  expect(screen.queryByRole("region", { name: "Featured" })).toBeNull();
  await user.click(screen.getByRole("radio", { name: "All" }));

  await user.click(await screen.findByRole("button", { name: "Add Workspace database" }));
  const dialog = screen.getByRole("dialog", { name: "Add Workspace database" });
  expect(within(dialog).queryByRole("textbox", { name: /Server URL/ })).toBeNull();
  const name = within(dialog).getByRole("textbox", { name: /^Name/ });
  await user.clear(name);
  await user.type(name, "Orders");
  await user.click(within(dialog).getByRole("button", { name: "Create" }));
  await screen.findByText("Created Orders");
  expect(sent("POST /v1/connectors")[0]!.body).toEqual({ listing_id: "workspace-database", name: "Orders", transport: "builtin", auth: "none" });
  await screen.findByRole("heading", { name: "Databases" });
});
