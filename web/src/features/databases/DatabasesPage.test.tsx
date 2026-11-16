// @vitest-environment jsdom
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import type { CellValue, ConnectorInfo, TableInfo } from "../../api/types";
import { apiError, json } from "../../test/api";
import { renderApp } from "../../test/app";
import { connector } from "../../test/fixtures";
import { identifier } from "./dialogs";
import { toCell } from "./hooks";

const customers: TableInfo = {
  name: "customers", rows: 1,
  columns: [
    { name: "id", type: "integer", required: false, primary_key: true },
    { name: "name", type: "text", required: true, primary_key: false },
    { name: "loaves", type: "integer", required: false, primary_key: false },
  ],
};

/** A fake database: connectors, one database's tables and the rows of `customers`. */
function renderDatabases(installed: ConnectorInfo[]) {
  const tables: TableInfo[] = installed.length ? [customers] : [];
  const rows: { rowid: number; values: CellValue[] }[] = [{ rowid: 1, values: [1, "Cafe Rosa", 120] }];
  return renderApp("/databases", (route, { body }) => {
    if (route === "GET /v1/connectors") return json(200, { data: installed });
    if (route === "POST /v1/connectors") {
      const created = connector("db2", (body as { name: string }).name, { listing_id: "workspace-database", transport: "builtin", url: null });
      installed.push(created);
      return json(201, { data: created });
    }
    if (route.startsWith("GET /v1/databases/") && route.endsWith("/tables")) return json(200, { data: tables });
    if (route === "GET /v1/databases/db1/tables/customers/rows") {
      return json(200, { data: { columns: ["id", "name", "loaves"], rowids: rows.map((r) => r.rowid), rows: rows.map((r) => r.values), total: rows.length } });
    }
    if (route === "POST /v1/databases/db1/tables/customers/rows") {
      const { values } = body as { values: Record<string, CellValue> };
      rows.push({ rowid: 2, values: [2, values.name ?? null, values.loaves ?? null] });
      return json(201, { data: 2 });
    }
    if (route === "PUT /v1/databases/db1/tables/customers/rows/1") return apiError(422, "invalid_database_request", "The database refused the statement: NOT NULL constraint failed.");
    if (route === "POST /v1/databases/db1/query") return json(200, { data: { columns: ["n"], rows: [[2]], truncated: false, changed: 0 } });
    return undefined;
  });
}

const orders = () => [connector("db1", "Orders", { listing_id: "workspace-database", transport: "builtin", url: null })];

it("typed values are stored by column type, and names become identifiers", () => {
  expect([toCell(" 12 ", "integer"), toCell("1.5", "real"), toCell("", "text"), toCell("Yes", "boolean"), toCell("no", "boolean"), toCell("n/a", "integer")]).toEqual([
    12, 1.5, null, 1, 0, "n/a",
  ]);
  expect([identifier(" Order items "), identifier("2024-sales.csv"), identifier("___")]).toEqual(["Order_items", "2024_sales_csv", ""]);
});

it("with no database yet, offers to create one and opens it", async () => {
  const user = userEvent.setup();
  const { sent } = renderDatabases([]);
  await screen.findByText("Create your first database");
  await user.click(screen.getAllByRole("button", { name: "New database" })[0]!);
  const dialog = screen.getByRole("dialog", { name: "New database" });
  await user.type(within(dialog).getByRole("textbox", { name: /^Name/ }), "Inventory");
  await user.click(within(dialog).getByRole("button", { name: "Create database" }));
  await screen.findByText("Created Inventory");
  expect(sent("POST /v1/connectors")[0]!.body).toEqual({ listing_id: "workspace-database", name: "Inventory", transport: "builtin", auth: "none" });
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(await screen.findByText("This database is empty")).toBeTruthy();
});

it("shows a table's rows, adds a row with typed values, reports a refused edit, and runs SQL", async () => {
  const user = userEvent.setup();
  const { sent } = renderDatabases(orders());
  const grid = await screen.findByRole("table", { name: "Rows of customers" });
  expect(within(grid).getAllByRole("columnheader").map((th) => th.textContent)).toEqual(["idkey", "nametext", "loavesinteger", "Actions"]);
  expect(within(grid).getAllByRole("row")[1]!.textContent).toContain("1Cafe Rosa120");

  await user.click(screen.getByRole("button", { name: "Add row" }));
  const draft = within(grid).getByRole("row", { name: "New row" });
  await user.type(within(draft).getByRole("textbox", { name: "name" }), "Milo's Deli");
  await user.type(within(draft).getByRole("textbox", { name: "loaves" }), "45{Enter}");
  await within(grid).findByText("Milo's Deli");
  expect(sent("POST /v1/databases/db1/tables/customers/rows")[0]!.body).toEqual({ values: { name: "Milo's Deli", loaves: 45 } });

  await user.click(screen.getByRole("button", { name: "Edit row 1" }));
  const editing = within(grid).getByRole("row", { name: "Row 1" });
  await user.clear(within(editing).getByRole("textbox", { name: "name" }));
  await user.click(within(editing).getByRole("button", { name: "Save" }));
  await screen.findByText("The database refused the statement: NOT NULL constraint failed.");
  expect(sent("PUT /v1/databases/db1/tables/customers/rows/1")[0]!.body).toEqual({ values: { name: null, loaves: 120 } });

  await user.click(screen.getByRole("radio", { name: "SQL" }));
  const sql = screen.getByRole("textbox", { name: "SQL statement" });
  await user.clear(sql);
  await user.type(sql, "SELECT count(*) AS n FROM customers");
  await user.click(screen.getByRole("button", { name: "Run" }));
  const result = await screen.findByRole("table", { name: "Query result" });
  expect(result.textContent).toBe("n2");
  expect(sent("POST /v1/databases/db1/query")[0]!.body).toEqual({ sql: "SELECT count(*) AS n FROM customers", write: false });
});
