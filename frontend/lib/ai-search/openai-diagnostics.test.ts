import { afterEach, describe, expect, it, vi } from "vitest";

import { OpenAiRequestError, publicOpenAiDiagnosticCode, requestOpenAiResponse, type OpenAiDiagnosticCategory } from "@/lib/ai-search/openai-diagnostics";
import { buildStructuredResponseRequest } from "@/lib/ai-search/openai-request-factory";
import { StrictSchemaValidationError } from "@/lib/ai-search/strict-schema";

const diagnosticSchema = {
  type: "object",
  additionalProperties: false,
  required: ["ok"],
  properties: { ok: { type: "boolean" } },
} as const;

function requestBody(input: string, instructions: string, maxOutputTokens: number) {
  return buildStructuredResponseRequest({
    model: "gpt-5-mini", input, instructions, maxOutputTokens,
    schemaName: "diagnostic_resolution", schema: diagnosticSchema,
  });
}

function errorResponse(status: number, type: string, code: string | null, param: string | null, message = "sensitive raw message") {
  return Response.json({ error: { type, code, param, message, authorization: "Bearer secret-key", question: "private question", prompt: "private prompt" } }, {
    status,
    headers: { "x-request-id": "req_safe_123" },
  });
}

async function rejectedDiagnostic(response: Response) {
  const diagnostics: unknown[] = [];
  const fetchImpl = vi.fn(async () => response.clone());
  await expect(requestOpenAiResponse({
    apiKey: "secret-key",
    model: "gpt-5-mini",
    body: requestBody("private question", "private prompt", 50),
    timeoutMs: 50,
    fetchImpl,
    retryBackoffMs: 0,
    onDiagnostic: (diagnostic) => diagnostics.push(diagnostic),
  })).rejects.toBeInstanceOf(OpenAiRequestError);
  return { diagnostic: diagnostics.at(-1) as { category: OpenAiDiagnosticCategory; [key: string]: unknown }, fetchImpl };
}

