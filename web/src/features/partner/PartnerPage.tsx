import { ArrowUp, CircleAlert, MonitorSmartphone, Paperclip, Plus, Square, SquarePen, Upload, X } from "lucide-react";
import { useLayoutEffect, useRef } from "react";
import { useInterview } from "../../api/business";
import { errorMessage } from "../../api/client";
import { Button } from "../../components/Button";
import { Progress } from "../../components/Progress";
import { Skeleton } from "../../components/Skeleton";
import { AssistantMessage, Failure, Thinking, UserMessage } from "../assistant/Message";
import { useDropZone, usePartnerComposer, usePartnerConversation, usePartnerUploads } from "./hooks";
import styles from "./PartnerPage.module.css";

const START = "Let's start. Interview me about my business, one question at a time.";

/**
 * `/partner` (fullBleed): the onboarding chat with the business partner (POST /v1/partner/chat), the interview
 * beside it, and document uploads (drop on the page or "+") that the partner then organizes.
 */
export function PartnerPage() {
  const chat = usePartnerConversation();
  const uploads = usePartnerUploads(chat.ask, chat.pending);
  const composer = usePartnerComposer(chat.ask, chat.pending);
  const drop = useDropZone(uploads.add);
  const file = useRef<HTMLInputElement>(null);
  const scroller = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const el = scroller.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [chat.turns, chat.pending]);

  const lastAnswer = chat.turns.findLastIndex((t) => t.role === "assistant");
  return (
    <div className={styles.page} {...drop.handlers} data-dragging={drop.over}>
      <section className={styles.chat} aria-label="Partner chat">
        <header className={styles.bar}>
          <h1>Partner</h1>
          {chat.turns.length > 0 && (
            <Button variant="ghost" size="sm" icon={<SquarePen />} onClick={chat.reset}>
              New chat
            </Button>
          )}
        </header>
        <div ref={scroller} className={styles.scroll}>
          {chat.turns.length === 0 && !chat.pending ? (
            <div className={styles.welcome}>
              <h2>Tell me about your business</h2>
              <p>
                I ask about what you sell, who does what, the tools you use and how information moves between your teams. From that I build your
                business profile, recommend connectors and draft assistants for you to approve. Drop documents here and I file them.
              </p>
              <Button variant="primary" onClick={() => chat.ask(START)}>
                Start the interview
              </Button>
            </div>
          ) : (
            <div className={styles.thread} role="log" aria-label="Conversation">
              {chat.turns.map((turn, i) =>
                turn.role === "user" ? <UserMessage key={i} text={turn.content} /> : <AssistantMessage key={i} turn={turn} last={i === lastAnswer} />,
              )}
              {chat.pending && <Thinking label="Thinking…" />}
              {chat.failure.error && !chat.pending && <Failure chat={chat.failure} />}
            </div>
          )}
        </div>
        <div className={styles.dock}>
          {(uploads.states.length > 0 || uploads.waiting.length > 0) && (
            <ul className={styles.uploads} aria-label="Uploads">
              {uploads.states.map((u) => (
                <li key={u.id} data-state={u.state} title={u.error}>
                  {u.state === "failed" ? <CircleAlert aria-hidden /> : <Upload aria-hidden />}
                  <span className="truncate">{u.state === "failed" ? `${u.name}: ${u.error}` : `Uploading ${u.name}…`}</span>
                  {u.state === "failed" && (
                    <button type="button" aria-label={`Dismiss ${u.name}`} onClick={() => uploads.dismiss(u.id)}>
                      <X aria-hidden />
                    </button>
                  )}
                </li>
              ))}
              {uploads.waiting.map((d) => (
                <li key={d.id} data-state="done">
                  <Paperclip aria-hidden />
                  <span className="truncate">{d.title}</span>
                </li>
              ))}
            </ul>
          )}
          {chat.attached && (
            <p className={styles.attached}>
              <MonitorSmartphone aria-hidden /> Sending with the screen you came from: <code>{chat.attached.page}</code>
            </p>
          )}
          <form className={styles.composer} onSubmit={composer.submit}>
            <input ref={file} type="file" multiple hidden data-testid="partner-upload" onChange={(e) => { void uploads.add(e.target.files); e.target.value = ""; }} />
            <button type="button" className={styles.iconButton} aria-label="Upload documents" title="Upload documents" onClick={() => file.current?.click()}>
              <Plus aria-hidden />
            </button>
            <textarea
              aria-label="Message"
              value={composer.text}
              onChange={(e) => composer.setText(e.target.value)}
              onKeyDown={composer.keyDown}
              rows={2}
              placeholder="Answer, ask, or drop documents here"
            />
            {chat.pending ? (
              <button type="button" className={`${styles.iconButton} ${styles.send}`} aria-label="Stop" onClick={chat.stop}>
                <Square aria-hidden />
              </button>
            ) : (
              <button type="submit" className={`${styles.iconButton} ${styles.send}`} aria-label="Send" disabled={!composer.canSend}>
                <ArrowUp aria-hidden />
              </button>
            )}
          </form>
        </div>
        {drop.over && <div className={styles.dropHint}>Drop files to upload them for the partner</div>}
      </section>
      <InterviewPanel onAsk={(text) => chat.ask(`Ask me this next: ${text}`)} disabled={chat.pending} />
    </div>
  );
}

function InterviewPanel({ onAsk, disabled }: { onAsk: (text: string) => void; disabled: boolean }) {
  const interview = useInterview();
  const data = interview.data;
  return (
    <aside className={styles.side} aria-label="Interview">
      <h2>Interview</h2>
      {interview.isError ? (
        <p className="muted">{errorMessage(interview.error)}</p>
      ) : !data ? (
        <Skeleton height={200} />
      ) : (
        <>
          <div className={styles.total}>
            <span className="num">
              {data.answered} / {data.total} covered
            </span>
            {data.complete && <span className={styles.complete}>Complete</span>}
          </div>
          <Progress value={data.answered} max={data.total} label="Interview covered" />
          <ul className={styles.areas} aria-label="Progress by area">
            {data.areas.map((a) => (
              <li key={a.area}>
                <span className="truncate">{a.label}</span>
                <Progress value={a.answered} max={a.total} label={`${a.label} covered`} />
                <span className="muted num">
                  {a.answered}/{a.total}
                </span>
              </li>
            ))}
          </ul>
          {data.next.length > 0 && (
            <>
              <h3>Next questions</h3>
              <ul className={styles.next} aria-label="Next questions">
                {data.next.map((q) => (
                  <li key={q.id}>
                    <button type="button" disabled={disabled} title={q.purpose} onClick={() => onAsk(q.text)}>
                      {q.text}
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}
        </>
      )}
    </aside>
  );
}
