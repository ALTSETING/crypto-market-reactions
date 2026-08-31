import "server-only";

import { AI_RESOLUTION_JSON_SCHEMA } from "@/lib/ai-search/schema";
import { AI_TOPICS } from "@/types/ai-search";
import { ASSETS, HORIZONS } from "@/types/events";

const OPENAI_RESPONSES_ENDPOINT = "https://api.openai.com/v1/responses";
const MINI_MODEL = "gpt-5-mini";
const TERRA_MODEL = "gpt-5.6-terra";
const FIXED_INPUT = "Classify this neutral request for historical database analysis.";
const DEFAULT_TIMEOUT_MS = 15_000;

type JsonSchema = Readonly<Record<string, unknown>>;

export const SCHEMA_BISECT_VARIANTS = ["P", "A", "B", "C", "D", "E", "F", "T", "D0", "F1", "F2"] as const;
export type SchemaBisectVariantId = (typeof SCHEMA_BISECT_VARIANTS)[number];
export type SchemaBisectResultCode = "PASS" | "HTTP_400" | "ERROR";
export type SchemaBisectCategory =
  | "NONE"
  | "BAD_REQUEST"
  | "AUTHENTICATION"
  | "PERMISSION"
  | "MODEL_NOT_FOUND"
  | "RATE_OR_BILLING"
  | "UPSTREAM"
  | "TIMEOUT"
  | "CONNECTION"
  | "UNKNOWN";

export interface SchemaBisectResult {
  variant: SchemaBisectVariantId;
  model: typeof MINI_MODEL | typeof TERRA_MODEL;
  result: SchemaBisectResultCode;
  category: SchemaBisectCategory;
  latencyMs: number;
}

interface RunOptions {
  apiKey: string;
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
}

const NULLABLE_STRING = { anyOf: [{ type: "string" }, { type: "null" }] } as const;
const A_SCHEMA = {
  type: "object",
  properties: { intent: { type: "string", enum: ["database", "clarification"] } },
  required: ["intent"],
  additionalProperties: false,
} as const;
const B_SCHEMA = {
  type: "object",
  properties: {
    ...A_SCHEMA.properties,
    asset: { anyOf: [{ type: "string", enum: ASSETS }, { type: "null" }] },
    horizon: { anyOf: [{ type: "string", enum: HORIZONS }, { type: "null" }] },
  },
  required: ["intent", "asset", "horizon"],
  additionalProperties: false,
} as const;
const C_SCHEMA = {
  type: "object",
  properties: {
    ...B_SCHEMA.properties,
    topic: { anyOf: [{ type: "string", enum: AI_TOPICS }, { type: "null" }] },
  },
  required: ["intent", "asset", "horizon", "topic"],
  additionalProperties: false,
} as const;
const D0_SCHEMA = {
  type: "object",
  properties: { ...C_SCHEMA.properties, entity: NULLABLE_STRING },
  required: ["intent", "asset", "horizon", "topic", "entity"],
  additionalProperties: false,
} as const;
const D_SCHEMA = {
  type: "object",
  properties: {
    ...C_SCHEMA.properties,
    entity: {
      anyOf: [
        { type: "string", pattern: "^[\\p{L}\\p{N}][\\p{L}\\p{N} .&'’_-]{0,79}$" },
        { type: "null" },
      ],
    },
  },
  required: ["intent", "asset", "horizon", "topic", "entity"],
  additionalProperties: false,
} as const;
const E_SCHEMA = {
  type: "object",
  properties: {
    status: { type: "string", enum: ["ready", "clarification", "rejected"] },
    intent: { anyOf: [D_SCHEMA, { type: "null" }] },
    message: NULLABLE_STRING,
  },
  required: ["status", "intent", "message"],
  additionalProperties: false,
} as const;

function removeLengthKeywords(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(removeLengthKeywords);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>)
      .filter(([key]) => key !== "minLength" && key !== "maxLength")
      .map(([key, item]) => [key, removeLengthKeywords(item)]),
  );
}

function removeProperty(schema: JsonSchema, property: string): JsonSchema {
  const clone = removeLengthKeywords(schema) as Record<string, unknown>;
  const intentBranch = ((clone.properties as Record<string, unknown>).intent as { anyOf: Array<Record<string, unknown>> }).anyOf[0];
  const properties = intentBranch.properties as Record<string, unknown>;
  delete properties[property];
  intentBranch.required = (intentBranch.required as string[]).filter((name) => name !== property);
  return clone;
}

