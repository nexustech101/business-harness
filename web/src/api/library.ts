/** Documents, their page images and original files: one thin hook per resource. */
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api, ok, unwrap } from "./client";

/** Pages are always rendered at this width (px), so every view of a page shares one cached image. */
export const PAGE_WIDTH = 1600;

export const keys = {
  documents: ["documents"] as const,
  document: (id: string) => ["documents", id] as const,
  page: (id: string, page: number) => ["pages", id, page, PAGE_WIDTH] as const,
};

export type ListParams = { q?: string; limit?: number; offset?: number; order?: "newest" | "oldest" };

/** Uploaded documents, newest first (the workspace's own index records are on the Knowledge page). */
export function useDocuments(params: ListParams) {
  return useQuery({
    queryKey: [...keys.documents, "list", params],
    queryFn: () => unwrap(api.GET("/v1/library/documents", { params: { query: params } })),
    placeholderData: keepPreviousData,
  });
}

export function useDocument(id: string) {
  return useQuery({
    queryKey: keys.document(id),
    queryFn: () =>
      unwrap(api.GET("/v1/library/documents/{document_id}", { params: { path: { document_id: id } } })),
  });
}

/** Stores a file and indexes its text; the same file again returns the stored document. */
export function useUploadDocument() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (file: File) =>
      unwrap(
        api.POST("/v1/library/documents", {
          // `file` is binary in the schema (typed as string); the serializer sends the File itself.
          body: { file: file as unknown as string },
          bodySerializer() {
            const form = new FormData();
            form.set("file", file, file.name);
            return form;
          },
        }),
      ),
    onSuccess: () => invalidateLibrary(queryClient),
  });
}

export function useDeleteDocument() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      ok(api.DELETE("/v1/library/documents/{document_id}", { params: { path: { document_id: id } } })),
    onSuccess: (_, id) => {
      queryClient.removeQueries({ queryKey: keys.document(id) });
      return invalidateLibrary(queryClient);
    },
  });
}

export function invalidateLibrary(queryClient: ReturnType<typeof useQueryClient>) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: keys.documents }),
    queryClient.invalidateQueries({ queryKey: ["knowledge"] }), // the index follows the library (api/knowledge.ts)
    queryClient.invalidateQueries({ queryKey: ["workspace"] }), // document counts on the dashboard
  ]);
}

/** A rendered page as an object URL (null while loading). The PNG is fetched with the API key, then cached. */
export function usePageImage(documentId: string, page: number | null) {
  const query = useQuery({
    queryKey: keys.page(documentId, page ?? 0),
    enabled: page !== null,
    staleTime: Infinity,
    queryFn: () =>
      ok(
        api.GET("/v1/library/documents/{document_id}/pages/{page}", {
          params: { path: { document_id: documentId, page: page ?? 1 }, query: { width: PAGE_WIDTH } },
          parseAs: "blob",
        }),
      ) as Promise<Blob>,
  });
  return { url: useObjectUrl(query.data), isError: query.isError };
}

function useObjectUrl(blob: Blob | undefined): string | null {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!blob) {
      setUrl(null);
      return;
    }
    const next = URL.createObjectURL(blob);
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [blob]);
  return url;
}

/** Downloads the original file (the route needs the API key header, so a plain link cannot be used). */
export async function downloadOriginal(id: string, filename: string) {
  const blob = (await ok(
    api.GET("/v1/library/documents/{document_id}/file", {
      params: { path: { document_id: id } },
      parseAs: "blob",
    }),
  )) as Blob;
  const url = URL.createObjectURL(blob);
  const link = Object.assign(document.createElement("a"), { href: url, download: filename });
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
