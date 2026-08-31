import "server-only";

import { assertCanonicalResponseRequest, OPENAI_RESPONSES_ENDPOINT, type OpenAiResponseRequest } from "@/lib/ai-search/openai-request-factory";
import type { PublicOpenAiDiagnosticCode } from "@/types/ai-search";

export const OPENAI_DIAGNOSTIC_CATEGORIES = [
  "OPENAI_400_BAD_REQUEST",
  "OPENAI_400_INVALID_SERVICE_TIER",
  "OPENAI_401_AUTHENTICATION",
  "OPENAI_403_PERMISSION_DENIED",
  "OPENAI_404_MODEL_NOT_FOUND",
  "OPENAI_429_CREDIT_EXHAUSTED",
  "OPENAI_429_PROJECT_SPEND_LIMIT",
  "OPENAI_429_USAGE_LIMIT",
  "OPENAI_429_RATE_LIMIT",
  "OPENAI_5XX_UPSTREAM",
  "OPENAI_TIMEOUT",
  "OPENAI_CONNECTION_ERROR",
  "OPENAI_UNKNOWN_REJECTION",
] as const;

export type OpenAiDiagnosticCategory = (typeof OPENAI_DIAGNOSTIC_CATEGORIES)[number];
export type OpenAiErrorClass = "OpenAiHttpError" | "AbortError" | "TypeError" | "UnknownError";

const ALLOWED_ERROR_TYPES = new Set([
  "invalid_request_error",
  "authentication_error",
  "permission_denied_error",
  "not_found_error",
  "rate_limit_error",
  "insufficient_quota",
  "server_error",
]);
const ALLOWED_ERROR_CODES = new Set([
  "invalid_api_key",
  "invalid_service_tier",
  "model_not_found",
  "credit_balance_exhausted",
  "insufficient_quota",
  "organization_spend_limit_exceeded",
  "project_spend_limit_exceeded",
  "organization_usage_limit_exceeded",
  "project_usage_limit_exceeded",
  "usage_limit_exceeded",
  "rate_limit_exceeded",
  "server_error",
]);
const ALLOWED_ERROR_PARAMS = new Set([
  "service_tier",
  "model",
  "max_output_tokens",
  "input",
  "text.format",
  "reasoning.effort",
]);

export interface OpenAiSafeDiagnostic {
  category: OpenAiDiagnosticCategory;
  httpStatus: number | null;
  errorClass: OpenAiErrorClass;
  errorType: string | null;
  errorCode: string | null;
  errorParam: string | null;
  requestId: string | null;
  model: string;
  attempt: number;
  latencyMs: number;
}

interface OpenAiErrorMetadata {
  type: string | null;
  code: string | null;
  param: string | null;
}

interface OpenAiRequestOptions {
  apiKey: string;
  model: string;
  body: OpenAiResponseRequest;
  timeoutMs: number;
  fetchImpl?: typeof fetch;
  retryBackoffMs?: number;
  onDiagnostic?: (diagnostic: OpenAiSafeDiagnostic) => void;
}

export function publicOpenAiDiagnosticCode(category: OpenAiDiagnosticCategory): PublicOpenAiDiagnosticCode {
  if (category === "OPENAI_400_BAD_REQUEST" || category === "OPENAI_400_INVALID_SERVICE_TIER") return "OPENAI_400_BAD_REQUEST";
  if (category === "OPENAI_401_AUTHENTICATION") return category;
  if (category === "OPENAI_403_PERMISSION_DENIED") return category;
  if (category === "OPENAI_404_MODEL_NOT_FOUND") return category;
  if (category.startsWith("OPENAI_429_")) return "OPENAI_429_BILLING_OR_LIMIT";
  if (category === "OPENAI_5XX_UPSTREAM" || category === "OPENAI_TIMEOUT" || category === "OPENAI_CONNECTION_ERROR") return category;
  return "OPENAI_UNKNOWN_REJECTION";
}

function allowlisted(value: unknown, allowlist: Set<string>): string | null {
  return typeof value === "string" && allowlist.has(value) ? value : null;
}

function safeRequestId(response: Response): string | null {
  const value = response.headers.get("x-request-id") ?? response.headers.get("request-id");
  return value && /^[A-Za-z0-9_-]{1,128}$/.test(value) ? value : null;
}

async function readSafeErrorMetadata(response: Response): Promise<OpenAiErrorMetadata> {
  try {
    const body = await response.json() as { error?: { type?: unknown; code?: unknown; param?: unknown } };
    return {
      type: allowlisted(body.error?.type, ALLOWED_ERROR_TYPES),
      code: allowlisted(body.error?.code, ALLOWED_ERROR_CODES),
      param: allowlisted(body.error?.param, ALLOWED_ERROR_PARAMS),
    };
  } catch {
    return { type: null, code: null, param: null };
  }
}