const F_SCHEMA = removeLengthKeywords(AI_RESOLUTION_JSON_SCHEMA) as JsonSchema;
const F1_SCHEMA = removeProperty(AI_RESOLUTION_JSON_SCHEMA, "comparison");
const F2_SCHEMA = removeProperty(AI_RESOLUTION_JSON_SCHEMA, "amount");

const STRUCTURED_SCHEMAS: Record<Exclude<SchemaBisectVariantId, "P" | "T">, JsonSchema> = {
  A: A_SCHEMA,
  B: B_SCHEMA,
  C: C_SCHEMA,
  D: D_SCHEMA,
  E: E_SCHEMA,
  F: F_SCHEMA,
  D0: D0_SCHEMA,
  F1: F1_SCHEMA,
  F2: F2_SCHEMA,
};

export function isSchemaBisectVariant(value: unknown): value is SchemaBisectVariantId {
  return typeof value === "string" && (SCHEMA_BISECT_VARIANTS as readonly string[]).includes(value);
}

export function buildSchemaBisectRequest(variant: SchemaBisectVariantId): {
  model: typeof MINI_MODEL | typeof TERRA_MODEL;
  body: Record<string, unknown>;
} {
  const model = variant === "T" ? TERRA_MODEL : MINI_MODEL;
  if (variant === "P") {
    return {
      model,
      body: { model, store: false, max_output_tokens: 32, input: "Reply with the word OK." },
    };
  }
  const schema = variant === "T" ? A_SCHEMA : STRUCTURED_SCHEMAS[variant];
  return {
    model,
    body: {
      model,
      store: false,
      max_output_tokens: 256,
      input: FIXED_INPUT,
      text: {
        format: {
          type: "json_schema",
          name: `schema_bisect_${variant.toLowerCase()}`,
          strict: true,
          schema,
        },
      },
    },
  };
}

function httpCategory(status: number): SchemaBisectCategory {
  if (status === 400) return "BAD_REQUEST";
  if (status === 401) return "AUTHENTICATION";
  if (status === 403) return "PERMISSION";
  if (status === 404) return "MODEL_NOT_FOUND";
  if (status === 429) return "RATE_OR_BILLING";
  if (status >= 500) return "UPSTREAM";
  return "UNKNOWN";
}

function transportCategory(error: unknown): SchemaBisectCategory {
  if (error instanceof DOMException && error.name === "AbortError") return "TIMEOUT";
  if (error instanceof TypeError) return "CONNECTION";
  return "UNKNOWN";
}

export async function runSchemaBisectVariant(
  variant: SchemaBisectVariantId,
  options: RunOptions,
): Promise<SchemaBisectResult> {
  const { model, body } = buildSchemaBisectRequest(variant);
  const fetchImpl = options.fetchImpl ?? fetch;
  const maximumAttempts = variant === "P" ? 2 : 1;
  const startedAt = performance.now();
  let category: SchemaBisectCategory = "UNKNOWN";

  for (let attempt = 1; attempt <= maximumAttempts; attempt += 1) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), options.timeoutMs ?? DEFAULT_TIMEOUT_MS);
    try {
      const response = await fetchImpl(OPENAI_RESPONSES_ENDPOINT, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${options.apiKey}`,
          "Content-Type": "application/json",
        },
        signal: controller.signal,
        body: JSON.stringify(body),
      });
      if (response.ok) {
        return { variant, model, result: "PASS", category: "NONE", latencyMs: Math.round(performance.now() - startedAt) };
      }
      category = httpCategory(response.status);
      if (response.status === 400) {
        return { variant, model, result: "HTTP_400", category, latencyMs: Math.round(performance.now() - startedAt) };
      }
      if (!(variant === "P" && response.status >= 500 && attempt === 1)) break;
    } catch (error) {
      category = transportCategory(error);
      if (!(variant === "P" && attempt === 1 && (category === "TIMEOUT" || category === "CONNECTION"))) break;
    } finally {
      clearTimeout(timeout);
    }
  }
  return { variant, model, result: "ERROR", category, latencyMs: Math.round(performance.now() - startedAt) };
}