describe("safe OpenAI diagnostics", () => {
  afterEach(() => vi.restoreAllMocks());

  it.each([
    [400, "invalid_request_error", "invalid_request", "input", "OPENAI_400_BAD_REQUEST"],
    [400, "invalid_request_error", "invalid_service_tier", "service_tier", "OPENAI_400_INVALID_SERVICE_TIER"],
    [401, "authentication_error", "invalid_api_key", null, "OPENAI_401_AUTHENTICATION"],
    [403, "permission_denied_error", "permission_denied", null, "OPENAI_403_PERMISSION_DENIED"],
    [404, "not_found_error", "model_not_found", "model", "OPENAI_404_MODEL_NOT_FOUND"],
    [429, "insufficient_quota", "credit_balance_exhausted", null, "OPENAI_429_CREDIT_EXHAUSTED"],
    [429, "insufficient_quota", "insufficient_quota", null, "OPENAI_429_CREDIT_EXHAUSTED"],
    [429, "insufficient_quota", "project_spend_limit_exceeded", null, "OPENAI_429_PROJECT_SPEND_LIMIT"],
    [429, "insufficient_quota", "organization_usage_limit_exceeded", null, "OPENAI_429_USAGE_LIMIT"],
    [429, "rate_limit_error", "rate_limit_exceeded", null, "OPENAI_429_RATE_LIMIT"],
    [500, "server_error", "server_error", null, "OPENAI_5XX_UPSTREAM"],
    [503, "server_error", "server_error", null, "OPENAI_5XX_UPSTREAM"],
    [418, "unknown_type", "unknown_code", "unknown_param", "OPENAI_UNKNOWN_REJECTION"],
  ] as const)("classifies HTTP %s safely", async (status, type, code, param, expected) => {
    vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const { diagnostic, fetchImpl } = await rejectedDiagnostic(errorResponse(status, type, code, param));
    expect(diagnostic).toMatchObject({ category: expected, httpStatus: status, requestId: "req_safe_123", model: "gpt-5-mini" });
    expect(fetchImpl).toHaveBeenCalledTimes(expected === "OPENAI_429_RATE_LIMIT" || expected === "OPENAI_5XX_UPSTREAM" ? 2 : 1);
    const serialized = JSON.stringify(diagnostic);
    expect(serialized).not.toMatch(/secret-key|private question|private prompt|sensitive raw message|authorization/iu);
  });

  it.each([
    [new DOMException("private timeout detail", "AbortError"), "OPENAI_TIMEOUT", "AbortError"],
    [new TypeError("private connection detail"), "OPENAI_CONNECTION_ERROR", "TypeError"],
    [new Error("private unknown detail"), "OPENAI_UNKNOWN_REJECTION", "UnknownError"],
  ] as const)("classifies transport failures without messages", async (failure, category, errorClass) => {
    const logs: unknown[] = [];
    vi.spyOn(console, "warn").mockImplementation((_label, diagnostic) => logs.push(diagnostic));
    const fetchImpl = vi.fn(async () => { throw failure; });
    const body = requestBody("private input", "private instructions", 50);
    await expect(requestOpenAiResponse({ apiKey: "secret-key", model: "gpt-5-mini", body, timeoutMs: 50, fetchImpl, retryBackoffMs: 0 })).rejects.toBeInstanceOf(OpenAiRequestError);
    expect(fetchImpl).toHaveBeenCalledTimes(category === "OPENAI_UNKNOWN_REJECTION" ? 1 : 2);
    expect(logs.at(-1)).toMatchObject({ category, errorClass });
    expect(JSON.stringify(logs)).not.toMatch(/secret-key|private timeout|private connection|private unknown/iu);
  });

  it("returns a successful response without diagnostic logging", async () => {
    const warning = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const response = await requestOpenAiResponse({
      apiKey: "secret-key", model: "gpt-5-mini",
      body: requestBody("input", "instructions", 50),
      timeoutMs: 50,
      fetchImpl: vi.fn(async () => Response.json({ output_text: "ok" })),
    });
    expect(response.ok).toBe(true);
    expect(warning).not.toHaveBeenCalled();
  });

  it.each([
    ["OPENAI_400_BAD_REQUEST", "OPENAI_400_BAD_REQUEST"],
    ["OPENAI_400_INVALID_SERVICE_TIER", "OPENAI_400_BAD_REQUEST"],
    ["OPENAI_401_AUTHENTICATION", "OPENAI_401_AUTHENTICATION"],
    ["OPENAI_403_PERMISSION_DENIED", "OPENAI_403_PERMISSION_DENIED"],
    ["OPENAI_404_MODEL_NOT_FOUND", "OPENAI_404_MODEL_NOT_FOUND"],
    ["OPENAI_429_CREDIT_EXHAUSTED", "OPENAI_429_BILLING_OR_LIMIT"],
    ["OPENAI_429_PROJECT_SPEND_LIMIT", "OPENAI_429_BILLING_OR_LIMIT"],
    ["OPENAI_429_USAGE_LIMIT", "OPENAI_429_BILLING_OR_LIMIT"],
    ["OPENAI_429_RATE_LIMIT", "OPENAI_429_BILLING_OR_LIMIT"],
    ["OPENAI_5XX_UPSTREAM", "OPENAI_5XX_UPSTREAM"],
    ["OPENAI_TIMEOUT", "OPENAI_TIMEOUT"],
    ["OPENAI_CONNECTION_ERROR", "OPENAI_CONNECTION_ERROR"],
    ["OPENAI_UNKNOWN_REJECTION", "OPENAI_UNKNOWN_REJECTION"],
  ] as const)("maps %s to public code %s", (category, expected) => {
    expect(publicOpenAiDiagnosticCode(category)).toBe(expected);
  });

  it("rejects a tampered schema before fetch", async () => {
    const fetchImpl = vi.fn();
    const body = buildStructuredResponseRequest({
      model: "gpt-5-mini", input: "input", instructions: "instructions", maxOutputTokens: 50,
      schemaName: "safe_schema",
      schema: { type: "object", additionalProperties: false, required: ["ok"], properties: { ok: { type: "boolean" } } },
    });
    const tampered = {
      ...body,
      text: { format: { ...body.text.format, schema: { ...body.text.format.schema, additionalProperties: true } } },
    };
    await expect(requestOpenAiResponse({
      apiKey: "secret-key", model: "gpt-5-mini", body: tampered, timeoutMs: 50, fetchImpl,
    })).rejects.toBeInstanceOf(StrictSchemaValidationError);
    expect(fetchImpl).not.toHaveBeenCalled();
  });
});
