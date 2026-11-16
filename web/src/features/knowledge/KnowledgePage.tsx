import { BookOpen, Building2, ChevronRight, EyeOff, FileText, Layers, Search, Upload, X } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link } from "react-router";
import { errorMessage } from "../../api/client";
import { usePassages } from "../../api/knowledge";
import type { KnowledgeMap, KnowledgeSearchResponse, KnowledgeSource, SearchHit } from "../../api/types";
import { Alert } from "../../components/Alert";
import { Badge } from "../../components/Badge";
import { Button } from "../../components/Button";
import { Card } from "../../components/Card";
import { EmptyState } from "../../components/EmptyState";
import { PageHeader } from "../../components/PageHeader";
import { Progress } from "../../components/Progress";
import { Segmented } from "../../components/Segmented";
import { Skeleton } from "../../components/Skeleton";
import { formatCount, plural, timeAgo } from "../../lib/format";
import { useKnowledge, useSearchBox, type View } from "./hooks";
import styles from "./KnowledgePage.module.css";

const PASSAGES = 20;
const VIEW_OPTIONS: { value: View; label: string; title: string }[] = [
  { value: "all", label: "Everything", title: "Every source in the index" },
  { value: "files", label: "Files", title: "Documents you uploaded" },
  { value: "workspace", label: "Workspace records", title: "The business profile, discovery answers and notes" },
  { value: "unused", label: "Never retrieved", title: "Sources with passages no search or assistant has surfaced, most first" },
];

/**
 * `/knowledge`: everything the assistants can search, source by source (GET /v1/knowledge). Each source shows how
 * much of it has never been retrieved, and opens to its passages exactly as indexed; the search box runs the same
 * search the assistants use.
 */
export function KnowledgePage() {
  const knowledge = useKnowledge();
  const { map } = knowledge;
  // A search result may belong to a source the current filter or page does not list: it opens on its own.
  const unlisted = knowledge.open !== null && map.data !== undefined && !map.data.items.some((s) => s.document_id === knowledge.open);
  return (
    <div className={styles.page}>
      <PageHeader
        title="Knowledge"
        description="One searchable index of your files and everything the partner has recorded about the business. Nothing depends on being found by a search: every source and passage is listed here, with what has never been retrieved."
        actions={
          <Link to="/partner" className={styles.upload}>
            <Upload aria-hidden /> Add documents
          </Link>
        }
      />
      {map.isError ? <Alert title="The knowledge index could not be loaded">{errorMessage(map.error)}</Alert> : <Totals map={map.data} />}
      <SearchCard onOpen={knowledge.show} />
      {unlisted && knowledge.open && <OpenedSource key={knowledge.open} id={knowledge.open} onClose={knowledge.close} />}
      <Card
        flush
        title="Sources"
        actions={
          <div className={styles.filters}>
            <label className={styles.filter}>
              <Search aria-hidden />
              <input value={knowledge.q} onChange={(e) => knowledge.setQ(e.target.value)} placeholder="Filter by title" aria-label="Filter sources by title" />
            </label>
            <Segmented label="Show" value={knowledge.view} onChange={knowledge.setView} options={VIEW_OPTIONS} />
          </div>
        }
      >
        {!map.data ? (
          <div className={styles.pad}>{!map.isError && <Skeleton height={160} />}</div>
        ) : map.data.items.length === 0 ? (
          <EmptyState icon={<BookOpen />} title={map.data.sources === 0 ? "Nothing is indexed yet" : "No sources match"}>
            {map.data.sources === 0
              ? "Upload documents to the partner or answer its questions: both land here."
              : knowledge.view === "unused"
                ? "Every passage has been retrieved at least once."
                : "Try another filter."}
          </EmptyState>
        ) : (
          <ul className={styles.sources} aria-label="Sources">
            {map.data.items.map((source) => (
              <Source key={source.document_id} source={source} open={knowledge.open === source.document_id} onToggle={() => knowledge.toggle(source.document_id)} />
            ))}
          </ul>
        )}
        {knowledge.hasMore && (
          <div className={styles.more}>
            <Button onClick={knowledge.more} loading={map.isFetching}>
              Show more sources
            </Button>
          </div>
        )}
      </Card>
    </div>
  );
}

