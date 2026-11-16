import { ExternalLink, LogIn } from "lucide-react";
import type { ConnectorListing } from "../../api/types";
import { Alert } from "../../components/Alert";
import { Button } from "../../components/Button";
import { Dialog } from "../../components/Dialog";
import { Field, Input, Select, Textarea } from "../../components/Field";
import { ListingIcon } from "./ListingIcon";
import { useConnectorForm } from "./hooks";
import styles from "./ConnectorsPage.module.css";

type Props = { listing: ConnectorListing | null; open: boolean; onClose: () => void };

/**
 * Add a connector from a store listing (prefilled) or by hand ("Add manually"). A built-in app asks for a name only;
 * OAuth connectors then sign in.
 */
export function ConnectorDialog({ listing, open, onClose }: Props) {
  const c = useConnectorForm(listing, onClose);
  const title = listing ? `Add ${listing.name}` : "Add a connector manually";
  if (c.added) {
    return (
      <Dialog
        open={open}
        onClose={onClose}
        title={title}
        footer={
          <>
            <Button onClick={onClose}>Later</Button>
            <Button variant="primary" icon={<LogIn />} loading={c.signingIn} onClick={c.signIn}>
              Sign in
            </Button>
          </>
        }
      >
        <div className={styles.form}>
          {c.error && <Alert>{c.error}</Alert>}
          <p>
            <strong>{c.added.name}</strong> is added. Sign in{listing ? ` with ${listing.publisher}` : ""} to let it connect; you come back here afterwards.
          </p>
        </div>
      </Dialog>
    );
  }
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={title}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" type="submit" form="connector-form" loading={c.adding} disabled={!c.ready}>
            {c.builtin ? "Create" : "Add connector"}
          </Button>
        </>
      }
    >
      <form id="connector-form" className={styles.form} onSubmit={c.submit}>
        {c.error && <Alert title="Not added">{c.error}</Alert>}
        {listing && <ListingSummary listing={listing} />}
        <Field label="Name" hint={c.builtin ? "What you and your assistants call it, e.g. Orders or Inventory." : undefined}>
          <Input value={c.form.name} onChange={(e) => c.set({ name: e.target.value })} maxLength={80} required />
        </Field>
        {!listing && (
          <Field label="Transport">
            <Select value={c.form.transport} onChange={(e) => c.set({ transport: e.target.value as typeof c.form.transport })}>
              <option value="streamable_http">Streamable HTTP</option>
              <option value="sse">SSE</option>
              <option value="stdio">stdio (a command on the server)</option>
            </Select>
          </Field>
        )}
        {c.stdio ? (
          <>
            <Field label="Command" hint="stdio connectors run a command on the API server: admin keys only.">
              <Input value={c.form.command} onChange={(e) => c.set({ command: e.target.value })} placeholder="e.g. npx" required />
            </Field>
            <Field label="Arguments" hint="One per line.">
              <Textarea value={c.form.args} onChange={(e) => c.set({ args: e.target.value })} rows={3} spellCheck={false} />
            </Field>
          </>
        ) : (
          !c.builtin &&
          (!listing || !listing.url) && (
            <Field label="Server URL" hint={listing ? "This server's address depends on your account; the setup guide says where to find it." : undefined}>
              <Input type="url" value={c.form.url} onChange={(e) => c.set({ url: e.target.value })} placeholder="https://" required />
            </Field>
          )
        )}
        {!listing && !c.stdio && (
          <Field label="Authentication">
            <Select value={c.form.auth} onChange={(e) => c.set({ auth: e.target.value as typeof c.form.auth })}>
              <option value="none">None</option>
              <option value="bearer">Bearer token or API key</option>
              <option value="oauth">OAuth sign-in</option>
            </Select>
          </Field>
        )}
        {c.form.auth === "bearer" && (
          <Field label="API key or token" hint="Stored encrypted and never shown again.">
            <Input type="password" autoComplete="off" value={c.form.token} onChange={(e) => c.set({ token: e.target.value })} required />
          </Field>
        )}
        {c.form.auth === "oauth" && (
          <>
            <Field
              label="OAuth client (client_id:client_secret), if the provider requires one"
              hint="Providers without dynamic client registration need a client you registered with them. Stored encrypted."
            >
              <Input type="password" autoComplete="off" value={c.form.token} onChange={(e) => c.set({ token: e.target.value })} />
            </Field>
            <p className="muted">After adding it, you sign in{listing ? ` with ${listing.publisher}` : " at the provider"}.</p>
          </>
        )}
      </form>
    </Dialog>
  );
}

/** What the listing is and how it connects: the tagline, the publisher's setup text, and its address. */
function ListingSummary({ listing: l }: { listing: ConnectorListing }) {
  return (
    <div className={styles.listingSummary}>
      <div className={styles.listingHead}>
        <ListingIcon category={l.category} />
        <div>
          <strong>{l.tagline || l.name}</strong>
          <span className="muted">
            {l.publisher} · {l.availability}
          </span>
        </div>
      </div>
      <p className={styles.setup}>{l.description}</p>
      <ul className={styles.capabilities} aria-label="Capabilities">
        {l.capabilities.map((capability) => (
          <li key={capability}>{capability}</li>
        ))}
      </ul>
      {!l.builtin && (
        <p className={styles.facts}>
          {l.url && <code>{l.url}</code>}
          {l.docs_url && (
            <a href={l.docs_url} target="_blank" rel="noreferrer" className={styles.docs}>
              Setup guide <ExternalLink aria-hidden />
            </a>
          )}
        </p>
      )}
    </div>
  );
}
