import { Send, StickyNote } from "lucide-react";
import { useId } from "react";
import { errorMessage } from "../../api/client";
import { Alert } from "../../components/Alert";
import { Button } from "../../components/Button";
import { Card } from "../../components/Card";
import { EmptyState } from "../../components/EmptyState";
import { Field, Input, Textarea } from "../../components/Field";
import { PageHeader } from "../../components/PageHeader";
import { Skeleton } from "../../components/Skeleton";
import { formatDateTime, timeAgo } from "../../lib/format";
import { useNotesBoard } from "./hooks";
import styles from "./NotesPage.module.css";

/** `/notes?topic=`: the board assistants share facts, hand-offs and reports on, by topic; the owner posts too. */
export function NotesPage() {
  const board = useNotesBoard();
  const topicsId = useId();
  return (
    <div className={styles.page}>
      <PageHeader title="Notes" description="What assistants share with each other, by topic. Assistants read the topics in their spec's `shares`." />
      <Card title="Post a note">
        <form className={styles.form} onSubmit={board.submit}>
          {board.postError && <Alert>{board.postError}</Alert>}
          <div className={styles.formRow}>
            <Field label="Topic">
              <Input
                list={topicsId}
                value={board.draft.topic}
                onChange={(e) => board.setDraft({ ...board.draft, topic: e.target.value })}
                maxLength={60}
                placeholder="e.g. finance"
                required
              />
            </Field>
            <datalist id={topicsId}>
              {board.topics.map((t) => (
                <option key={t} value={t} />
              ))}
            </datalist>
            <Field label="Note">
              <Textarea value={board.draft.text} onChange={(e) => board.setDraft({ ...board.draft, text: e.target.value })} maxLength={4000} rows={2} required />
            </Field>
          </div>
          <div className={styles.formActions}>
            <span className="muted">Posted as the owner.</span>
            <Button type="submit" variant="primary" icon={<Send />} loading={board.posting} disabled={!board.draft.topic.trim() || !board.draft.text.trim()}>
              Post
            </Button>
          </div>
        </form>
      </Card>
      {board.topics.length > 0 && (
        <div className={styles.topics} role="group" aria-label="Topics">
          <button type="button" className={styles.topic} aria-pressed={board.topic === null} onClick={() => board.selectTopic(null)}>
            All topics
          </button>
          {board.topics.map((t) => (
            <button key={t} type="button" className={styles.topic} aria-pressed={board.topic === t} onClick={() => board.selectTopic(t)}>
              {t}
            </button>
          ))}
        </div>
      )}
      {board.notes.isError ? (
        <Alert title="Notes could not be loaded">{errorMessage(board.notes.error)}</Alert>
      ) : !board.notes.data ? (
        <Skeleton height={160} />
      ) : board.shown.length === 0 ? (
        <Card>
          <EmptyState icon={<StickyNote />} title="The board is empty">
            Assistants post here as they work; post the first note yourself.
          </EmptyState>
        </Card>
      ) : (
        <div className={styles.board}>
          {board.shown.map(([topic, notes]) => (
            <Card key={topic} title={topic}>
              {notes.length === 0 ? (
                <p className="muted">No notes on this topic.</p>
              ) : (
                <ul className={styles.notes}>
                  {notes.map((n) => (
                    <li key={n.id}>
                      <p className={styles.text}>{n.text}</p>
                      <p className={styles.meta} title={formatDateTime(n.created_at)}>
                        {n.author} · {timeAgo(n.created_at)}
                      </p>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
