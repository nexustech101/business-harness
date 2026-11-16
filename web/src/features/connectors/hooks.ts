/** State of the connector store; `ConnectorsPage` and `ConnectorDialog` render it. */
import { useEffect, useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { errorMessage } from "../../api/client";
import { useAddConnector, useCatalog, useCheckConnector, useConnectors, useRemoveConnector, useStartOAuth } from "../../api/connectors";
import { DATABASE_LISTING } from "../../api/databases";
import type { ConnectorCreate, ConnectorInfo, ConnectorListing } from "../../api/types";
import { useAgentic, useScreenState } from "../../app/agentic";
import { useToast } from "../../components/Toast";

const OAUTH_ERRORS: Record<string, string> = {
  expired: "The sign-in took too long or was already used. Start it again.",
  no_code: "The provider did not complete the sign-in.",
  access_denied: "Access was denied at the provider.",
};

/**
 * The store (search, category) and the installed connectors. Without a search or category (`filtered` false) the
 * page shows `builtin`, `featured` and `rest`; with one, `listings` (a listing matches a category through `category`
 * or `also_in`). The add dialog for a listing is `?add=<listing id>` (links from the dashboard, hints and the
 * profile open it); `?connected=<id>` and `?oauth_error=` are the OAuth callback's results: a toast or an alert,
 * then the parameters are removed.
 */
export function useConnectorStore() {
  const catalog = useCatalog();
  const connectors = useConnectors();
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState("");
  const [category, setCategory] = useState("");
  const [manual, setManual] = useState(false);
  const [oauthError, setOauthError] = useState<string | null>(null);
  const notify = useToast();
  const { track } = useAgentic();

  const addId = params.get("add");
  const adding = addId ? (catalog.data?.find((l) => l.id === addId) ?? null) : null;
  useScreenState({ entity: adding ? { kind: "connector_listing", id: adding.id, title: adding.name } : null, detail: { q, category, manual } });

  useEffect(() => {
    const connected = params.get("connected");
    const failed = params.get("oauth_error");
    if (connected === null && failed === null) return;
    if (connected !== null) notify("Signed in: the connector is ready");
    if (failed !== null) setOauthError(OAUTH_ERRORS[failed] ?? `The sign-in failed (${failed}).`);
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.delete("connected");
        next.delete("oauth_error");
        return next;
      },
      { replace: true },
    );
  }, [params, setParams, notify]);

  const setAdding = (listing: ConnectorListing | null) => {
    if (listing) track("select", `listing:${listing.id}`);
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        if (listing) next.set("add", listing.id);
        else next.delete("add");
        return next;
      },
      { replace: !listing },
    );
  };

  const needle = q.trim().toLowerCase();
  const all = catalog.data ?? [];
  const listings = all.filter(
    (l) =>
      (!category || l.category === category || (l.also_in ?? []).includes(category)) &&
      (!needle || [l.name, l.publisher, l.tagline ?? "", l.description, l.category, ...l.capabilities].some((s) => s.toLowerCase().includes(needle))),
  );
  const categoryById = new Map(all.map((l) => [l.id, l.category]));
  return {
    catalog, connectors, q, setQ, category, setCategory,
    // Storage first: where a business keeps its files is the first thing it connects.
    categories: [...new Set(all.map((l) => l.category))].sort((a, b) => Number(b === "Storage") - Number(a === "Storage") || a.localeCompare(b)),
    filtered: needle !== "" || category !== "",
    builtin: all.filter((l) => l.builtin),
    featured: all.filter((l) => l.featured && !l.builtin),
    rest: all.filter((l) => !l.featured && !l.builtin),
    listings,
    installed: new Set((connectors.data ?? []).flatMap((c) => (c.listing_id ? [c.listing_id] : []))),
    categoryOf: (c: ConnectorInfo) => (c.listing_id ? (categoryById.get(c.listing_id) ?? null) : null),
    adding, setAdding, addMissing: addId !== null && catalog.data !== undefined && adding === null,
    manual, setManual, oauthError, clearOauthError: () => setOauthError(null),
  };
}

type Form = { name: string; transport: ConnectorCreate["transport"]; url: string; command: string; args: string; auth: ConnectorCreate["auth"]; token: string };

