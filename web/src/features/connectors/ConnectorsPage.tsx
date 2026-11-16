import { ArrowUpRight, Check, LogIn, Plug, Plus, RefreshCw, Search, Trash2, Wrench } from "lucide-react";
import { Link } from "react-router";
import { errorMessage } from "../../api/client";
import { useConnectorTools } from "../../api/connectors";
import { DATABASE_LISTING } from "../../api/databases";
import type { ConnectorInfo, ConnectorListing } from "../../api/types";
import { Alert } from "../../components/Alert";
import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Card } from "../../components/Card";
import { Dialog } from "../../components/Dialog";
import { EmptyState } from "../../components/EmptyState";
import { PageHeader } from "../../components/PageHeader";
import { Skeleton } from "../../components/Skeleton";
import table from "../../components/Table.module.css";
import { timeAgo } from "../../lib/format";
import { CONNECTOR_STATUS } from "../../lib/status";
import { ConnectorDialog } from "./ConnectorDialog";
import { ListingIcon } from "./ListingIcon";
import { useConnectorStore, useInstalledActions } from "./hooks";
import styles from "./ConnectorsPage.module.css";

const AUTH_LABEL: Record<ConnectorListing["auth"], string> = { oauth: "Sign-in", bearer: "API key", none: "No sign-in" };
const SHOWN_CAPABILITIES = 3;

/**
 * `/connectors`: what is installed, then the store. Without a search or category the store shows the built-in apps,
 * the featured listings and the rest; with one, a single list of matches. See hooks.ts for the query parameters.
 */
export function ConnectorsPage() {
  const store = useConnectorStore();
  const card = (l: ConnectorListing) => (
    <ListingCard key={l.id} listing={l} installed={store.installed.has(l.id)} onAdd={() => store.setAdding(l)} />
  );
  return (
    <div className={styles.page}>
      <PageHeader
        title="Plugins"
        description="Connect the storage and tools your business runs on. Assistants read through a connector freely; anything that changes data follows each assistant's write policy."
        actions={<Button icon={<Plus />} onClick={() => store.setManual(true)}>Add manually</Button>}
      />
      {store.oauthError && (
        <Alert title="Sign-in failed" action={<Button size="sm" variant="ghost" onClick={store.clearOauthError}>Dismiss</Button>}>
          {store.oauthError}
        </Alert>
      )}
      {store.addMissing && <Alert tone="warning">The store has no connector with that id.</Alert>}
      <Installed connectors={store.connectors.data} error={store.connectors.error} categoryOf={store.categoryOf} />

      <div className={styles.toolbar}>
        <label className={styles.search}>
          <Search aria-hidden />
          <input value={store.q} onChange={(e) => store.setQ(e.target.value)} placeholder="Search connectors" aria-label="Search connectors" />
        </label>
        <div className={styles.categories} role="radiogroup" aria-label="Category">
          {["", ...store.categories].map((c) => (
            <button key={c} type="button" role="radio" aria-checked={store.category === c} className={styles.category} onClick={() => store.setCategory(c)}>
              {c || "All"}
            </button>
          ))}
        </div>
      </div>

      {store.catalog.isError ? (
        <Alert title="The store could not be loaded">{errorMessage(store.catalog.error)}</Alert>
      ) : !store.catalog.data ? (
        <Skeleton height={240} />
      ) : store.filtered ? (
        <section aria-label="Store">
          <h2 className={styles.sectionTitle}>
            {store.listings.length} {store.listings.length === 1 ? "connector" : "connectors"}
            {store.category && ` in ${store.category}`}
          </h2>
          {store.listings.length === 0 ? (
            <Card>
              <EmptyState compact icon={<Search />} title="No matching connectors">
                Try another search or category, or add a server by hand.
              </EmptyState>
            </Card>
          ) : (
            <div className={styles.grid}>{store.listings.map(card)}</div>
          )}
        </section>
      ) : (
        <>
          {store.builtin.length > 0 && (
            <section aria-label="Built-in apps">
              <h2 className={styles.sectionTitle}>Built-in apps</h2>
              <p className={styles.sectionNote}>Run inside this workspace: nothing to sign in to, and your data stays here.</p>
              <div className={styles.grid}>{store.builtin.map(card)}</div>
            </section>
          )}
          {store.featured.length > 0 && (
            <section aria-label="Featured">
              <h2 className={styles.sectionTitle}>Featured</h2>
              <div className={styles.grid}>{store.featured.map(card)}</div>
            </section>
          )}
          {store.rest.length > 0 && (
            <section aria-label="More connectors">
              <h2 className={styles.sectionTitle}>More connectors</h2>
              <div className={styles.grid}>{store.rest.map(card)}</div>
            </section>
          )}
        </>
      )}
      {store.adding && <ConnectorDialog key={store.adding.id} listing={store.adding} open onClose={() => store.setAdding(null)} />}
      {store.manual && <ConnectorDialog listing={null} open onClose={() => store.setManual(false)} />}
    </div>
  );
}

