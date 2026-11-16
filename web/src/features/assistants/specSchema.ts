/**
 * Client-side checking of an assistant spec against the JSON Schema from GET /v1/assistants/schema (Pydantic's
 * `AssistantSpec.model_json_schema()`). Covers the subset that schema uses: `type`, `enum`, `properties`,
 * `required`, `additionalProperties` (false or a schema), `items`, `anyOf`, local `$ref` (`#/$defs/<name>`),
 * `minLength` / `maxLength`, `minimum` / `maximum`. The API validates again; this only gives errors while typing.
 */
import type { AssistantSpec } from "../../api/types";

export type JsonSchema = {
  type?: string | string[];
  enum?: unknown[];
  properties?: Record<string, JsonSchema>;
  required?: string[];
  additionalProperties?: boolean | JsonSchema;
  items?: JsonSchema;
  anyOf?: JsonSchema[];
  $ref?: string;
  $defs?: Record<string, JsonSchema>;
  minLength?: number;
  maxLength?: number;
  minimum?: number;
  maximum?: number;
  title?: string;
  description?: string;
  default?: unknown;
};

/** `path` is like `policy.tools.crm/send` or `connectors[0]`; empty for the whole spec. */
export type SpecError = { path: string; message: string };

const NAMES: Record<string, string> = {
  string: "a string", integer: "an integer", number: "a number", boolean: "true or false",
  array: "a list", object: "an object", null: "null",
};

/** A starting point for a new assistant (the example from the spec's docstring, without connectors). */
export const TEMPLATE = {
  name: "Accountant",
  role: "Keeps the books and prepares the monthly report",
  department: "Finance",
  instructions: "Reconcile new transactions every week. Post the month-end summary to the finance topic.",
  connectors: [],
  knowledge: { departments: ["Finance"], document_kinds: [] },
  shares: ["finance", "month-end"],
  policy: { default: "ask", tools: {} },
  max_tool_rounds: 6,
} satisfies AssistantSpec;

/** Parses the editor's text and checks it: the spec when it is valid, else the errors (a JSON error has no path). */
export function parseSpec(text: string, schema: JsonSchema): { spec: AssistantSpec | null; errors: SpecError[] } {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch (error) {
    return { spec: null, errors: [{ path: "", message: `Not valid JSON: ${(error as Error).message}` }] };
  }
  const errors = validate(value, schema);
  return { spec: errors.length ? null : (value as AssistantSpec), errors };
}

/** Every error of `value` against `schema`; `root` holds the `$defs` (the schema itself at the top). */
export function validate(value: unknown, schema: JsonSchema, root: JsonSchema = schema): SpecError[] {
  const errors: SpecError[] = [];
  check(value, schema, root, "", errors);
  return errors;
}

function typeOf(value: unknown): string {
  if (value === null) return "null";
  if (Array.isArray(value)) return "array";
  if (typeof value === "number") return Number.isInteger(value) ? "integer" : "number";
  return typeof value;
}

function isType(value: unknown, type: string): boolean {
  const actual = typeOf(value);
  return actual === type || (type === "number" && actual === "integer");
}

function describe(schema: JsonSchema): string {
  if (schema.anyOf) return schema.anyOf.map(describe).join(" or ");
  const types = [schema.type ?? []].flat();
  return types.length ? types.map((t) => NAMES[t] ?? t).join(" or ") : "a valid value";
}

const join = (path: string, key: string) => (path ? `${path}.${key}` : key);

function check(value: unknown, schema: JsonSchema, root: JsonSchema, path: string, errors: SpecError[]): void {
  if (schema.$ref) {
    const target = root.$defs?.[schema.$ref.replace("#/$defs/", "")];
    if (target) check(value, target, root, path, errors);
    return;
  }
  if (schema.anyOf) {
    if (!schema.anyOf.some((option) => validate(value, option, root).length === 0)) errors.push({ path, message: `must be ${describe(schema)}` });
    return;
  }
  const types = [schema.type ?? []].flat();
  if (types.length && !types.some((t) => isType(value, t))) {
    errors.push({ path, message: `must be ${describe(schema)}` });
    return;
  }
  if (schema.enum && !schema.enum.includes(value)) {
    errors.push({ path, message: `must be one of ${schema.enum.map((v) => JSON.stringify(v)).join(", ")}` });
    return;
  }
  if (typeof value === "string") {
    const length = [...value].length; // characters, as the API counts them
    if (schema.minLength !== undefined && length < schema.minLength)
      errors.push({ path, message: schema.minLength === 1 ? "must not be empty" : `must be at least ${schema.minLength} characters` });
    if (schema.maxLength !== undefined && length > schema.maxLength) errors.push({ path, message: `must be at most ${schema.maxLength} characters` });
  }
  if (typeof value === "number") {
    if (schema.minimum !== undefined && value < schema.minimum) errors.push({ path, message: `must be at least ${schema.minimum}` });
    if (schema.maximum !== undefined && value > schema.maximum) errors.push({ path, message: `must be at most ${schema.maximum}` });
  }
  if (Array.isArray(value) && schema.items) {
    value.forEach((item, i) => check(item, schema.items!, root, `${path}[${i}]`, errors));
  }
  if (typeOf(value) === "object") {
    const object = value as Record<string, unknown>;
    for (const key of schema.required ?? []) if (!(key in object)) errors.push({ path: join(path, key), message: "is required" });
    for (const [key, item] of Object.entries(object)) {
      const property = schema.properties?.[key];
      if (property) check(item, property, root, join(path, key), errors);
      else if (schema.additionalProperties === false) errors.push({ path: join(path, key), message: "is not a known field" });
      else if (typeof schema.additionalProperties === "object") check(item, schema.additionalProperties, root, join(path, key), errors);
    }
  }
}
