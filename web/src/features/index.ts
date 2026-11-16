/**
 * The page registry: every route of the dashboard. A page is a folder under features/ plus one entry here.
 * Entries with a `section` appear in the sidebar under that section, in array order. `fullBleed` pages fill the
 * content area (no padding, no page scroll) and manage their own scrolling. `useChildren` (expandable entries)
 * and `useBadge` (a count beside the label) are hooks the sidebar calls for its entry.
 */
import { BookOpen, Bot, Building2, Database, FileText, Handshake, LayoutDashboard, Plug, Settings, ShieldCheck, StickyNote } from "lucide-react";
import type { ComponentType } from "react";
import { usePendingApprovals } from "./approvals/hooks";
import { ApprovalsPage } from "./approvals/ApprovalsPage";
import { Mark } from "./assistant/Mark";
import { AssistantPage } from "./assistant/AssistantPage";
import { AssistantDetailPage } from "./assistants/AssistantDetailPage";
import { AssistantsPage } from "./assistants/AssistantsPage";
import { useActiveAssistantLinks } from "./assistants/hooks";
import { ConnectorsPage } from "./connectors/ConnectorsPage";
import { DashboardPage } from "./dashboard/DashboardPage";
import { DatabasesPage } from "./databases/DatabasesPage";
import { DocumentsPage } from "./documents/DocumentsPage";
import { KnowledgePage } from "./knowledge/KnowledgePage";
import { NotesPage } from "./notes/NotesPage";
import { OverviewPage } from "./overview/OverviewPage";
import { PartnerPage } from "./partner/PartnerPage";
import { ProfilePage } from "./profile/ProfilePage";
import { useProfileLinks } from "./profile/sections";
import { ReviewPage } from "./review/ReviewPage";
import { SettingsPage } from "./settings/SettingsPage";

export const SECTIONS = ["Workspace", "Operations", "Knowledge", "Connect"] as const;

export type NavChild = { to: string; label: string };

export type Page = {
  path: string;
  label: string;
  component: ComponentType;
  icon?: ComponentType<{ className?: string }>;
  section?: (typeof SECTIONS)[number];
  fullBleed?: boolean;
  useChildren?: () => NavChild[];
  useBadge?: () => number | undefined;
};

export const pages: Page[] = [
  { path: "/", label: "Dashboard", icon: LayoutDashboard, component: DashboardPage, section: "Workspace" },
  { path: "/partner", label: "Partner", icon: Handshake, component: PartnerPage, section: "Workspace", fullBleed: true },
  { path: "/assistants", label: "Assistants", icon: Bot, component: AssistantsPage, section: "Operations", useChildren: useActiveAssistantLinks },
  { path: "/assistants/:id", label: "Assistant", component: AssistantDetailPage },
  { path: "/approvals", label: "Approvals", icon: ShieldCheck, component: ApprovalsPage, section: "Operations", useBadge: usePendingApprovals },
  { path: "/notes", label: "Notes", icon: StickyNote, component: NotesPage, section: "Operations" },
  { path: "/profile", label: "Business profile", icon: Building2, component: ProfilePage, section: "Knowledge", useChildren: useProfileLinks },
  { path: "/knowledge", label: "Knowledge", icon: BookOpen, component: KnowledgePage, section: "Knowledge" },
  { path: "/documents", label: "Documents", icon: FileText, component: DocumentsPage, section: "Knowledge" },
  { path: "/documents/overview", label: "Document overview", component: OverviewPage },
  { path: "/documents/:id", label: "Review", component: ReviewPage, fullBleed: true },
  { path: "/assistant", label: "Ask documents", icon: Mark, component: AssistantPage, section: "Knowledge", fullBleed: true },
  { path: "/connectors", label: "Plugins", icon: Plug, component: ConnectorsPage, section: "Connect" },
  { path: "/databases", label: "Databases", icon: Database, component: DatabasesPage, section: "Connect" },
  { path: "/settings", label: "Settings", icon: Settings, component: SettingsPage, section: "Connect" },
];
