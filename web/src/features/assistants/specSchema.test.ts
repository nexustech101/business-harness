import { expect, it } from "vitest";
import { specSchema } from "../../test/fixtures";
import { parseSpec, TEMPLATE, validate } from "./specSchema";

it("the template and a minimal spec are valid", () => {
  expect(validate(TEMPLATE, specSchema)).toEqual([]);
  expect(parseSpec('{"name": "Marketer", "role": "Plans campaigns"}', specSchema).spec).toEqual({ name: "Marketer", role: "Plans campaigns" });
});

it("reports invalid JSON without a path", () => {
  const { spec, errors } = parseSpec('{"name": ', specSchema);
  expect(spec).toBeNull();
  expect(errors).toHaveLength(1);
  expect(errors[0]!.path).toBe("");
  expect(errors[0]!.message).toMatch(/^Not valid JSON: /);
});

it("checks required fields, types, lengths, ranges and unknown fields", () => {
  expect(validate({ name: "", instructions: 3, max_tool_rounds: 21, colour: "red" }, specSchema)).toEqual([
    { path: "role", message: "is required" },
    { path: "name", message: "must not be empty" },
    { path: "instructions", message: "must be a string" },
    { path: "max_tool_rounds", message: "must be at most 20" },
    { path: "colour", message: "is not a known field" },
  ]);
  expect(validate({ name: "x".repeat(61), role: "r", max_tool_rounds: 1.5 }, specSchema)).toEqual([
    { path: "name", message: "must be at most 60 characters" },
    { path: "max_tool_rounds", message: "must be an integer" },
  ]);
  expect(validate([], specSchema)).toEqual([{ path: "", message: "must be an object" }]);
});

it("follows $ref, anyOf, items, enums and additionalProperties schemas", () => {
  const spec = {
    name: "A", role: "B", department: 7, connectors: ["crm", 2],
    knowledge: { departments: "Finance" },
    policy: { default: "sometimes", tools: { "crm/send": "auto", "crm/delete": "never" } },
  };
  expect(validate(spec, specSchema)).toEqual([
    { path: "department", message: "must be a string or null" },
    { path: "connectors[1]", message: "must be a string" },
    { path: "knowledge.departments", message: "must be a list" },
    { path: "policy.default", message: 'must be one of "auto", "ask", "deny"' },
    { path: "policy.tools.crm/delete", message: 'must be one of "auto", "ask", "deny"' },
  ]);
  expect(validate({ name: "A", role: "B", department: null }, specSchema)).toEqual([]);
});
