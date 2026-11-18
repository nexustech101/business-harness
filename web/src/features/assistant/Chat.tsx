import { FileSearch, FileText, Handshake, ListChecks, Target, Users, type LucideIcon } from "lucide-react";
import { useEffect, useLayoutEffect, useRef } from "react";
import { useAssistant } from "../../app/assistant";
import { greeting, isNearBottom } from "./chatUtils";
import { Composer } from "./Composer";
import { Mark } from "./Mark";
import { AssistantMessage, Failure, Thinking, UserMessage } from "./Message";
import styles from "./Chat.module.css";

type Variant = "page" | "panel";
type Suggestion = { icon: LucideIcon; label: string; prompt: string };

const LIBRARY: Suggestion[] = [
  { icon: FileText, label: "What is on file?", prompt: "List the documents that are on file" },
  { icon: Users, label: "Who does what?", prompt: "Which roles does the business have, and what is each responsible for?" },
  { icon: Target, label: "Goals", prompt: "What are the goals of the business, and what stands in the way?" },
];

const DOCUMENT: Suggestion[] = [
  { icon: ListChecks, label: "Summarize", prompt: "Summarize this document: what it is, who it concerns and its key points." },
  { icon: FileSearch, label: "Key figures", prompt: "What are the key amounts, dates and terms in this document?" },
  { icon: Handshake, label: "Obligations", prompt: "What does this document commit the business to?" },
];

/** The assistant conversation: a welcome until the first question, then the thread with the composer docked below. */
export function Chat({ variant }: { variant: Variant }) {
  const { turns } = useAssistant();
  if (turns.length > 0) return <Conversation variant={variant} />;
  return variant === "page" ? <Welcome /> : <PanelWelcome />;
}

function useSuggestions(): Suggestion[] {
  return useAssistant().scope.documents.length ? DOCUMENT : LIBRARY;
}

function Welcome() {
  const { ask } = useAssistant();
  const suggestions = useSuggestions();
  return (
    <div className={styles.welcome}>
      <div className={styles.welcomeMain}>
        <h1 className={styles.greeting}>
          <Mark size={28} />
          {greeting(new Date().getHours())}
        </h1>
        <Composer placement="bottom" minRows={2} autoFocus />
      </div>
      <div className={styles.welcomeBelow}>
        <div className={styles.pills}>
          {suggestions.map(({ icon: Icon, label, prompt }) => (
            <button key={label} type="button" className={styles.pill} title={prompt} onClick={() => ask(prompt)}>
              <Icon aria-hidden />
              {label}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

function PanelWelcome() {
  const { ask } = useAssistant();
  const suggestions = useSuggestions();
  return (
    <>
      <div className={styles.panelWelcome}>
        <div className={styles.panelIntro}>
          <Mark size={24} />
          <h3>What can I help with?</h3>
          <p>Answers come from your documents and the business's records, with sources. Nothing is changed.</p>
        </div>
        <div className={styles.list}>
          {suggestions.map(({ icon: Icon, prompt }) => (
            <button key={prompt} type="button" className={styles.listItem} onClick={() => ask(prompt)}>
              <Icon aria-hidden />
              <span>{prompt}</span>
            </button>
          ))}
        </div>
      </div>
      <Dock variant="panel" />
    </>
  );
}

function Conversation({ variant }: { variant: Variant }) {
  const { turns, pending, error } = useAssistant();
  const scroller = useRef<HTMLDivElement>(null);
  const stick = useRef(true);

  // Follow new messages unless the user scrolled up; their own question always brings the end back into view.
  useLayoutEffect(() => {
    const el = scroller.current;
    if (!el) return;
    if (turns.at(-1)?.role === "user") stick.current = true;
    if (stick.current) el.scrollTop = el.scrollHeight;
  }, [turns, pending, error]);

  // Also when the column or the viewport changes size (window resize, the composer growing).
  useEffect(() => {
    const el = scroller.current;
    if (!el?.firstElementChild) return;
    const observer = new ResizeObserver(() => {
      if (stick.current) el.scrollTop = el.scrollHeight;
    });
    observer.observe(el);
    observer.observe(el.firstElementChild);
    return () => observer.disconnect();
  }, []);

  const lastAnswer = turns.findLastIndex((t) => t.role === "assistant");
  return (
    <div className={`${styles.conversation} ${styles[variant]}`}>
      <div ref={scroller} className={styles.scroll} onScroll={(e) => (stick.current = isNearBottom(e.currentTarget))}>
        <div className={styles.thread} role="log" aria-label="Conversation">
          {turns.map((turn, i) =>
            turn.role === "user" ? <UserMessage key={i} text={turn.content} /> : <AssistantMessage key={i} turn={turn} last={i === lastAnswer} />,
          )}
          {pending && <Thinking />}
          {error && !pending && <Failure />}
        </div>
      </div>
      <Dock variant={variant} />
    </div>
  );
}

function Dock({ variant }: { variant: Variant }) {
  return (
    <div className={`${styles.dock} ${styles[variant]}`}>
      <div className={styles.dockInner}>
        <Composer placement="top" autoFocus />
        {variant === "page" && <p className={styles.note}>Answers come from your documents and the business's records. The assistant never changes them.</p>}
      </div>
    </div>
  );
}