function ListingCard({ listing: l, installed, onAdd }: { listing: ConnectorListing; installed: boolean; onAdd: () => void }) {
  const extra = l.capabilities.length - SHOWN_CAPABILITIES;
  return (
    <article className={styles.card} aria-label={l.name} data-builtin={l.builtin || undefined}>
      <header className={styles.cardHead}>
        <ListingIcon category={l.category} />
        <div className={styles.cardTitle}>
          <h3 className="truncate">{l.name}</h3>
          <span className="muted truncate">{l.publisher}</span>
        </div>
        {installed && !l.builtin && (
          <Badge tone="success" icon={<Check aria-hidden />}>
            Added
          </Badge>
        )}
      </header>
      <p className={styles.tagline}>{l.tagline || l.description}</p>
      <ul className={styles.capabilities} aria-label="Capabilities">
        {l.capabilities.slice(0, SHOWN_CAPABILITIES).map((c) => (
          <li key={c} className="truncate">
            {c}
          </li>
        ))}
        {extra > 0 && <li>+{extra} more</li>}
      </ul>
      <footer className={styles.cardFoot}>
        <span className={styles.meta}>
          <Badge>{l.builtin ? "Built in" : AUTH_LABEL[l.auth]}</Badge>
          <span className="muted truncate" title={l.availability}>
            {l.availability}
          </span>
        </span>
        {(!installed || l.builtin) && (
          <Button size="sm" variant={l.builtin ? "primary" : "secondary"} aria-label={`Add ${l.name}`} onClick={onAdd}>
            {l.builtin ? "Create" : "Add"}
          </Button>
        )}
      </footer>
    </article>
  );
}

type InstalledProps = { connectors?: ConnectorInfo[]; error: Error | null; categoryOf: (c: ConnectorInfo) => string | null };