/**
 * The add form, prefilled from `listing` (then only the name, a URL when the listing has none, and the token are
 * asked: required for bearer auth, optional for oauth, where it carries a pre-registered OAuth client for providers
 * without dynamic client registration) or empty for a manual connector (stdio forces auth `none`). A built-in
 * listing asks for the name only, and a new workspace database opens on `/databases`. After an OAuth connector is
 * added, `added` holds it and `signIn` starts the provider's sign-in.
 */
export function useConnectorForm(listing: ConnectorListing | null, onDone: () => void) {
  const [form, setForm] = useState<Form>({
    name: listing?.name ?? "", transport: listing?.transport ?? "streamable_http", url: listing?.url ?? "", command: "", args: "",
    auth: listing?.auth ?? "none", token: "",
  });
  const [added, setAdded] = useState<ConnectorInfo | null>(null);
  const add = useAddConnector();
  const oauth = useStartOAuth();
  const notify = useToast();
  const navigate = useNavigate();
  const { track } = useAgentic();
  const builtin = listing?.builtin === true;
  // stdio connectors take no token: their auth is always none.
  const set = (change: Partial<Form>) => setForm((f) => ({ ...f, ...change, ...((change.transport ?? f.transport) === "stdio" ? { auth: "none" as const } : {}) }));
  const stdio = form.transport === "stdio";
  const reachable = builtin || (stdio ? form.command.trim() !== "" : form.url.trim() !== "");
  const ready = form.name.trim() !== "" && reachable && (form.auth !== "bearer" || form.token.trim() !== "");

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!ready) return;
    const body: ConnectorCreate = builtin ? { listing_id: listing.id, name: form.name.trim(), transport: "builtin", auth: "none" } : {
      listing_id: listing?.id ?? null,
      name: form.name.trim(),
      transport: form.transport,
      url: stdio ? null : form.url.trim(),
      command: stdio ? form.command.trim() : null,
      args: stdio ? form.args.split("\n").map((a) => a.trim()).filter(Boolean) : [],
      auth: form.auth,
      // bearer: the API key or token; oauth: an optional pre-registered client, `client_id:client_secret` or `client_id`.
      token: form.auth !== "none" && form.token.trim() ? form.token.trim() : null,
    };
    track("action", "connector:add", { listing: listing?.id ?? null, transport: body.transport, auth: body.auth });
    add.mutate(body, {
      onSuccess: (info) => {
        if (info.auth === "oauth") return setAdded(info);
        if (info.listing_id === DATABASE_LISTING) {
          notify(`Created ${info.name}`);
          onDone();
          return navigate(`/databases?db=${encodeURIComponent(info.id)}`);
        }
        notify(info.status === "error" ? `Added ${info.name}, but it failed its check: ${info.error ?? "no details"}` : `Added ${info.name}`, info.status === "error" ? "danger" : "success");
        onDone();
      },
    });
  };

  return {
    form, set, stdio, builtin, ready, submit, adding: add.isPending, error: add.error ? errorMessage(add.error) : oauth.error ? errorMessage(oauth.error) : null,
    added, signIn: () => added && oauth.mutate(added.id), signingIn: oauth.isPending,
  };
}

/** Check, OAuth sign-in and removal of installed connectors, with the one waiting for confirmation to remove. */
export function useInstalledActions() {
  const check = useCheckConnector();
  const remove = useRemoveConnector();
  const oauth = useStartOAuth();
  const notify = useToast();
  const { track } = useAgentic();
  const [toRemove, setToRemove] = useState<ConnectorInfo | null>(null);
  const [toolsOf, setToolsOf] = useState<string | null>(null);
  return {
    check: (c: ConnectorInfo) => {
      track("action", `connector:${c.id}:check`);
      check.mutate(c.id, {
        onSuccess: (info) => notify(info.status === "connected" ? `${info.name} is connected` : `${info.name}: ${info.error ?? info.status}`, info.status === "connected" ? "success" : "danger"),
        onError: (e) => notify(errorMessage(e), "danger"),
      });
    },
    checking: check.isPending ? check.variables : undefined,
    signIn: (c: ConnectorInfo) => oauth.mutate(c.id, { onError: (e) => notify(errorMessage(e), "danger") }),
    toRemove, setToRemove,
    remove: () =>
      toRemove &&
      remove.mutate(toRemove.id, {
        onSuccess: () => {
          notify(`Removed ${toRemove.name}`);
          setToRemove(null);
        },
        onError: (e) => notify(errorMessage(e), "danger"),
      }),
    removing: remove.isPending,
    toolsOf, toggleTools: (id: string) => setToolsOf((open) => (open === id ? null : id)),
  };
}
