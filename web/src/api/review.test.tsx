// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { expect, it } from "vitest";
import { apiError, deferred, json, serve } from "../test/api";
import { w2 } from "../test/fixtures";
import { keys } from "./library";
import { useReviewField } from "./review";
import type { Check, FormDetail } from "./types";

function setup() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const form = w2();
  queryClient.setQueryData(keys.form(form.id), form);
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  const { result } = renderHook(() => useReviewField(form), { wrapper });
  const cached = () => queryClient.getQueryData<FormDetail>(keys.form(form.id))!.checks.find((c) => c.field === "wages")!;
  return { result, form, cached };
}

it("shows a decision at once, then the API's check", async () => {
  const { result, form, cached } = setup();
  const answer = deferred<Response>();
  serve((request) => (request.method === "PUT" ? answer.promise : json(200, { data: form })));
  act(() => result.current.mutate({ field: "wages", review: { decision: "corrected", value: 1200 } }));
  await waitFor(() => expect(cached().review).toMatchObject({ decision: "corrected", value: 1200, reviewer: "" }));

  const stored: Check = { ...cached(), review: { decision: "corrected", value: 1200, note: null, reviewer: "firm", reviewer_id: 2, updated_at: "2026-01-02T00:00:00Z" } };
  answer.resolve(json(200, { data: stored }));
  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(cached().review?.reviewer).toBe("firm");
});

it("puts the form back when the API refuses the decision", async () => {
  const { result, cached } = setup();
  const answer = deferred<Response>();
  serve(() => answer.promise);
  act(() => result.current.mutate({ field: "wages", review: { decision: "corrected", value: "see attached" } }));
  await waitFor(() => expect(cached().review?.decision).toBe("corrected"));

  answer.resolve(apiError(422, "invalid_value", "wages: not an amount"));
  await waitFor(() => expect(result.current.isError).toBe(true));
  expect(cached().review).toBeNull();
  expect(result.current.error?.message).toBe("wages: not an amount");
});
