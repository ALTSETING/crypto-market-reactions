const UNSUPPORTED_KEYWORDS = new Set([
  "allOf", "not", "if", "then", "else", "dependentRequired", "dependentSchemas",
  "minLength", "maxLength",
]);
const JSON_TYPES = new Set(["string", "number", "integer", "boolean", "object", "array", "null"]);

export type StrictJsonSchema = Readonly<Record<string, unknown>>;

export class StrictSchemaValidationError extends Error {
  readonly code = "OPENAI_SCHEMA_INVALID";

  constructor(message: string) {
    super(message);
    this.name = "StrictSchemaValidationError";
  }
}

function record(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function fail(path: string, message: string): never {
  throw new StrictSchemaValidationError(`${path}: ${message}`);
}

function declaredTypes(node: Record<string, unknown>, path: string): Set<string> {
  const raw = node.type;
  const values = typeof raw === "string" ? [raw] : Array.isArray(raw) ? raw : [];
  if (values.length === 0 || values.some((value) => typeof value !== "string" || !JSON_TYPES.has(value))) {
    fail(path, "type must use the supported JSON Schema types.");
  }
  if (new Set(values).size !== values.length) fail(path, "type must not contain duplicates.");
  return new Set(values as string[]);
}

function enumValueMatches(value: unknown, types: Set<string>): boolean {
  if (value === null) return types.has("null");
  if (typeof value === "string") return types.has("string");
  if (typeof value === "boolean") return types.has("boolean");
  if (typeof value === "number") {
    return Number.isFinite(value) && (types.has("number") || (types.has("integer") && Number.isInteger(value)));
  }
  return false;
}

function validateNode(node: unknown, path: string, root: boolean): void {
  if (!record(node)) fail(path, "schema nodes must be objects.");
  for (const keyword of UNSUPPORTED_KEYWORDS) {
    if (keyword in node) fail(path, `${keyword} is not supported by the OpenAI Structured Outputs subset.`);
  }
  if (root && "anyOf" in node) fail(path, "the root must not use anyOf.");

  if ("anyOf" in node) {
    if (!Array.isArray(node.anyOf) || node.anyOf.length < 2) fail(`${path}.anyOf`, "must contain at least two schemas.");
    node.anyOf.forEach((branch, index) => validateNode(branch, `${path}.anyOf[${index}]`, false));
    return;
  }

  const types = declaredTypes(node, path);
  if (node.enum !== undefined) {
    if (!Array.isArray(node.enum) || node.enum.length === 0) fail(`${path}.enum`, "must be a non-empty array.");
    if (node.enum.some((value) => !enumValueMatches(value, types))) {
      fail(`${path}.enum`, "contains a value that conflicts with its nullable or declared type.");
    }
  }

  const objectKeywordsPresent = "properties" in node || "required" in node || "additionalProperties" in node;
  if (types.has("object") || objectKeywordsPresent) {
    if (types.size !== 1 || !types.has("object")) fail(path, "object schemas must declare type object.");
    if (!record(node.properties)) fail(path, "object schemas require properties.");
    if (node.additionalProperties !== false) fail(path, "object schemas require additionalProperties=false.");
    if (!Array.isArray(node.required) || node.required.some((value) => typeof value !== "string")) {
      fail(path, "object schemas require a string required array.");
    }
    const properties = Object.keys(node.properties);
    const required = node.required as string[];
    if (new Set(required).size !== required.length) fail(`${path}.required`, "must not contain duplicates.");
    const missing = properties.filter((name) => !required.includes(name));
    const extra = required.filter((name) => !properties.includes(name));
    if (missing.length > 0) fail(`${path}.required`, `is missing properties: ${missing.join(", ")}.`);
    if (extra.length > 0) fail(`${path}.required`, `contains unknown properties: ${extra.join(", ")}.`);
    for (const [name, property] of Object.entries(node.properties)) {
      validateNode(property, `${path}.properties.${name}`, false);
    }
  }

  if (types.has("array")) {
    if (types.size !== 1) fail(path, "array schemas must declare only type array.");
    if (!("items" in node)) fail(path, "array schemas require items.");
    validateNode(node.items, `${path}.items`, false);
  }
  if (node.pattern !== undefined && typeof node.pattern !== "string") fail(`${path}.pattern`, "must be a string.");
}

export function validateStrictStructuredSchema(schema: unknown): asserts schema is StrictJsonSchema {
  validateNode(schema, "schema", true);
  if ((schema as Record<string, unknown>).type !== "object") fail("schema", "the root must declare type object.");
}

export function validateStructuredTextFormat(format: unknown): asserts format is {
  type: "json_schema"; name: string; strict: true; schema: StrictJsonSchema;
} {
  if (!record(format)) fail("text.format", "must be an object.");
  const keys = Object.keys(format).sort().join(",");
  if (keys !== "name,schema,strict,type") fail("text.format", "must contain only name, schema, strict, and type.");
  if (format.type !== "json_schema") fail("text.format.type", "must be json_schema.");
  if (format.strict !== true) fail("text.format.strict", "must be true.");
  if (typeof format.name !== "string" || !/^[A-Za-z0-9_-]{1,64}$/.test(format.name)) {
    fail("text.format.name", "must contain 1-64 allowlisted characters.");
  }
  validateStrictStructuredSchema(format.schema);
}
