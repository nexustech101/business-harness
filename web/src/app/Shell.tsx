import { Handshake, LogOut, Search } from "lucide-react";
import { useState, type FormEvent } from "react";
import { matchPath, Outlet, useLocation, useNavigate } from "react-router";
import { useWorkspaceSummary } from "../api/business";
import { Button } from "../components/Button";
import { AssistantPanel } from "../features/assistant/AssistantPanel";
import { Mark } from "../features/assistant/Mark";
import { pages } from "../features";
import { useAgentic } from "./agentic";
import { useAssistant } from "./assistant";
import { useAuth } from "./auth";
import { HintsBar } from "./HintsBar";
import { Sidebar } from "./Sidebar";
import styles from "./Shell.module.css";

export function Shell() {
  const { me, signOut } = useAuth();
  const assistant = useAssistant();
  const { askPartner } = useAgentic();
  const workspace = useWorkspaceSummary();
  const { pathname } = useLocation();
  const page = pages.find((p) => matchPath(p.path, pathname));
  const initials = (me?.name ?? "?").slice(0, 2).toUpperCase();

  return (
    <div className={styles.app}>
      <Sidebar />
      <div className={styles.main}>
        <header className={styles.topbar}>
          <div className={styles.business}>
            <span className={`${styles.businessName} truncate`} data-testid="business-name">
              {workspace.data?.business_name || "Your business"}
            </span>
            <GlobalSearch />
          </div>
          <div className={styles.topActions}>
            {pathname !== "/partner" && (
              <Button icon={<Handshake />} title="Ask the partner about this screen" onClick={askPartner}>
                Ask the partner
              </Button>
            )}
            {pathname !== "/assistant" && (
              <Button
                icon={<Mark size={16} />}
                aria-pressed={assistant.panelOpen}
                onClick={assistant.panelOpen ? assistant.closePanel : assistant.openPanel}
              >
                Ask documents
              </Button>
            )}
            <div className={styles.account}>
              <span className={styles.avatar} aria-hidden>
                {initials}
              </span>
              <span className={styles.accountText}>
                <span className="truncate" data-testid="key-name">{me?.name}</span>
                <span className={styles.accountRole}>{me?.is_admin ? "Admin key" : "Client key"}</span>
              </span>
              <Button variant="ghost" size="sm" icon={<LogOut />} aria-label="Sign out" title="Sign out" onClick={() => signOut()} />
            </div>
          </div>
        </header>
        <HintsBar />
        <main className={page?.fullBleed ? styles.full : styles.content}>
          <Outlet />
        </main>
      </div>
      {assistant.panelOpen && pathname !== "/assistant" && <AssistantPanel />}
    </div>
  );
}

function GlobalSearch() {
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    navigate(q.trim() ? `/documents?q=${encodeURIComponent(q.trim())}` : "/documents");
    setQ("");
  };
  return (
    <form className={styles.search} onSubmit={submit} role="search">
      <Search aria-hidden />
      <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find documents by title" aria-label="Find documents" />
    </form>
  );
}
