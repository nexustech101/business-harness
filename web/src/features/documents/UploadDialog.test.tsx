// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { expect, it, vi } from "vitest";
import { apiError, deferred, json, sentForm, serve } from "../../test/api";
import { document, w2 } from "../../test/fixtures";
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
  const sent: { name: string; client: unknown; year: unknown }[] = [];
  let answer = (name: string) => (name === "w2.pdf" ? first.promise : apiError(415, "unsupported_media_type", "notes.pdf is not a PDF."));
  serve((request) => {
    if (request.method === "GET") return json(200, { data: { clients: [{ client: "Gonzalez", documents: 1 }] } }); // stats
    const body = sentForm(request);
    const name = (body.get("file") as File).name;
    sent.push({ name, client: body.get("client"), year: body.get("tax_year") });
    return answer(name);
  });
  const user = userEvent.setup();
  const onClose = renderDialog();

  await user.upload(screen.getByTestId("upload-input"), [file("w2.pdf"), file("notes.pdf"), file("extra.pdf")]);
  expect(row("w2.pdf").dataset.state).toBe("queued");
  expect(row("w2.pdf").textContent).toContain("waiting");
  await user.click(screen.getByRole("button", { name: "Remove extra.pdf" }));
  expect(screen.queryByText("extra.pdf")).toBeNull();
  await user.type(screen.getByRole("combobox", { name: /^Client/ }), "Gonzalez");
  await user.type(screen.getByRole("textbox", { name: /^Tax year/ }), "20x25"); // digits only
  await user.click(screen.getByRole("button", { name: "Upload 2 files" }));

  await waitFor(() => expect(row("w2.pdf").dataset.state).toBe("uploading"));
  expect(row("w2.pdf").textContent).toContain("Extracting forms…");
  expect(row("notes.pdf").dataset.state).toBe("queued"); // one at a time
  await user.click(screen.getByRole("button", { name: "Cancel" })); // disabled while running
  expect(onClose).not.toHaveBeenCalled();

  first.resolve(json(201, { data: document([w2()]) }));
  await waitFor(() => expect(row("notes.pdf").dataset.state).toBe("failed"));
  expect(row("w2.pdf").dataset.state).toBe("done");
  expect(row("w2.pdf").textContent).toContain("1 form extracted · 3 flagged fields");
  expect(row("notes.pdf").textContent).toContain("notes.pdf is not a PDF.");
  expect(sent).toEqual([{ name: "w2.pdf", client: "Gonzalez", year: "2025" }, { name: "notes.pdf", client: "Gonzalez", year: "2025" }]);

  answer = () => json(201, { data: document([], "d2", "notes") });
  await user.click(screen.getByRole("button", { name: "Upload 1 file" }));
  await waitFor(() => expect(row("notes.pdf").dataset.state).toBe("done"));
  expect(sent.map((s) => s.name)).toEqual(["w2.pdf", "notes.pdf", "notes.pdf"]); // only the failed file again
  expect(row("notes.pdf").textContent).toContain("Stored as text");
  expect(screen.getAllByRole("link", { name: "Review" }).map((a) => a.getAttribute("href"))).toEqual(["/documents/d1", "/documents/d2"]);
  await user.click(screen.getByRole("button", { name: "Done" }));
  expect(onClose).toHaveBeenCalledOnce();
});