function categoryForHttp(status: number, metadata: OpenAiErrorMetadata): OpenAiDiagnosticCategory {
  if (status === 400) {
    return metadata.param === "service_tier" || metadata.code === "invalid_service_tier"
      ? "OPENAI_400_INVALID_SERVICE_TIER"
      : "OPENAI_400_BAD_REQUEST";
  }
  if (status === 401) return "OPENAI_401_AUTHENTICATION";
  if (status === 403) return "OPENAI_403_PERMISSION_DENIED";
  if (status === 404) return "OPENAI_404_MODEL_NOT_FOUND";
  if (status === 429) {
    if (metadata.code === "credit_balance_exhausted" || metadata.code === "insufficient_quota") return "OPENAI_429_CREDIT_EXHAUSTED";
    if (metadata.code === "organization_spend_limit_exceeded" || metadata.code === "project_spend_limit_exceeded") return "OPENAI_429_PROJECT_SPEND_LIMIT";
    if (metadata.code === "organization_usage_limit_exceeded" || metadata.code === "project_usage_limit_exceeded" || metadata.code === "usage_limit_exceeded") return "OPENAI_429_USAGE_LIMIT";
    if (metadata.code === "rate_limit_exceeded" || metadata.type === "rate_limit_error") return "OPENAI_429_RATE_LIMIT";
    return "OPENAI_UNKNOWN_REJECTION";
  }
  if (status >= 500) return "OPENAI_5XX_UPSTREAM";
  return "OPENAI_UNKNOWN_REJECTION";
}

function transportCategory(error: unknown): { category: OpenAiDiagnosticCategory; errorClass: OpenAiErrorClass } {
  if (error instanceof DOMException && error.name === "AbortError") return { category: "OPENAI_TIMEOUT", errorClass: "AbortError" };
  if (error instanceof TypeError) return { category: "OPENAI_CONNECTION_ERROR", errorClass: "TypeError" };
  return { category: "OPENAI_UNKNOWN_REJECTION", errorClass: "UnknownError" };
}

export function isRetryableOpenAiDiagnostic(category: OpenAiDiagnosticCategory): boolean {
  return category === "OPENAI_429_RATE_LIMIT"
    || category === "OPENAI_5XX_UPSTREAM"
    || category === "OPENAI_TIMEOUT"
    || category === "OPENAI_CONNECTION_ERROR";
}

export class OpenAiRequestError extends Error {
  constructor(readonly diagnostic: OpenAiSafeDiagnostic) {
    super("OpenAI request failed.");
    this.name = "OpenAiRequestError";
  }
}

function emitDiagnostic(diagnostic: OpenAiSafeDiagnostic, callback?: (diagnostic: OpenAiSafeDiagnostic) => void) {
  callback?.(diagnostic);
  console.warn("OpenAI provider diagnostic", diagnostic);
}

export async function requestOpenAiResponse(options: OpenAiRequestOptions): Promise<Response> {
  assertCanonicalResponseRequest(options.body);
  if (options.model !== options.body.model) throw new Error("OpenAI diagnostic model does not match the canonical request.");
  const fetchImpl = options.fetchImpl ?? fetch;
  const retryBackoffMs = options.retryBackoffMs ?? 150;
  let finalError: OpenAiRequestError | null = null;
  for (let attempt = 1; attempt <= 2; attempt += 1) {
    const startedAt = performance.now();
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), options.timeoutMs);
    try {
      const response = await fetchImpl(OPENAI_RESPONSES_ENDPOINT, {
        method: "POST",
        headers: { Authorization: `Bearer ${options.apiKey}`, "Content-Type": "application/json" },
        signal: controller.signal,
        body: JSON.stringify(options.body),
      });
      if (response.ok) return response;
      const metadata = await readSafeErrorMetadata(response);
      const diagnostic: OpenAiSafeDiagnostic = {
        category: categoryForHttp(response.status, metadata),
        httpStatus: response.status,
        errorClass: "OpenAiHttpError",
        errorType: metadata.type,
        errorCode: metadata.code,
        errorParam: metadata.param,
        requestId: safeRequestId(response),
        model: options.model,
        attempt,
        latencyMs: Math.round(performance.now() - startedAt),
      };
      emitDiagnostic(diagnostic, options.onDiagnostic);
      finalError = new OpenAiRequestError(diagnostic);
      if (!isRetryableOpenAiDiagnostic(diagnostic.category) || attempt === 2) throw finalError;
    } catch (error) {
      if (error instanceof OpenAiRequestError) {
        if (!isRetryableOpenAiDiagnostic(error.diagnostic.category) || attempt === 2) throw error;
        finalError = error;
      } else {
        const transport = transportCategory(error);
        const diagnostic: OpenAiSafeDiagnostic = {
          category: transport.category,
          httpStatus: null,
          errorClass: transport.errorClass,
          errorType: null,
          errorCode: null,
          errorParam: null,
          requestId: null,
          model: options.model,
          attempt,
          latencyMs: Math.round(performance.now() - startedAt),
        };
        emitDiagnostic(diagnostic, options.onDiagnostic);
        finalError = new OpenAiRequestError(diagnostic);
        if (!isRetryableOpenAiDiagnostic(diagnostic.category) || attempt === 2) throw finalError;
      }
    } finally {
      clearTimeout(timeout);
    }
    await new Promise((resolve) => setTimeout(resolve, retryBackoffMs));
  }
  throw finalError ?? new OpenAiRequestError({
    category: "OPENAI_UNKNOWN_REJECTION", httpStatus: null, errorClass: "UnknownError",
    errorType: null, errorCode: null, errorParam: null, requestId: null,
    model: options.model, attempt: 1, latencyMs: 0,
  });
}
