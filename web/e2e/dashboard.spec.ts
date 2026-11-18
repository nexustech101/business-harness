/**
 * The dashboard against the real API on fake models (see e2e/global-setup.ts). One serial story: sign in, upload
 * two text documents, open one, theme (the sidebar's sun/moon toggle), document assistant (panel, then the
 * "Ask documents" page and New chat), delete. The fake chat model searches with the question and answers with the
 * best-matching line of source [1].
 */
import { expect, test } from "@playwright/test";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const HANDBOOK = `# Staff handbook

## Refunds

Customers can return unopened goods within 30 days for a full refund.
Opened goods are exchanged for store credit.

## Opening hours

The shop opens at 8am on weekdays and 9am on Saturdays.
`;

const PRICES = `Item,Price
Sourdough loaf,6.50
Croissant,3.25
Rye loaf,7.00
`;

test("the dashboard workflow", async ({ page }) => {
  test.setTimeout(300_000);
  const dir = mkdtempSync(join(tmpdir(), "harness-e2e-files-"));
  const handbook = join(dir, "handbook.md");
  const prices = join(dir, "prices.csv");
  writeFileSync(handbook, HANDBOOK);
  writeFileSync(prices, PRICES);

  try {
    await test.step("rejects a wrong key, then signs in", async () => {
      await page.goto("/");
      await page.getByLabel("API key").fill("ak_not_a_key");
      await page.getByRole("button", { name: "Sign in" }).click();
      await expect(page.getByText("This key is not valid, expired or revoked.")).toBeVisible();
      await page.getByLabel("API key").fill(process.env.E2E_CLIENT_KEY!);
      await page.getByRole("button", { name: "Sign in" }).click();
      await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
      await page.getByRole("link", { name: "Documents", exact: true }).first().click();
      await expect(page.getByText("No documents yet")).toBeVisible();
    });

    await test.step("uploads two documents, each indexed", async () => {
      await page.getByRole("button", { name: "Upload documents" }).first().click();
      const dialog = page.getByRole("dialog", { name: "Upload documents" });
      await dialog.getByTestId("upload-input").setInputFiles([handbook, prices]);
      await dialog.getByRole("button", { name: "Upload 2 files" }).click();
      await expect(dialog.getByText(/passages? indexed/)).toHaveCount(2, { timeout: 90_000 });
      await dialog.getByRole("button", { name: "Done" }).click();
      await expect(page.getByRole("row", { name: /handbook/ })).toBeVisible();
      await expect(page.getByRole("row", { name: /prices/ })).toContainText("Not filed yet");
    });

    await test.step("opens a document and shows its passages", async () => {
      await page.getByRole("link", { name: "handbook", exact: true }).click();
      await expect(page.getByRole("heading", { name: "handbook" })).toBeVisible();
      const passages = page.getByRole("list", { name: "Passages" });
      await expect(passages).toContainText("full refund");
      await expect(passages).toContainText("never retrieved");
    });

    await test.step("switches to dark mode with the sidebar toggle and keeps it", async () => {
      const theme = page.getByRole("radiogroup", { name: "Theme" });
      await theme.getByRole("radio", { name: "Dark" }).click();
      await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
      await page.reload();
      await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
      await theme.getByRole("radio", { name: "Light" }).click();
      await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    });

    await test.step("the document assistant answers with a source that opens the document", async () => {
      await page.getByRole("link", { name: "Documents", exact: true }).first().click();
      await page.getByRole("button", { name: "Ask documents" }).click();
      const panel = page.getByRole("complementary", { name: "Assistant" });
      await panel.getByLabel("Question").fill("How long do customers have for a refund?");
      await panel.getByLabel("Question").press("Enter");
      await expect(panel.getByTestId("tool-activity")).toContainText("Searched");
      await expect(panel.getByTestId("citation").first()).toBeVisible();
      await expect(panel).toContainText("30 days");
      await panel.getByTestId("source").first().click();
      await expect(page).toHaveURL(/\/documents\/[\w-]+/);
      await expect(page.getByRole("heading", { name: "handbook" })).toBeVisible();
      await panel.getByRole("button", { name: "Close assistant" }).click();
    });

    await test.step("the Ask documents page continues the conversation; New chat clears it", async () => {
      await page.getByRole("link", { name: "Ask documents" }).click();
      const log = page.getByRole("log", { name: "Conversation" });
      await expect(log.getByTestId("citation").first()).toBeVisible();
      const question = page.getByLabel("Question");
      await question.fill("list the documents");
      await question.press("Enter");
      await expect(question).toHaveValue("");
      await expect(log.getByTestId("tool-activity").last()).toContainText("Listed documents");
      await page.getByRole("button", { name: "New chat" }).click();
      await expect(log).toHaveCount(0);
      await expect(page.getByRole("heading", { name: /^Good (morning|afternoon|evening)$/ })).toBeVisible();
      await expect(page.getByRole("button", { name: "New chat" })).toHaveCount(0);
    });

    await test.step("deletes a document", async () => {
      await page.getByRole("link", { name: "Documents", exact: true }).first().click();
      await page.getByRole("button", { name: "Delete prices" }).click();
      await page.getByRole("dialog", { name: "Delete document?" }).getByRole("button", { name: "Delete" }).click();
      await expect(page.getByText("Deleted prices")).toBeVisible();
      await expect(page.getByRole("row", { name: /prices/ })).toHaveCount(0);
      await expect(page.getByText("1–1 of 1 document")).toBeVisible();
    });
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
