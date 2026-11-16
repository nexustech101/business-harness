/**
 * The sidebar: sections of `pages` entries (features/index.ts), expandable groups, count badges, a collapse
 * control that turns it into an icon rail (kept in localStorage `COLLAPSED_KEY`), the plugins button and
 * the sun/moon theme toggle on its edge.
 */
import { ChevronDown, Moon, PanelLeftClose, PanelLeftOpen, Store, Sun } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, NavLink, useLocation, useMatch } from "react-router";
import { pages, SECTIONS, type Page } from "../features";
import { PRODUCT } from "./product";
import { useTheme, type ThemeChoice } from "./theme";
import styles from "./Sidebar.module.css";

export const COLLAPSED_KEY = "tda.sidebar.collapsed";

function storedCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSED_KEY) === "1";
  } catch {
    return false;
  }
}

export function Sidebar() {
  const [collapsed, setCollapsed] = useState(storedCollapsed);
  const toggle = () => {
    setCollapsed(!collapsed);
    try {
      localStorage.setItem(COLLAPSED_KEY, collapsed ? "0" : "1");
    } catch {
      // storage blocked: the choice lasts for this page only
    }
  };
  return (
    <aside className={`${styles.sidebar} ${collapsed ? styles.collapsed : ""}`} aria-label="Sidebar" data-collapsed={collapsed}>
      <div className={styles.brand}>
        <span className={styles.logo} aria-hidden>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M4 20V9l8-5 8 5v11" />
            <path d="M9 20v-6h6v6" />
          </svg>
        </span>
        <span className={styles.brandName}>{PRODUCT}</span>
        <button
          type="button"
          className={styles.collapse}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          onClick={toggle}
        >
          {collapsed ? <PanelLeftOpen aria-hidden /> : <PanelLeftClose aria-hidden />}
        </button>
      </div>
      <nav className={styles.nav} aria-label="Main">
        {SECTIONS.map((section) => (
          <div key={section} className={styles.section}>
            <p className={styles.sectionLabel} title={section}>
              {section}
            </p>
            <ul className={styles.items}>
              {pages
                .filter((p) => p.section === section)
                .map((page) => (
                  <NavItem key={page.path} page={page} collapsed={collapsed} />
                ))}
            </ul>
          </div>
        ))}
      </nav>
      <div className={styles.foot}>
        <Link to="/connectors" className={styles.store} title="Browse plugins">
          <Store aria-hidden />
          <span className={styles.label}>Browse plugins</span>
        </Link>
      </div>
      <ThemeToggle />
    </aside>
  );
}

const NO_CHILDREN = () => undefined;
const NO_BADGE = () => undefined;

function NavItem({ page, collapsed }: { page: Page; collapsed: boolean }) {
  const { path, label, icon: Icon } = page;
  // The registry is static, so each item always calls the same hooks.
  const children = (page.useChildren ?? NO_CHILDREN)();
  const badge = (page.useBadge ?? NO_BADGE)();
  const active = useMatch({ path, end: path === "/" }) !== null;
  const { pathname, hash } = useLocation();
  const [open, setOpen] = useState(active);
  useEffect(() => {
    if (active) setOpen(true);
  }, [active]);

  return (
    <li>
      <div className={`${styles.row} ${active ? styles.active : ""}`}>
        <NavLink to={path} end={path === "/"} className={styles.link} title={label}>
          {Icon && <Icon className={styles.icon} />}
          <span className={styles.label}>{label}</span>
          {badge ? (
            <span className={`${styles.badge} num`}>
              {badge}
              <span className="sr-only"> pending</span>
            </span>
          ) : null}
        </NavLink>
        {children && !collapsed && (
          <button
            type="button"
            className={styles.chevron}
            aria-expanded={open}
            aria-label={`${open ? "Collapse" : "Expand"} ${label}`}
            onClick={() => setOpen(!open)}
          >
            <ChevronDown aria-hidden />
          </button>
        )}
      </div>
      {children && open && !collapsed && children.length > 0 && (
        <ul className={styles.children}>
          {children.map((child) => {
            const current = child.to.includes("#") ? `${pathname}${hash}` === child.to : pathname === child.to;
            return (
              <li key={child.to}>
                <Link to={child.to} className={styles.child} aria-current={current ? "page" : undefined}>
                  <span className="truncate">{child.label}</span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </li>
  );
}

const THEMES: { value: ThemeChoice; label: string; icon: typeof Sun }[] = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
];

/** The vertical sun/moon pill on the sidebar's edge. "System" is chosen in Settings (then neither is checked). */
function ThemeToggle() {
  const { choice, setChoice } = useTheme();
  return (
    <div className={styles.theme} role="radiogroup" aria-label="Theme">
      {THEMES.map(({ value, label, icon: Icon }) => (
        <button
          key={value}
          type="button"
          role="radio"
          aria-checked={choice === value}
          title={`${label} theme`}
          className={styles.themeOption}
          onClick={() => setChoice(value)}
        >
          <Icon aria-hidden />
          <span className="sr-only">{label}</span>
        </button>
      ))}
    </div>
  );
}
