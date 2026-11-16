/**
 * Renders the signed-in dashboard (providers, router, shell) at `path` on the fake API (`api.ts`). `routes`
 * answers `"<METHOD> <path>"` (return undefined to fall through); the defaults cover what the shell loads: the
 * key, the workspace summary, hints (none), assistants (none), the interview, document types and an empty knowledge index. Every other
 * request answers 404. `requests` lists every request with its parsed JSON body.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { Routed } from "../app/App";
import { AuthProvider } from "../app/auth";
import { ThemeProvider } from "../app/theme";
import { ToastProvider } from "../components/Toast";
import { apiError, json, serve } from "./api";
import { workspace } from "./fixtures";

export type Sent = { method: string; path: string; search: string; body: unknown; request: Request };
type Routes = (route: string, sent: Sent) => Response | Promise<Response> | undefined;

export const me = { id: 2, name: "owner-key", prefix: "ak_test", is_admin: false, created_at: "2026-01-01T00:00:00Z" };

const DEFAULTS: Record<string, () => Response> = {
  "GET /auth/me": () => json(200, { data: me }),
  "GET /v1/workspace": () => json(200, { data: workspace() }),
  "POST /v1/workspace/hints": () => json(200, { data: { hints: [] } }),
  "GET /v1/assistants": () => json(200, { data: [] }),
  "GET /v1/business/interview": () => json(200, { data: workspace().interview }),
  "GET /v1/document-types": () => json(200, { data: [] }),
  "GET /v1/knowledge": () => json(200, { data: { sources: 0, passages: 0, never_retrieved: 0, count: 0, items: [] } }),
};

export function renderApp(path: string, routes: Routes = () => undefined) {
  const requests: Sent[] = [];
  serve(async (request) => {
    const url = new URL(request.url);
    const text = request.headers.get("Content-Type")?.includes("json") ? await request.clone().text() : "";
    const sent = { method: request.method, path: url.pathname, search: url.search, body: text ? JSON.parse(text) : null, request };
    requests.push(sent);
    const route = `${request.method} ${url.pathname}`;
    return (await routes(route, sent)) ?? DEFAULTS[route]?.() ?? apiError(404, "not_found", `No fake for ${route}`);
  });
  sessionStorage.setItem("tda.key", "ak_test");
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <ToastProvider>
          <MemoryRouter initialEntries={[path]}>
            <AuthProvider fallback={<p>Checking key</p>}>
              <Routed />
            </AuthProvider>
          </MemoryRouter>
        </ToastProvider>
      </QueryClientProvider>
    </ThemeProvider>,
  );
  const sent = (route: string) => requests.filter((r) => `${r.method} ${r.path}` === route);
  return { ...view, requests, sent, queryClient };
}