function Totals({ map }: { map?: KnowledgeMap }) {
  if (!map) return <Skeleton height={96} />;
  const retrieved = map.passages - map.never_retrieved;
  return (
    <div className={styles.totals}>
      <Stat icon={<FileText />} label="Sources" value={formatCount(map.sources)} caption="files and workspace records" />
      <Stat icon={<Layers />} label="Passages" value={formatCount(map.passages)} caption="indexed and searchable" />
      <Stat
        icon={<EyeOff />}
        label="Never retrieved"
        value={formatCount(map.never_retrieved)}
        caption={map.passages ? `${formatCount(retrieved)} of ${formatCount(map.passages)} passages have surfaced` : "nothing indexed yet"}
      >
        <Progress value={retrieved} max={map.passages} label="Passages retrieved at least once" />
      </Stat>
    </div>
  );
}

function Stat({ icon, label, value, caption, children }: { icon: ReactNode; label: string; value: string; caption: string; children?: ReactNode }) {
  return (
    <div className={styles.stat}>
      <span className={styles.statIcon} aria-hidden>
        {icon}
      </span>
      <div className={styles.statText}>
        <span className={styles.statLabel}>{label}</span>
        <span className={`${styles.statValue} num`}>{value}</span>
        <span className={styles.statCaption}>{caption}</span>
        {children}
      </div>
    </div>
  );
}

function SearchCard({ onOpen }: { onOpen: (id: string) => void }) {
  const box = useSearchBox();
  return (
    <Card>
      <form className={styles.searchForm} onSubmit={box.submit} role="search">
        <label className={styles.searchBox}>
          <Search aria-hidden />
          <input
            value={box.text}
            onChange={(e) => box.setText(e.target.value)}
            placeholder="Search by meaning or exact words, e.g. payment terms for wholesale customers"
            aria-label="Search the knowledge index"
          />
        </label>
        <Button type="submit" variant="primary" loading={box.searching} disabled={!box.text.trim()}>
          Search
        </Button>
        {box.result && <Button variant="ghost" icon={<X />} aria-label="Clear search" onClick={box.clear} />}
      </form>
      {box.error && <Alert>{errorMessage(box.error)}</Alert>}
      {box.result && <Results result={box.result} query={box.asked ?? ""} onOpen={onOpen} />}
    </Card>
  );
}

function Results({ result, query, onOpen }: { result: KnowledgeSearchResponse; query: string; onOpen: (id: string) => void }) {
  if (result.hits.length === 0) return <p className={styles.none}>Nothing matches “{query}”. The sources below list everything that is stored.</p>;
  return (
    <div className={styles.results}>
      <ol className={styles.hits} aria-label="Search results">
        {result.hits.map((hit) => (
          <li key={hit.chunk_id}>
            <button type="button" className={styles.hitTitle} onClick={() => onOpen(hit.document_id)}>
              {hit.title}
              <span className="muted">{where(hit)}</span>
            </button>
            <p className={styles.excerpt}>{hit.content}</p>
          </li>
        ))}
      </ol>
      {result.other_sources.length > 0 && (
        <p className={styles.also}>
          <span className="muted">Also relevant, not shown:</span>
          {result.other_sources.map((s) => (
            <button key={s.document_id} type="button" className={styles.chip} onClick={() => onOpen(s.document_id)}>
              {s.title}
            </button>
          ))}
        </p>
      )}
    </div>
  );
}

/** " · Role: Bookkeeper · page 2" for a hit or passage. */
function where({ section_title, page_number, sheet_name }: Pick<SearchHit, "section_title" | "page_number" | "sheet_name">): string {
  const parts = [section_title, page_number ? `page ${page_number}` : "", sheet_name && sheet_name !== section_title ? `sheet ${sheet_name}` : ""];
  return parts.filter(Boolean).map((p) => ` · ${p}`).join("");
}

