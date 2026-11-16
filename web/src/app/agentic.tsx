/**
 * Agentic UI, first pass: the dashboard reports what is on screen and what the user did; the API answers hints.
 *
 * - Events (the last `MAX_EVENTS`): `navigate` on every route change, `select` / `action` from `track` (pages
 *   call it at their key interactions), `error` for every failed API response (except the hints route), `idle`
 *   after `IDLE_MS` without a key, pointer or wheel input (once per idle spell).
 * - Screen state: `useScreenState({entity, detail})` declares what the page shows; with the route path it is the
 *   `UiState` sent with hint requests and partner messages.
 * - Hints: POST /v1/workspace/hints `{state, events}`, `HINT_DELAY_MS` after a navigation, an idle event or a
 *   tracked event (a later one restarts the wait; a late answer to an older request is dropped). A navigation
 *   clears the hints shown. Dismissed hint ids are kept in localStorage per API key (`dismissedKey(key id)`).
 * - Ask the partner: `askPartner()` keeps the current `UiState` for the partner's next message and opens /partner.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router";
import { fetchHints } from "../api/business";
import { setFailureListener } from "../api/client";
import type { Hint, UiEvent, UiState } from "../api/types";
import { useAuth } from "./auth";

export const MAX_EVENTS = 50;
export const IDLE_MS = 45_000;
export const HINT_DELAY_MS = 600;
/** Dismissals are per signed-in key: another key in the same browser sees its own hints. */
export const dismissedKey = (keyId: number) => `tda.hints.dismissed.${keyId}`;

type Screen = Pick<UiState, "entity" | "detail">;

type Agentic = {
  /** Records a selection or an action; `target` names what was acted on, e.g. `connector:stripe`. */
  track: (type: "select" | "action", target: string, detail?: Record<string, unknown>) => void;
  /** The current screen: route path plus what the page declared. */
  uiState: () => UiState;
  /** Hints for this screen, without dismissed ones. */
  hints: Hint[];
  dismiss: (id: string) => void;
  askPartner: () => void;
  /** The screen `askPartner` was called from, until the partner's next message takes it. */
  attached: UiState | null;
  clearAttached: () => void;
  setScreen: (screen: Screen | null) => void;
};

const noop = () => {};
const AgenticContext = createContext<Agentic>({
  track: noop, uiState: () => ({ page: "/" }), hints: [], dismiss: noop, askPartner: noop, attached: null, clearAttached: noop, setScreen: noop,
});

export const useAgentic = () => useContext(AgenticContext);

/** Declares what the page shows (sent as `ui_state.entity` / `ui_state.detail`); cleared when the page unmounts. */
export function useScreenState(screen: Screen) {
  const { setScreen } = useAgentic();
  const key = JSON.stringify(screen);
  useEffect(() => {
    setScreen(JSON.parse(key) as Screen);
    return () => setScreen(null);
  }, [key, setScreen]);
}

function loadDismissed(storageKey: string): Set<string> {
  try {
    return new Set(JSON.parse(localStorage.getItem(storageKey) ?? "[]") as string[]);
  } catch {
    return new Set();
  }
}

export function AgenticProvider({ children }: { children: ReactNode }) {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const page = useRef(pathname);
  page.current = pathname;
  const screen = useRef<Screen | null>(null);
  const events = useRef<UiEvent[]>([]);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const latest = useRef(0);
  const [hints, setHints] = useState<Hint[]>([]);
  const storageKey = dismissedKey(useAuth().me?.id ?? 0);
  const [dismissed, setDismissed] = useState(() => loadDismissed(storageKey));
  const [attached, setAttached] = useState<UiState | null>(null);

  const uiState = useCallback((): UiState => ({ page: page.current, entity: screen.current?.entity ?? null, detail: screen.current?.detail ?? {} }), []);

  const record = useCallback((event: Omit<UiEvent, "page" | "at">) => {
    events.current = [...events.current, { ...event, page: page.current, at: new Date().toISOString() }].slice(-MAX_EVENTS);
  }, []);

  const requestHints = useCallback(() => {
    clearTimeout(timer.current);
    const id = ++latest.current; // now, not when the timer fires: an answer still in flight for the last screen is stale
    timer.current = setTimeout(() => {
      fetchHints({ state: uiState(), events: events.current })
        .then(({ hints }) => id === latest.current && setHints(hints))
        .catch(noop); // hints are optional: the screen works without them
    }, HINT_DELAY_MS);
  }, [uiState]);

  const track = useCallback<Agentic["track"]>(
    (type, target, detail = {}) => {
      record({ type, target, detail });
      requestHints();
    },
    [record, requestHints],
  );

  useEffect(() => {
    record({ type: "navigate", target: null, detail: {} });
    setHints([]);
    requestHints();
  }, [pathname, record, requestHints]);

  useEffect(() => {
    setFailureListener((method, path, status) => {
      if (path !== "/v1/workspace/hints") record({ type: "error", target: `${method} ${path}`, detail: { status } });
    });
    return () => setFailureListener(noop);
  }, [record]);

  useEffect(() => {
    let idle: ReturnType<typeof setTimeout>;
    const arm = () => {
      clearTimeout(idle);
      idle = setTimeout(() => {
        record({ type: "idle", target: null, detail: { seconds: IDLE_MS / 1000 } });
        requestHints();
      }, IDLE_MS);
    };
    const inputs = ["keydown", "pointerdown", "wheel"] as const;
    inputs.forEach((name) => window.addEventListener(name, arm, { passive: true }));
    arm();
    return () => {
      clearTimeout(idle);
      inputs.forEach((name) => window.removeEventListener(name, arm));
    };
  }, [record, requestHints]);

  useEffect(() => () => clearTimeout(timer.current), []);

  const setScreen = useCallback((next: Screen | null) => {
    screen.current = next;
  }, []);

  const dismiss = useCallback(
    (id: string) => {
    setDismissed((previous) => {
      const next = new Set(previous).add(id);
      try {
        localStorage.setItem(storageKey, JSON.stringify([...next].slice(-200)));
      } catch {
        // storage blocked: dismissed for this page only
      }
      return next;
    });
    },
    [storageKey],
  );

  const value = useMemo<Agentic>(
    () => ({
      track,
      uiState,
      hints: hints.filter((h) => !dismissed.has(h.id)),
      dismiss,
      askPartner: () => {
        setAttached(uiState());
        navigate("/partner");
      },
      attached,
      clearAttached: () => setAttached(null),
      setScreen,
    }),
    [track, uiState, hints, dismissed, dismiss, attached, navigate, setScreen],
  );
  return <AgenticContext.Provider value={value}>{children}</AgenticContext.Provider>;
}
