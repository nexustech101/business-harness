/**
 * Component tests (`// @vitest-environment jsdom`): a fake API behind `fetch`, plus what jsdom lacks. Loaded as a
 * vitest setup file, so `fetch` and `Request` are replaced before `api/client.ts` creates the client (openapi-fetch
 * keeps the globals it finds then); a test sets the answers with `serve`.
 */
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

export type Handler = (request: Request) => Response | Promise<Response>;

let handler: Handler = (request) => {
  throw new Error(`no fake API for ${request.method} ${new URL(request.url).pathname}`);
};

/** Answers every request made through `api` until the next `serve`. */
export function serve(next: Handler) {
  handler = next;
}

export function json(status: number, body: unknown): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

/** The API's error envelope. */
export function apiError(status: number, code: string, message: string, details: Record<string, unknown> | null = null): Response {
  return json(status, { error: { code, message, details } });
}

const forms = new WeakMap<Request, FormData>();

/** The multipart body a request was made with (jsdom's FormData does not survive Node's Request). */
export function sentForm(request: Request): FormData {
  const form = forms.get(request);
  if (!form) throw new Error(`${request.method} ${request.url} has no FormData body`);
  return form;
}

/** A promise with its resolver, to hold a request open while the test looks at the pending state. */
export function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => (resolve = r));
  return { promise, resolve };
}

if (typeof window !== "undefined") {
  // The client uses relative paths ("/v1/..."); Node's Request needs an absolute URL.
  const NodeRequest = globalThis.Request;
  globalThis.Request = class extends NodeRequest {
    constructor(input: RequestInfo | URL, init?: RequestInit) {
      super(typeof input === "string" ? new URL(input, window.location.origin) : input, init);
      if (init?.body instanceof FormData) forms.set(this, init.body);
    }
  };
  globalThis.fetch = (input, init) => Promise.resolve(handler(input instanceof Request ? input : new Request(input, init)));
  // jsdom has no <dialog> methods, scrolling or object URLs.
  HTMLDialogElement.prototype.showModal ??= function (this: HTMLDialogElement) {
    this.open = true;
  };
  HTMLDialogElement.prototype.close ??= function (this: HTMLDialogElement) {
    this.open = false;
  };
  Element.prototype.scrollIntoView ??= () => {};
  URL.createObjectURL ??= () => "blob:test";
  URL.revokeObjectURL ??= () => {};
  afterEach(() => {
    cleanup();
    sessionStorage.clear();
    localStorage.clear();
  });
}
