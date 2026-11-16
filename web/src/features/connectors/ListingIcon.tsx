import {
  Code,
  CreditCard,
  Database,
  HardDrive,
  Kanban,
  LayoutGrid,
  Megaphone,
  MessageSquare,
  Plug,
  ShoppingBag,
  Users,
  Workflow,
  type LucideIcon,
} from "lucide-react";
import styles from "./ConnectorsPage.module.css";

/** One icon and hue per store category; anything else (a connector added by hand) is a plug. */
const CATEGORY: Record<string, { icon: LucideIcon; hue: number }> = {
  Storage: { icon: HardDrive, hue: 212 },
  Productivity: { icon: LayoutGrid, hue: 245 },
  Communication: { icon: MessageSquare, hue: 172 },
  CRM: { icon: Users, hue: 24 },
  Payments: { icon: CreditCard, hue: 262 },
  Marketing: { icon: Megaphone, hue: 330 },
  Data: { icon: Database, hue: 152 },
  Automation: { icon: Workflow, hue: 38 },
  Development: { icon: Code, hue: 220 },
  "Project management": { icon: Kanban, hue: 198 },
  Commerce: { icon: ShoppingBag, hue: 128 },
};

/** The tile beside a listing's or connector's name, coloured by its category. */
export function ListingIcon({ category, size = 36 }: { category?: string | null; size?: number }) {
  const { icon: Icon, hue } = (category && CATEGORY[category]) || { icon: Plug, hue: 230 };
  return (
    <span className={styles.icon} style={{ "--hue": hue, width: size, height: size } as React.CSSProperties} aria-hidden>
      <Icon />
    </span>
  );
}
