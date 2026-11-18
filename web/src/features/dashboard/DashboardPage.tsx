import { ArrowRight, BookOpen, Handshake, Plug, Upload } from "lucide-react";
import type { ReactNode } from "react";
import { Link, useNavigate } from "react-router";
import { useWorkspaceSummary } from "../../api/business";
import { errorMessage } from "../../api/client";
import { useKnowledgeMap } from "../../api/knowledge";
import type { AssistantStatus, ConnectorStatus, WorkspaceSummary } from "../../api/types";
import { useAgentic, useScreenState } from "../../app/agentic";
import { Alert } from "../../components/Alert";
import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Card } from "../../components/Card";
import { PageHeader } from "../../components/PageHeader";
import { Progress } from "../../components/Progress";
import { Skeleton } from "../../components/Skeleton";
import type { Tone } from "../../lib/tone";
import { formatCount } from "../../lib/format";
import { ASSISTANT_STATUS, CONNECTOR_STATUS } from "../../lib/status";
import styles from "./DashboardPage.module.css";

const ASSISTANT_ORDER: AssistantStatus[] = ["active", "draft", "paused"];
const CONNECTOR_ORDER: ConnectorStatus[] = ["connected", "needs_auth", "error", "untested"];

/** `/`: where the workspace stands (GET /v1/workspace). */
export function DashboardPage() {
  const workspace = useWorkspaceSummary();
  useScreenState({ detail: {} });
  return (
    <div>
      <PageHeader
        title="Dashboard"
        description="Where your business workspace stands: what the partner knows, your assistants, and what needs you."
      />
      {workspace.isError ? <Alert title="The dashboard could not be loaded">{errorMessage(workspace.error)}</Alert> : <Summary summary={workspace.data} />}
    </div>
  );
}

function Summary({ summary: s }: { summary?: WorkspaceSummary }) {
  const knowledge = useKnowledgeMap({ limit: 1 });
  if (!s) return <Skeleton height={320} />;
  const { interview } = s;
  return (
    <div className={styles.grid}>
      <Hero summary={s} />
      <div className={styles.tiles}>
        <Tile label="Interview" value={`${interview.answered} / ${interview.total}`} to="/partner" caption={interview.complete ? "Complete" : "questions covered"}>
          <Progress value={interview.answered} max={interview.total} label="Interview covered" />
        </Tile>
        <Tile label="Business profile" value={`${s.profile_fields} / ${s.profile_total}`} to="/profile" caption="sections filled">
          <Progress value={s.profile_fields} max={s.profile_total} label="Profile completeness" />
        </Tile>
        <Tile label="Documents" value={`${formatCount(s.organized_documents)} / ${formatCount(s.documents)}`} to="/profile#documents" caption="organized in the profile">
          <Progress value={s.organized_documents} max={s.documents} label="Documents organized" />
        </Tile>
        <Tile
          label="Knowledge"
          value={knowledge.data ? formatCount(knowledge.data.passages) : "–"}
          to="/knowledge"
          caption={knowledge.data ? `passages in ${formatCount(knowledge.data.sources)} sources` : "searchable passages"}
        />
        <Tile label="Pending approvals" value={formatCount(s.pending_approvals)} to="/approvals" caption={s.pending_approvals ? "waiting for your decision" : "nothing waiting"} warn={s.pending_approvals > 0} />
      </div>
      <Card title="Interview by area" actions={<More to="/partner">Continue with the partner</More>}>
        <ul className={styles.areas}>
          {interview.areas.map((a) => (
            <li key={a.area}>
              <span className={styles.areaLabel}>{a.label}</span>
              <Progress value={a.answered} max={a.total} label={`${a.label} covered`} />
              <span className="muted num">
                {a.answered}/{a.total}
              </span>
            </li>
          ))}
        </ul>
      </Card>
      <div className={styles.stack}>
        <Card title="Assistants" actions={<More to="/assistants">All assistants</More>}>
          <Counts label="Assistants by status" order={ASSISTANT_ORDER} counts={s.assistants} meta={ASSISTANT_STATUS} />
        </Card>
        <Card title="Connectors" actions={<More to="/connectors">Plugins</More>}>
          <Counts label="Connectors by status" order={CONNECTOR_ORDER} counts={s.connectors} meta={CONNECTOR_STATUS} />
        </Card>
      </div>
      {s.recommended_connectors.length > 0 && <Recommended listings={s.recommended_connectors} />}
    </div>
  );
}

