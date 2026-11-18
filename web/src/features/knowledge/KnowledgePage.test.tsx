// @vitest-environment jsdom
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import type { KnowledgeMap, KnowledgeSource } from "../../api/types";
import { json } from "../../test/api";
import { renderApp } from "../../test/app";

const AT = "2026-01-01T00:00:00Z";

function source(id: string, title: string, change: Partial<KnowledgeSource> = {}): KnowledgeSource {
  return {
    document_id: id, title, type: "md", location: `${title}.md`, created_at: AT, passages: 3, never_retrieved: 2, last_retrieved_at: AT,
    sections: ["Terms", "Refunds"], origin: "upload", department: null, kind: null, ...change,
  };
}

const handbook = source("d1", "handbook", { kind: "policy", department: "Operations" });
const profile = source("d2", "Business profile", { origin: "workspace", location: "workspace://profile", never_retrieved: 0, sections: ["Overview"] });

function map(items: KnowledgeSource[]): KnowledgeMap {
  return { sources: 2, passages: 6, never_retrieved: 2, count: items.length, items };
}

it("lists every source with what was never retrieved, filters to unread ones and opens a source's passages", async () => {
  const user = userEvent.setup();
  const { sent } = renderApp("/knowledge", (route, { search }) => {
    if (route === "GET /v1/knowledge") return json(200, { data: map(search.includes("unused=true") ? [handbook] : [handbook, profile]) });
    if (route === "GET /v1/knowledge/d1/passages") {
      return json(200, {
        data: {
          document_id: "d1", title: "handbook", count: 3,
          passages: [
            { chunk_id: "c1", index: 0, section_title: "Terms", page_number: null, sheet_name: null, content: "Net 14 days.", retrievals: 2, last_retrieved_at: AT },
            { chunk_id: "c2", index: 1, section_title: "Refunds", page_number: null, sheet_name: null, content: "Refund within 24 hours.", retrievals: 0, last_retrieved_at: null },
          ],
        },
      });
    }
    return undefined;
  });

  const list = await screen.findByRole("list", { name: "Sources" });
  expect(await screen.findByText("4 of 6 passages have surfaced")).toBeTruthy();
  const rows = within(list).getAllByRole("button");
  expect(rows.map((r) => r.textContent)).toEqual([
    "handbookpolicy · OperationsTerms · Refunds3 passages2 never retrieved",
    "Business profileWorkspace recordOverview3 passagesAll retrieved",
  ]);

  await user.click(screen.getByRole("radio", { name: "Never retrieved" }));
  await screen.findByRole("radio", { name: "Never retrieved", checked: true });
  expect(sent("GET /v1/knowledge").at(-1)!.search).toContain("unused=true");
  expect(await within(screen.getByRole("list", { name: "Sources" })).findAllByRole("button")).toHaveLength(1);

  await user.click(screen.getByRole("button", { name: /^handbook/ }));
  const passages = await screen.findByRole("list", { name: "Passages of handbook" });
  expect(within(passages).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
    "#1Termsretrieved 2 timesNet 14 days.",
    "#2Refundsnever retrievedRefund within 24 hours.",
  ]);
  expect(screen.getByRole("link", { name: "Open the document" }).getAttribute("href")).toBe("/documents/d1");
});

it("searches the index and names the sources that matched without being shown", async () => {
  const user = userEvent.setup();
  const { sent } = renderApp("/knowledge", (route) => {
    if (route === "GET /v1/knowledge") return json(200, { data: map([handbook, profile]) });
    if (route === "POST /v1/knowledge/search") {
      return json(200, {
        data: {
          hits: [{ chunk_id: "c2", document_id: "d1", title: "handbook", section_title: "Refunds", page_number: 2, sheet_name: null, content: "Refund within 24 hours.", similarity: 0.8 }],
          other_sources: [{ document_id: "d2", title: "Business profile" }],
        },
      });
    }
    return undefined;
  });
  await user.type(await screen.findByRole("textbox", { name: "Search the knowledge index" }), "refunds{Enter}");
  const results = await screen.findByRole("list", { name: "Search results" });
  expect(within(results).getByRole("button").textContent).toBe("handbook · Refunds · page 2");
  expect(sent("POST /v1/knowledge/search")[0]!.body).toEqual({ query: "refunds", filters: {} });
  await user.click(screen.getByRole("button", { name: "Business profile" })); // "also relevant": opens that source
  await screen.findByRole("button", { name: /^Business profile/, expanded: true });
});

it("a search result opens its source even when the list does not show it", async () => {
  const user = userEvent.setup();
  renderApp("/knowledge?view=unused", (route) => {
    if (route === "GET /v1/knowledge") return json(200, { data: map([handbook]) }); // the profile is fully retrieved: not listed
    if (route === "POST /v1/knowledge/search") {
      return json(200, {
        data: {
          hits: [{ chunk_id: "p1", document_id: "d2", title: "Business profile", section_title: "Overview", page_number: null, sheet_name: null, content: "Artisan bread.", similarity: 0.9 }],
          other_sources: [],
        },
      });
    }
    if (route === "GET /v1/knowledge/d2/passages") {
      return json(200, {
        data: {
          document_id: "d2", title: "Business profile", count: 1,
          passages: [{ chunk_id: "p1", index: 0, section_title: "Overview", page_number: null, sheet_name: null, content: "Artisan bread.", retrievals: 1, last_retrieved_at: AT }],
        },
      });
    }
    return undefined;
  });
  await user.type(await screen.findByRole("textbox", { name: "Search the knowledge index" }), "bread{Enter}");
  const hit = within(await screen.findByRole("list", { name: "Search results" })).getByRole("button");
  await user.click(hit);
  await user.click(hit); // a second click keeps it open
  const passages = await screen.findByRole("list", { name: "Passages of Business profile" });
  expect(within(passages).getByRole("listitem").textContent).toBe("#1Overviewretrieved 1 timeArtisan bread.");
  await user.click(screen.getByRole("button", { name: "Close source" }));
  expect(screen.queryByRole("list", { name: "Passages of Business profile" })).toBeNull();
});