function Source({ source: s, open, onToggle }: { source: KnowledgeSource; open: boolean; onToggle: () => void }) {
  const workspace = s.origin === "workspace";
  const filed = [s.kind, s.department].filter(Boolean).join(" · ");
  return (
    <li className={styles.source} data-open={open}>
      <button type="button" className={styles.sourceHead} aria-expanded={open} onClick={onToggle}>
        <ChevronRight className={styles.chevron} aria-hidden />
        <span className={styles.sourceIcon} data-origin={s.origin} aria-hidden>
          {workspace ? <Building2 /> : <FileText />}
        </span>
        <span className={styles.sourceText}>
          <span className={styles.sourceTitle}>
            <span className="truncate">{s.title}</span>
            {workspace ? <Badge tone="accent">Workspace record</Badge> : filed ? <Badge>{filed}</Badge> : <Badge tone="warning">Not filed</Badge>}
          </span>
          <span className={`${styles.sections} truncate`}>{s.sections.length ? s.sections.join(" · ") : `Added ${timeAgo(s.created_at)}`}</span>
        </span>
        <span className={styles.usage}>
          <span className="num">{plural(s.passages, "passage")}</span>
          {s.never_retrieved > 0 ? (
            <Badge tone={s.never_retrieved === s.passages ? "warning" : "neutral"}>{formatCount(s.never_retrieved)} never retrieved</Badge>
          ) : (
            <Badge tone="success">All retrieved</Badge>
          )}
        </span>
      </button>
      {open && <Passages id={s.document_id} source={s} />}
    </li>
  );
}

/** A source opened from a search result while the list does not show it. */
function OpenedSource({ id, onClose }: { id: string; onClose: () => void }) {
  return (
    <Card flush title="Opened from search" actions={<Button size="sm" variant="ghost" icon={<X />} aria-label="Close source" onClick={onClose} />}>
      <Passages id={id} />
    </Card>
  );
}

/** A source's passages as indexed. `source` (when the list has it) adds when it was last retrieved and where to edit it. */
function Passages({ id, source }: { id: string; source?: KnowledgeSource }) {
  const [limit, setLimit] = useState(PASSAGES);
  const passages = usePassages(id, limit);
  if (passages.isError) {
    return (
      <div className={styles.passages}>
        <Alert>{errorMessage(passages.error)}</Alert>
      </div>
    );
  }
  if (!passages.data) {
    return (
      <div className={styles.passages}>
        <Skeleton height={80} />
      </div>
    );
  }
  const { data } = passages;
  return (
    <div className={styles.passages}>
      <p className={styles.passagesHead}>
        <span className="muted">
          {source ? `${source.last_retrieved_at ? `Last retrieved ${timeAgo(source.last_retrieved_at)}` : "Never retrieved"} · ` : `${data.title} · `}
          showing {data.passages.length} of {data.count}
        </span>
        {source?.origin === "upload" && <Link to={`/documents/${id}`}>Open the document</Link>}
        {source?.origin === "workspace" && <Link to="/profile">Edit in the business profile</Link>}
      </p>
      <ol className={styles.passageList} aria-label={`Passages of ${data.title}`}>
        {data.passages.map((p) => (
          <li key={p.chunk_id} data-unused={p.retrievals === 0}>
            <header>
              <span className="num">#{p.index + 1}</span>
              <span className="truncate">{where(p).replace(/^ · /, "") || "No section"}</span>
              <span className={styles.retrievals}>{p.retrievals === 0 ? "never retrieved" : `retrieved ${plural(p.retrievals, "time")}`}</span>
            </header>
            <p className={styles.excerpt}>{p.content}</p>
          </li>
        ))}
      </ol>
      {data.count > data.passages.length && (
        <Button size="sm" onClick={() => setLimit((n) => n + PASSAGES)} loading={passages.isFetching}>
          Show more passages
        </Button>
      )}
    </div>
  );
}
