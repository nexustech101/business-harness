/** API objects for component tests, shaped by the generated types. */
import type { Approval, AssistantInfo, Check, ConnectorInfo, ConnectorListing, DocumentDetail, FormDetail, WorkspaceSummary } from "../api/types";
import type { JsonSchema } from "../features/assistants/specSchema";

export function check(field: string, label: string, flagged: boolean, value: Check["value"] = 1000): Check {
  return {
    field, label, group: null, kind: "money", value, source: null, review: null,
    flags: flagged ? [{ field, code: "not_printed", message: `${label} is not printed` }] : [],
  };
}

/** A W-2 with three flagged money fields and one unflagged. */
export function w2(): FormDetail {
  const checks = [check("wages", "Wages", true), check("federal", "Federal tax", true), check("state", "State tax", true), check("medicare", "Medicare", false)];
  return {
    id: "f1", document_id: "d1", index: 0, status: "ok", pages: [1], document_type: "w2", form_name: "W-2", duplicate_of: null,
    review_status: "pending", open_flags: 3, classification: { document_type: "w2", label: null, confidence: 1, probabilities: {}, model: "headings" },
    text_layer: true, extraction_model: "fake", approved_by: null, approved_at: null, flags: [], checks, checked: 0, total: checks.length,
    corrected_fields: {},
  };
}

export function document(forms: FormDetail[] = [], id = "d1", title = "w2"): DocumentDetail {
  return {
    id, title, type: "pdf", media_type: "application/pdf", length_bytes: 1000, location: `${title}.pdf`, content_hash: "0".repeat(64),
    client: null, tax_year: null, created_at: "2026-01-01T00:00:00Z", chunks: 1, document_types: ["w2"], page_count: 1,
    review_status: forms.length ? "pending" : null, forms_pending: forms.length, forms_approved: 0,
    open_flags: forms.reduce((n, f) => n + f.open_flags, 0), pages: [{ n: 1, width: 612, height: 792 }],
    forms: forms.map(({ id, index, status, pages, document_type, form_name, duplicate_of, review_status, open_flags }) => ({
      id, index, status, pages, document_type, form_name, duplicate_of, review_status, open_flags,
    })),
  };
}

const AT = "2026-01-01T00:00:00Z";

/** GET /v1/assistants/schema as the API returns it (Pydantic's `AssistantSpec.model_json_schema()`). */
export const specSchema: JsonSchema = {"$defs": {"KnowledgeScope": {"additionalProperties": false, "description": "Which organized documents the assistant can search. Empty lists: no limit.", "properties": {"departments": {"items": {"type": "string"}, "title": "Departments", "type": "array"}, "document_kinds": {"items": {"type": "string"}, "title": "Document Kinds", "type": "array"}}, "title": "KnowledgeScope", "type": "object"}, "WritePolicy": {"additionalProperties": false, "description": "What happens when the assistant calls a tool that changes something. Reads always run.", "properties": {"default": {"enum": ["auto", "ask", "deny"], "type": "string", "default": "ask", "title": "Default"}, "tools": {"additionalProperties": {"enum": ["auto", "ask", "deny"], "type": "string"}, "description": "Per tool, keyed `<connector id>/<tool name>`; overrides `default`.", "title": "Tools", "type": "object"}}, "title": "WritePolicy", "type": "object"}}, "additionalProperties": false, "description": "An assistant is this JSON object. The partner creates them; the owner can write or edit one by hand.\n\n{\"name\": \"Accountant\", \"role\": \"Keeps the books and prepares the monthly report\",\n \"department\": \"Finance\", \"instructions\": \"...\", \"connectors\": [\"<connector id>\"],\n \"knowledge\": {\"departments\": [\"Finance\"]}, \"shares\": [\"finance\", \"month-end\"],\n \"policy\": {\"default\": \"ask\", \"tools\": {\"<connector id>/list_invoices\": \"auto\"}}}", "properties": {"name": {"maxLength": 60, "minLength": 1, "title": "Name", "type": "string"}, "role": {"description": "One sentence: what it is responsible for.", "maxLength": 300, "minLength": 1, "title": "Role", "type": "string"}, "department": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": null, "title": "Department"}, "instructions": {"default": "", "description": "How it works: steps, rules, tone.", "maxLength": 8000, "title": "Instructions", "type": "string"}, "connectors": {"description": "Ids of installed connectors it may use.", "items": {"type": "string"}, "title": "Connectors", "type": "array"}, "knowledge": {"$ref": "#/$defs/KnowledgeScope"}, "shares": {"description": "Notes-board topics it reads and posts to (shared with other assistants).", "items": {"type": "string"}, "title": "Shares", "type": "array"}, "policy": {"$ref": "#/$defs/WritePolicy"}, "max_tool_rounds": {"default": 6, "maximum": 20, "minimum": 0, "title": "Max Tool Rounds", "type": "integer"}}, "required": ["name", "role"], "title": "AssistantSpec", "type": "object"};

export function workspace(change: Partial<WorkspaceSummary> = {}): WorkspaceSummary {
  return {
    business_name: "Acme Bakery", profile_fields: 4, profile_total: 10,
    interview: { answered: 3, total: 20, complete: false, areas: [{ area: "identity", label: "Identity", answered: 2, total: 3 }], next: [] },
    documents: 5, organized_documents: 2, assistants: { active: 1, draft: 1 }, connectors: { connected: 1 }, pending_approvals: 2,
    recommended_connectors: [], ...change,
  };
}

export function assistant(id: string, name: string, status: AssistantInfo["status"] = "active", change: Partial<AssistantInfo> = {}): AssistantInfo {
  return {
    id, name, role: `${name} role`, department: null, instructions: "", connectors: [], knowledge: { departments: [], document_kinds: [] },
    shares: [], policy: { default: "ask", tools: {} }, max_tool_rounds: 6, status, created_by: "owner", created_at: AT, updated_at: AT, ...change,
  };
}

export function listing(id: string, name: string, change: Partial<ConnectorListing> = {}): ConnectorListing {
  return {
    id, name, publisher: `${name} Inc.`, category: "Payments", also_in: [], tagline: `${name} in one line.`, builtin: false,
    description: `${name} for the business.`, capabilities: ["Read invoices"],
    availability: "Official", docs_url: `https://example.com/${id}`, transport: "streamable_http", url: `https://mcp.example.com/${id}`,
    auth: "bearer", featured: false, ...change,
  };
}

export function connector(id: string, name: string, change: Partial<ConnectorInfo> = {}): ConnectorInfo {
  return {
    id, listing_id: null, name, transport: "streamable_http", url: "https://mcp.example.com", command: null, args: [], auth: "none",
    has_secret: false, status: "connected", error: null, tool_count: 2, created_at: AT, checked_at: AT, ...change,
  };
}

export function approval(id: string, change: Partial<Approval> = {}): Approval {
  return {
    id, assistant_id: "a1", assistant_name: "Accountant", connector_id: "c1", tool: "send_invoice", arguments: { customer: "Lee", amount: 120 },
    reason: "The order shipped, so the invoice is due.", status: "pending", result: null, created_at: AT, decided_at: null, decided_by: null,
    note: null, ...change,
  };
}
