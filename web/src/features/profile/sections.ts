/**
 * The business profile's sections (anchor ids on /profile) and their editable fields. Field kinds: `text`,
 * `optional` (empty -> null), `textarea`, `lines` (a list, one item per line), `number` (empty -> null),
 * `select` (`options`).
 */
import type { NavChild } from "../index";

export type FieldKind = "text" | "optional" | "textarea" | "lines" | "number" | "select";
export type FieldSpec = { key: string; label: string; kind: FieldKind; options?: string[] };

export type ListKey = "departments" | "roles" | "tools" | "flows";
export type ListSection = { id: string; label: string; key: ListKey; item: string; fields: FieldSpec[]; title: (item: Record<string, unknown>) => string };

export const OVERVIEW_FIELDS: FieldSpec[] = [
  { key: "name", label: "Business name", kind: "text" },
  { key: "summary", label: "What it does", kind: "textarea" },
  { key: "industry", label: "Industry", kind: "text" },
  { key: "business_model", label: "How it makes money", kind: "text" },
  { key: "offerings", label: "Products and services", kind: "lines" },
  { key: "customers", label: "Customers", kind: "textarea" },
  { key: "locations", label: "Locations", kind: "lines" },
  { key: "team_size", label: "Team size", kind: "number" },
  { key: "stage", label: "Stage", kind: "text" },
  { key: "goals", label: "Goals", kind: "lines" },
  { key: "pain_points", label: "Pain points", kind: "lines" },
];

export const FINANCIAL_FIELDS: FieldSpec[] = [
  { key: "revenue_streams", label: "Revenue streams", kind: "lines" },
  { key: "cost_centers", label: "Cost centers", kind: "lines" },
  { key: "pricing", label: "Pricing", kind: "text" },
  { key: "currency", label: "Currency", kind: "text" },
  { key: "fiscal_year_end", label: "Fiscal year end", kind: "text" },
  { key: "accounting_method", label: "Accounting method", kind: "select", options: ["", "cash", "accrual"] },
  { key: "reporting", label: "Reports", kind: "lines" },
];

export const LISTS: ListSection[] = [
  {
    id: "departments", label: "Departments", key: "departments", item: "department", title: (d) => String(d.name),
    fields: [
      { key: "name", label: "Name", kind: "text" },
      { key: "purpose", label: "Purpose", kind: "textarea" },
      { key: "head", label: "Led by (role)", kind: "optional" },
      { key: "responsibilities", label: "Responsibilities", kind: "lines" },
    ],
  },
  {
    id: "roles", label: "Roles", key: "roles", item: "role", title: (r) => String(r.title),
    fields: [
      { key: "title", label: "Title", kind: "text" },
      { key: "department", label: "Department", kind: "optional" },
      { key: "people", label: "People", kind: "lines" },
      { key: "duties", label: "Duties", kind: "lines" },
      { key: "tools", label: "Tools", kind: "lines" },
      { key: "reports_to", label: "Reports to (role)", kind: "optional" },
    ],
  },
  {
    id: "tools", label: "Tools", key: "tools", item: "tool", title: (t) => String(t.name),
    fields: [
      { key: "name", label: "Name", kind: "text" },
      { key: "category", label: "Category", kind: "text" },
      { key: "used_for", label: "Used for", kind: "text" },
      { key: "departments", label: "Departments", kind: "lines" },
      { key: "listing_id", label: "Store listing id", kind: "optional" },
    ],
  },
  {
    id: "flows", label: "Information flows", key: "flows", item: "flow", title: (f) => `${String(f.source)} → ${String(f.target)}`,
    fields: [
      { key: "source", label: "From", kind: "text" },
      { key: "target", label: "To", kind: "text" },
      { key: "what", label: "What", kind: "text" },
      { key: "cadence", label: "Cadence", kind: "text" },
      { key: "via", label: "Via", kind: "text" },
    ],
  },
];

export const SECTIONS = [
  { id: "overview", label: "Overview" },
  ...LISTS.map(({ id, label }) => ({ id, label })),
  { id: "financials", label: "Financials" },
  { id: "compliance", label: "Compliance" },
  { id: "documents", label: "Organized documents" },
];

const LINKS: NavChild[] = LISTS.map(({ id, label }) => ({ to: `/profile#${id}`, label }));

/** Sidebar entries under Business profile. */
export function useProfileLinks(): NavChild[] {
  return LINKS;
}

export type Draft = Record<string, string>;

/** Form values (all strings) for `fields` of `value`. */
export function toDraft(fields: FieldSpec[], value: Record<string, unknown>): Draft {
  return Object.fromEntries(
    fields.map(({ key, kind }) => {
      const v = value[key];
      return [key, kind === "lines" ? ((v as string[] | undefined) ?? []).join("\n") : v === null || v === undefined ? "" : String(v)];
    }),
  );
}

/** `base` with the draft's fields converted back (lines split and trimmed, empty optional/number -> null). */
export function fromDraft<T extends object>(fields: FieldSpec[], draft: Draft, base: T): T {
  const out = { ...base } as Record<string, unknown>;
  for (const { key, kind } of fields) {
    const raw = draft[key] ?? "";
    const text = raw.trim();
    out[key] =
      kind === "lines" ? raw.split("\n").map((s) => s.trim()).filter(Boolean)
      : kind === "optional" ? text || null
      : kind === "number" ? (text === "" || Number.isNaN(Number(text)) ? null : Number(text))
      : text;
  }
  return out as T;
}
