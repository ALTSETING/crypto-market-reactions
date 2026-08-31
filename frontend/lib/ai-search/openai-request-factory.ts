import "server-only";

export const OPENAI_RESPONSES_ENDPOINT = "https://api.openai.com/v1/responses";

const APPROVED_MODEL = "gpt-5-mini";
const MAX_INPUT_CHARS = 4_000;
const MAX_INSTRUCTION_CHARS = 12_000;
const MAX_OUTPUT_TOKENS = 2_000;
const MAX_SCHEMA_CHARS = 50_000;

type JsonSchema = Readonly<Record<string, unknown>>;

interface ResponseRequestOptions {
  model: string;
  input: string;
  instructions: string;
  maxOutputTokens: number;
}

interface StructuredResponseRequestOptions extends ResponseRequestOptions {
  schemaName: string;
  schema: JsonSchema;
}

export interface PlainResponseRequest {
  model: string;
  store: false;
  max_output_tokens: number;
  reasoning: { effort: "minimal" };
  instructions: string;
  input: string;
}

export interface StructuredResponseRequest extends PlainResponseRequest {
  text: {
    format: {
      type: "json_schema";
      name: string;
      strict: true;
      schema: JsonSchema;
    };
  };
}

export type OpenAiResponseRequest = PlainResponseRequest | StructuredResponseRequest;

export interface OpenAiResponseBody {
  output_text?: string;
  output?: Array<{ content?: Array<{ type?: string; text?: string }> }>;
  model?: string;
  usage?: {
    input_tokens?: number;
    output_tokens?: number;
    total_tokens?: number;
    input_tokens_details?: { cached_tokens?: number };
  };
}

export class OpenAiRequestValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "OpenAiRequestValidationError";
  }
}

function boundedText(value: string, field: string, maximum: number): string {
  if (typeof value !== "string" || value.length < 1 || value.length > maximum) {
    throw new OpenAiRequestValidationError(`${field} is outside the canonical request bounds.`);
  }
  return value;
}

function validateBaseOptions(options: ResponseRequestOptions): void {
  if (options.model !== APPROVED_MODEL) throw new OpenAiRequestValidationError("The canonical request requires gpt-5-mini.");
  boundedText(options.input, "input", MAX_INPUT_CHARS);
  boundedText(options.instructions, "instructions", MAX_INSTRUCTION_CHARS);
  if (!Number.isInteger(options.maxOutputTokens) || options.maxOutputTokens < 1 || options.maxOutputTokens > MAX_OUTPUT_TOKENS) {
    throw new OpenAiRequestValidationError("max_output_tokens is outside the canonical request bounds.");
  }
}

function objectValue(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function validateObjectSchemas(node: unknown, path: string): void {
  if (!objectValue(node)) throw new OpenAiRequestValidationError(`${path} must be a JSON Schema object.`);
  if (node.type === "object") {
    if (node.additionalProperties !== false || !objectValue(node.properties) || !Array.isArray(node.required)) {
      throw new OpenAiRequestValidationError(`${path} object schemas require properties, required, and additionalProperties=false.`);
    }
    const propertyNames = Object.keys(node.properties).sort();
    const required = node.required;
    if (required.some((value) => typeof value !== "string") || [...required].sort().join("\u0000") !== propertyNames.join("\u0000")) {
      throw new OpenAiRequestValidationError(`${path} required fields must exactly match properties.`);
    }
    for (const [name, property] of Object.entries(node.properties)) validateObjectSchemas(property, `${path}.properties.${name}`);
  }
  if (Array.isArray(node.anyOf)) {
    if (node.anyOf.length < 1) throw new OpenAiRequestValidationError(`${path}.anyOf must not be empty.`);
    node.anyOf.forEach((branch, index) => validateObjectSchemas(branch, `${path}.anyOf[${index}]`));
  }
  if (node.items !== undefined) validateObjectSchemas(node.items, `${path}.items`);
}

export function validateStructuredResponseSchema(schema: JsonSchema): void {
  let serialized: string;
  try {
    serialized = JSON.stringify(schema);
  } catch {
    throw new OpenAiRequestValidationError("schema must be JSON serializable.");
  }
  if (!serialized || serialized.length > MAX_SCHEMA_CHARS) throw new OpenAiRequestValidationError("schema is outside the canonical request bounds.");
  if (schema.type !== "object") throw new OpenAiRequestValidationError("The structured response schema root must be an object.");
  validateObjectSchemas(schema, "schema");
}

export function buildPlainResponseRequest(options: ResponseRequestOptions): PlainResponseRequest {
  validateBaseOptions(options);
  return {
    model: options.model,
    store: false,
    max_output_tokens: options.maxOutputTokens,
    reasoning: { effort: "minimal" },
    instructions: options.instructions,
    input: options.input,
  };
}

export function buildStructuredResponseRequest(options: StructuredResponseRequestOptions): StructuredResponseRequest {
  validateBaseOptions(options);
  if (!/^[A-Za-z0-9_-]{1,64}$/.test(options.schemaName)) throw new OpenAiRequestValidationError("schema name is invalid.");
  validateStructuredResponseSchema(options.schema);
  return {
    ...buildPlainResponseRequest(options),
    text: {
      format: {
        type: "json_schema",
        name: options.schemaName,
        strict: true,
        schema: options.schema,
      },
    },
  };
}

export function assertCanonicalResponseRequest(body: OpenAiResponseRequest): void {
  const keys = Object.keys(body).sort().join(",");
  const plainKeys = "input,instructions,max_output_tokens,model,reasoning,store";
  const structuredKeys = `${plainKeys},text`;
  const isStructured = "text" in body;
  if (keys !== (isStructured ? structuredKeys : plainKeys)) throw new OpenAiRequestValidationError("The request contains non-canonical parameters.");
  const rebuilt = isStructured
    ? buildStructuredResponseRequest({
      model: body.model,
      input: body.input,
      instructions: body.instructions,
      maxOutputTokens: body.max_output_tokens,
      schemaName: body.text.format.name,
      schema: body.text.format.schema,
    })
    : buildPlainResponseRequest({
      model: body.model,
      input: body.input,
      instructions: body.instructions,
      maxOutputTokens: body.max_output_tokens,
    });
  if (JSON.stringify(rebuilt) !== JSON.stringify(body)) throw new OpenAiRequestValidationError("The request does not match canonical serialization.");
}

export function extractOpenAiOutputText(body: OpenAiResponseBody): string | null {
  const text = body.output_text
    ?? body.output?.flatMap((item) => item.content ?? []).find((item) => item.type === "output_text")?.text;
  return typeof text === "string" && text.length > 0 ? text : null;
}
