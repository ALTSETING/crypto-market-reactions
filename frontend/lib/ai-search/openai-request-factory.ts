import "server-only";

import { validateStructuredTextFormat, type StrictJsonSchema } from "@/lib/ai-search/strict-schema";

export const OPENAI_RESPONSES_ENDPOINT = "https://api.openai.com/v1/responses";
const APPROVED_MODEL = "gpt-5-mini";
const MAX_INPUT_CHARS = 4_000;
const MAX_INSTRUCTION_CHARS = 12_000;
const MAX_OUTPUT_TOKENS = 2_000;
const MAX_SCHEMA_CHARS = 50_000;

interface StructuredResponseRequestOptions {
  model: string;
  input: string;
  instructions: string;
  maxOutputTokens: number;
  schemaName: string;
  schema: StrictJsonSchema;
}

export interface StructuredResponseRequest {
  model: string;
  store: false;
  max_output_tokens: number;
  reasoning: { effort: "minimal" };
  instructions: string;
  input: string;
  text: { format: { type: "json_schema"; name: string; strict: true; schema: StrictJsonSchema } };
}

export type OpenAiResponseRequest = StructuredResponseRequest;

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

function boundedText(value: string, field: string, maximum: number): string {
  if (typeof value !== "string" || value.length < 1 || value.length > maximum) {
    throw new Error(`${field} is outside the canonical request bounds.`);
  }
  return value;
}

export function buildStructuredResponseRequest(options: StructuredResponseRequestOptions): StructuredResponseRequest {
  if (options.model !== APPROVED_MODEL) throw new Error("The canonical request requires gpt-5-mini.");
  boundedText(options.input, "input", MAX_INPUT_CHARS);
  boundedText(options.instructions, "instructions", MAX_INSTRUCTION_CHARS);
  if (!Number.isInteger(options.maxOutputTokens) || options.maxOutputTokens < 1 || options.maxOutputTokens > MAX_OUTPUT_TOKENS) {
    throw new Error("max_output_tokens is outside the canonical request bounds.");
  }
  const format = { type: "json_schema", name: options.schemaName, strict: true, schema: options.schema } as const;
  validateStructuredTextFormat(format);
  if (JSON.stringify(format.schema).length > MAX_SCHEMA_CHARS) throw new Error("schema is outside the canonical request bounds.");
  return {
    model: options.model,
    store: false,
    max_output_tokens: options.maxOutputTokens,
    reasoning: { effort: "minimal" },
    instructions: options.instructions,
    input: options.input,
    text: { format },
  };
}

export function assertCanonicalResponseRequest(body: OpenAiResponseRequest): void {
  if (!body || typeof body !== "object" || Array.isArray(body)) throw new Error("The request must be an object.");
  if (Object.keys(body).sort().join(",") !== "input,instructions,max_output_tokens,model,reasoning,store,text") {
    throw new Error("The request contains non-canonical parameters.");
  }
  validateStructuredTextFormat((body as { text?: { format?: unknown } }).text?.format);
  const rebuilt = buildStructuredResponseRequest({
    model: body.model,
    input: body.input,
    instructions: body.instructions,
    maxOutputTokens: body.max_output_tokens,
    schemaName: body.text.format.name,
    schema: body.text.format.schema,
  });
  if (JSON.stringify(rebuilt) !== JSON.stringify(body)) throw new Error("The request does not match canonical serialization.");
}

export function extractOpenAiOutputText(body: OpenAiResponseBody): string | null {
  const topLevel = typeof body.output_text === "string" && body.output_text.length > 0 ? body.output_text : null;
  if (topLevel) return topLevel;
  const nested = body.output?.flatMap((item) => item.content ?? [])
    .find((item) => item.type === "output_text" && typeof item.text === "string" && item.text.length > 0)?.text;
  return nested ?? null;
}