function Installed({ connectors, error, categoryOf }: InstalledProps) {
  const actions = useInstalledActions();
  const removingDatabase = actions.toRemove?.transport === "builtin";
  return (
    <Card title="Your connectors" flush>
      {error ? (
        <div className={styles.pad}>
          <Alert>{errorMessage(error)}</Alert>
        </div>
      ) : !connectors ? (
        <div className={styles.pad}>
          <Skeleton height={60} />
        </div>
      ) : connectors.length === 0 ? (
        <EmptyState compact icon={<Plug />} title="No connectors yet">
          Add one from the store below; the partner recommends the ones for the tools you use.
        </EmptyState>
      ) : (
        <div className={table.wrap}>
          <table className={table.table}>
            <thead>
              <tr>
                <th>Name</th>
                <th>Server</th>
                <th>Status</th>
                <th className={table.num}>Tools</th>
                <th className={table.num}>Checked</th>
                <th className={table.shrink}><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {connectors.flatMap((c) => [
                <tr key={c.id} aria-label={c.name}>
                  <td>
                    <span className={styles.installedName}>
                      <ListingIcon category={categoryOf(c)} size={28} />
                      <span className="truncate">{c.name}</span>
                    </span>
                  </td>
                  <td className={styles.endpoint}>
                    {c.transport === "builtin" ? (
                      <span className="muted">Built in, stored in this workspace</span>
                    ) : (
                      <code className="truncate">{c.url ?? [c.command, ...c.args].join(" ")}</code>
                    )}
                  </td>
                  <td>
                    <Badge tone={CONNECTOR_STATUS[c.status].tone} title={c.error ?? undefined} dot>
                      {CONNECTOR_STATUS[c.status].label}
                    </Badge>
                  </td>
                  <td className={table.num}>{c.tool_count}</td>
                  <td className={`${table.num} muted`}>{c.checked_at ? timeAgo(c.checked_at) : "never"}</td>
                  <td className={table.shrink}>
                    <div className={styles.rowActions}>
                      {c.listing_id === DATABASE_LISTING && (
                        <Link to={`/databases?db=${encodeURIComponent(c.id)}`} className={styles.open}>
                          Open <ArrowUpRight aria-hidden />
                        </Link>
                      )}
                      {c.auth === "oauth" && (c.status === "needs_auth" || !c.has_secret) && (
                        <Button size="sm" icon={<LogIn />} onClick={() => actions.signIn(c)}>
                          Sign in
                        </Button>
                      )}
                      <Button size="sm" variant="ghost" icon={<RefreshCw />} loading={actions.checking === c.id} onClick={() => actions.check(c)}>
                        Check
                      </Button>
                      <Button size="sm" variant="ghost" icon={<Wrench />} aria-expanded={actions.toolsOf === c.id} onClick={() => actions.toggleTools(c.id)}>
                        Tools
                      </Button>
                      <Button size="sm" variant="ghost" icon={<Trash2 />} aria-label={`Remove ${c.name}`} title="Remove" onClick={() => actions.setToRemove(c)} />
                    </div>
                  </td>
                </tr>,
                actions.toolsOf === c.id && (
                  <tr key={`${c.id}-tools`}>
                    <td colSpan={6} className={styles.toolsCell}>
                      <ToolList id={c.id} />
                    </td>
                  </tr>
                ),
              ])}
            </tbody>
          </table>
        </div>
      )}
      <Dialog
        open={actions.toRemove !== null}
        onClose={() => actions.setToRemove(null)}
        title={removingDatabase ? "Delete this database?" : "Remove connector?"}
        footer={
          <>
            <Button onClick={() => actions.setToRemove(null)}>Cancel</Button>
            <Button variant="danger" loading={actions.removing} onClick={actions.remove}>
              {removingDatabase ? "Delete database" : "Remove"}
            </Button>
          </>
        }
      >
        {removingDatabase ? (
          <p>
            <strong>{actions.toRemove?.name}</strong> and every table in it are deleted for good. Export what you want to keep first.
          </p>
        ) : (
          <p>
            Assistants lose <strong>{actions.toRemove?.name}</strong>'s tools at once; its stored token is deleted.
          </p>
        )}
      </Dialog>
    </Card>
  );
}

function ToolList({ id }: { id: string }) {
  const tools = useConnectorTools(id);
  if (tools.isError) return <Alert>{errorMessage(tools.error)}</Alert>;
  if (!tools.data) return <Skeleton height={40} />;
  if (!tools.data.length) return <p className="muted">It offers no tools.</p>;
  return (
    <ul className={styles.tools} aria-label="Tools">
      {tools.data.map((t) => (
        <li key={t.name}>
          <code>{t.name}</code>
          {t.read_only ? <Badge tone="success">Read-only</Badge> : <Badge tone="warning">Write</Badge>}
          <span className="muted">{t.description}</span>
        </li>
      ))}
    </ul>
  );
}
