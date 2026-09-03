import "server-only";

import { apiConsumerFingerprint, authenticateApiRequest } from "@/lib/api-v1/auth";
import { ApiV1Error } from "@/lib/api-v1/errors";
import {
  apiV1RateHeaders,
  consumeApiV1RateLimit,
  type ApiV1RateLimitResult,
} from "@/lib/api-v1/rate-limit";

export const CACHE_HEADERS = {
  short: "private, max-age=30, stale-while-revalidate=60",
  analytics: "private, max-age=60, stale-while-revalidate=300",
  metadata: "private, max-age=300, stale-while-revalidate=600",
  none: "private, no-store",
} as const;

export interface ApiV1Context {
  apiKey: string;
}

function json(body: unknown, status: number, headers: Record<string, string> = {}): Response {
  return Response.json(body, {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "X-Content-Type-Options": "nosniff",
      ...headers,
    },
  });
}

export function apiSuccess(data: unknown, cacheControl: string, extra: Record<string, unknown> = {}): Response {
  return json({ data, ...extra }, 200, { "Cache-Control": cacheControl });
}

export function apiDocument(body: unknown, cacheControl: string): Response {
  return json(body, 200, { "Cache-Control": cacheControl });
}

export function apiError(error: ApiV1Error, headers: Record<string, string> = {}): Response {
  const responseHeaders: Record<string, string> = { "Cache-Control": CACHE_HEADERS.none, ...headers };
  if (error.status === 429 && !responseHeaders["Retry-After"]) responseHeaders["Retry-After"] = "60";
  return json({ error: { code: error.code, message: error.message } }, error.status, responseHeaders);
}

function limited(result: ApiV1RateLimitResult): ApiV1Error | null {
  if (result.minute.allowed && result.daily.allowed) return null;
  return new ApiV1Error(429, "RATE_LIMITED", "The API rate limit has been exceeded.");
}

export async function withApiV1(
  request: Request,
  handler: (context: ApiV1Context) => Promise<Response> | Response,
): Promise<Response> {
  let rateHeaders: Record<string, string> = {};
  try {
    const apiKey = authenticateApiRequest(request);
    const rate = await consumeApiV1RateLimit(apiConsumerFingerprint(apiKey));
    rateHeaders = apiV1RateHeaders(rate);
    const limitError = limited(rate);
    if (limitError) {
      const resetAt = Math.max(rate.minute.allowed ? 0 : rate.minute.resetAt, rate.daily.allowed ? 0 : rate.daily.resetAt);
      return apiError(limitError, {
        ...rateHeaders,
        "Retry-After": String(Math.max(1, Math.ceil((resetAt - Date.now()) / 1_000))),
      });
    }
    const response = await handler({ apiKey });
    for (const [key, value] of Object.entries(rateHeaders)) response.headers.set(key, value);
    return response;
  } catch (caught) {
    if (caught instanceof ApiV1Error) return apiError(caught, rateHeaders);
    console.error("Unexpected API V1 error", { name: caught instanceof Error ? caught.name : "UnknownError" });
    return apiError(new ApiV1Error(503, "SERVICE_UNAVAILABLE", "The API is temporarily unavailable."), rateHeaders);
  }
}
