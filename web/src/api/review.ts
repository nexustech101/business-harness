/** Form review: read a form as checks, record or clear a decision, approve or reopen. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, unwrap } from "./client";
import { invalidateLibrary, keys } from "./library";
import type { Check, FormDetail, ReviewRequest } from "./types";

export function useForm(id: string | null) {
  return useQuery({
    queryKey: keys.form(id ?? ""),
    enabled: id !== null,
    queryFn: () => unwrap(api.GET("/v1/library/forms/{form_id}", { params: { path: { form_id: id ?? "" } } })),
  });
}

export type ReviewChange = { field: string; review: ReviewRequest | null };

/**
 * Sets (`review`) or clears (`review: null`) the decision on one field. The cached form shows the decision at once
 * (reviewer blank until the API answers) and goes back to what it was when the request fails.
 */
export function useReviewField(form: FormDetail) {
  const queryClient = useQueryClient();
  const key = keys.form(form.id);
  return useMutation({
    mutationFn: ({ field, review }: ReviewChange) => {
      const params = { path: { form_id: form.id, field } };
      return unwrap(
        review
          ? api.PUT("/v1/library/forms/{form_id}/reviews/{field}", { params, body: review })
          : api.DELETE("/v1/library/forms/{form_id}/reviews/{field}", { params }),
      );
    },
    onMutate: async ({ field, review }: ReviewChange) => {
      await queryClient.cancelQueries({ queryKey: key });
      const previous = queryClient.getQueryData<FormDetail>(key);
      const pending = review && { value: null, note: null, ...review, reviewer: "", reviewer_id: 0, updated_at: new Date().toISOString() };
      queryClient.setQueryData<FormDetail>(key, (old) => old && withCheck(old, field, (c) => ({ ...c, review: pending })));
      return { previous };
    },
    onError: (_error, _change, context) => {
      if (context?.previous) queryClient.setQueryData(key, context.previous);
    },
    onSuccess: (check) => {
      // The API's check (normalised value, reviewer); progress, status and counts come from the refetch.
      queryClient.setQueryData<FormDetail>(key, (old) => old && withCheck(old, check.field, () => check));
      return refresh(queryClient, form);
    },
  });
}

export function useFormStatus(form: FormDetail) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (action: "approve" | "reopen") => {
      const init = { params: { path: { form_id: form.id } } };
      return unwrap(
        action === "approve"
          ? api.POST("/v1/library/forms/{form_id}/approve", init)
          : api.POST("/v1/library/forms/{form_id}/reopen", init),
      );
    },
    onSuccess: (updated) => {
      queryClient.setQueryData(keys.form(form.id), updated);
      return refresh(queryClient, form, false);
    },
  });
}

function withCheck(form: FormDetail, field: string, change: (check: Check) => Check): FormDetail {
  return { ...form, checks: form.checks.map((c) => (c.field === field ? change(c) : c)) };
}

function refresh(queryClient: ReturnType<typeof useQueryClient>, form: FormDetail, refetchForm = true) {
  return Promise.all([
    refetchForm && queryClient.invalidateQueries({ queryKey: keys.form(form.id) }),
    queryClient.invalidateQueries({ queryKey: keys.document(form.document_id) }),
    invalidateLibrary(queryClient),
  ]);
}
