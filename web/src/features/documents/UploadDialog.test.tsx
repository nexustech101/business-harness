// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { expect, it, vi } from "vitest";
import { apiError, deferred, json, sentForm, serve } from "../../test/api";
import { document } from "../../test/fixtures";
import { UploadDialog } from "./UploadDialog";

function renderDialog() {
  const onClose = vi.fn();
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <UploadDialog open onClose={onClose} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return onClose;
}

const file = (name: string) => new File(["%PDF-1.7"], name, { type: "application/pdf" });
const row = (name: string) => screen.getByText(name).closest("li")!;

it("queues files, uploads them one at a time and shows each result or error", async () => {
  const first = deferred<Response>();
  const sent: string[] = [];
  let answer = (name: string) => (name === "lease.pdf" ? first.promise : apiError(415, "unsupported_media_type", "notes.pdf is not a PDF."));
  serve((request) => {
    const name = (sentForm(request).get("file") as File).name;
    sent.push(name);
    return answer(name);
  });
  const user = userEvent.setup();
  const onClose = renderDialog();

  await user.upload(screen.getByTestId("upload-input"), [file("lease.pdf"), file("notes.pdf"), file("extra.pdf")]);
  expect(row("lease.pdf").dataset.state).toBe("queued");
  expect(row("lease.pdf").textContent).toContain("waiting");
  await user.click(screen.getByRole("button", { name: "Remove extra.pdf" }));
  expect(screen.queryByText("extra.pdf")).toBeNull();
  await user.click(screen.getByRole("button", { name: "Upload 2 files" }));

  await waitFor(() => expect(row("lease.pdf").dataset.state).toBe("uploading"));
  expect(row("lease.pdf").textContent).toContain("Reading and indexing…");
  expect(row("notes.pdf").dataset.state).toBe("queued"); // one at a time
  await user.click(screen.getByRole("button", { name: "Cancel" })); // disabled while running
  expect(onClose).not.toHaveBeenCalled();

  first.resolve(json(201, { data: document() }));
  await waitFor(() => expect(row("notes.pdf").dataset.state).toBe("failed"));
  expect(row("lease.pdf").dataset.state).toBe("done");
  expect(row("lease.pdf").textContent).toContain("1 page · 2 passages indexed");
  expect(row("notes.pdf").textContent).toContain("notes.pdf is not a PDF.");
  expect(sent).toEqual(["lease.pdf", "notes.pdf"]);

  answer = () => json(201, { data: document("d2", "notes") });
  await user.click(screen.getByRole("button", { name: "Upload 1 file" }));
  await waitFor(() => expect(row("notes.pdf").dataset.state).toBe("done"));
  expect(sent).toEqual(["lease.pdf", "notes.pdf", "notes.pdf"]); // only the failed file again
  expect(screen.getAllByRole("link", { name: "Open" }).map((a) => a.getAttribute("href"))).toEqual(["/documents/d1", "/documents/d2"]);
  await user.click(screen.getByRole("button", { name: "Done" }));
  expect(onClose).toHaveBeenCalledOnce();
});