/** What the workspace needs next, from how far the setup is: discovery, then documents, then assistants. */
function nextStep(s: WorkspaceSummary): { title: string; body: string } {
  const assistants = Object.values(s.assistants).reduce((n, count) => n + (count ?? 0), 0);
  if (s.documents === 0 && s.interview.answered === 0) {
    return { title: "Let's get to know your business", body: "Upload a few documents (a price list, a contract, last month's report) or simply start talking. The partner reads them, records what it learns and asks about the rest." };
  }
  if (!s.interview.complete) {
    const question = s.interview.next[0]?.text;
    return { title: "Discovery is under way", body: question ? `Next the partner wants to know: ${question}` : "The partner has more questions about how the business runs." };
  }
  if (assistants === 0) return { title: "Ready for your first assistant", body: "The partner knows the business well enough to draft an assistant for one of your roles." };
  return { title: "Your workspace is running", body: "Assistants work from the business profile, your documents and their connectors. Approvals wait for you here." };
}

function Hero({ summary: s }: { summary: WorkspaceSummary }) {
  const navigate = useNavigate();
  const step = nextStep(s);
  const total = s.interview.total + s.profile_total;
  const percent = total ? Math.round((100 * (s.interview.answered + s.profile_fields)) / total) : 0;
  return (
    <section className={styles.hero} aria-label="Workspace setup">
      <div className={styles.heroText}>
        <p className={styles.heroEyebrow}>{s.business_name || "Your business"}</p>
        <h2>{step.title}</h2>
        <p>{step.body}</p>
        <div className={styles.heroActions}>
          <Button variant="primary" icon={<Handshake />} onClick={() => navigate("/partner")}>
            Continue with the partner
          </Button>
          <Link to="/partner" className={styles.heroLink}>
            <Upload aria-hidden /> Upload documents
          </Link>
          <Link to="/knowledge" className={styles.heroLink}>
            <BookOpen aria-hidden /> Browse knowledge
          </Link>
        </div>
      </div>
      <div className={styles.ring} style={{ "--percent": percent } as React.CSSProperties} role="img" aria-label={`Setup ${percent}% complete`}>
        <span className="num">{percent}%</span>
        <small>set up</small>
      </div>
    </section>
  );
}

function Tile({ label, value, caption, to, warn, children }: { label: string; value: string; caption: string; to: string; warn?: boolean; children?: ReactNode }) {
  return (
    <Link to={to} className={styles.tile}>
      <span className={styles.tileLabel}>
        {warn && <span className={styles.warnDot} aria-hidden />}
        {label}
      </span>
      <span className={`${styles.tileValue} num`}>{value}</span>
      <span className={styles.tileCaption}>{caption}</span>
      {children}
    </Link>
  );
}

function More({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link to={to} className={styles.more}>
      {children} <ArrowRight aria-hidden />
    </Link>
  );
}

function Counts<S extends string>({ label, order, counts, meta }: { label: string; order: S[]; counts: Record<string, number>; meta: Record<S, { label: string; tone: Tone }> }) {
  return (
    <dl className={styles.counts} aria-label={label}>
      {order.map((status) => (
        <div key={status}>
          <dt>
            <Badge tone={meta[status].tone} dot>
              {meta[status].label}
            </Badge>
          </dt>
          <dd className="num">{formatCount(counts[status] ?? 0)}</dd>
        </div>
      ))}
    </dl>
  );
}

function Recommended({ listings }: { listings: WorkspaceSummary["recommended_connectors"] }) {
  const navigate = useNavigate();
  const { track } = useAgentic();
  return (
    <Card title="Recommended connectors" className={styles.full}>
      <p className={styles.note}>For tools your business uses that are not connected yet.</p>
      <ul className={styles.recommended}>
        {listings.map((l) => (
          <li key={l.id}>
            <span className={styles.recIcon} aria-hidden>
              <Plug />
            </span>
            <span className={styles.recText}>
              <strong className="truncate">{l.name}</strong>
              <span className="muted truncate">{l.description}</span>
            </span>
            <Button
              size="sm"
              aria-label={`Add ${l.name}`}
              onClick={() => {
                track("action", `recommended:${l.id}`);
                navigate(`/connectors?add=${encodeURIComponent(l.id)}`);
              }}
            >
              Add
            </Button>
          </li>
        ))}
      </ul>
    </Card>
  );
}
