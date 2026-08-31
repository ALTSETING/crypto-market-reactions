import { NextResponse } from "next/server";

import { getAiSearchDataAdapter } from "@/lib/ai-search/adapter";
import { getAiIntentProvider } from "@/lib/ai-search/provider";
import { executeAiSearch } from "@/lib/ai-search/service";
import { createDistributedRateLimiter, getClientIp, InMemoryRateLimiter, type RateLimiter, type RateLimitResult } from "@/lib/rate-limit";
import type { AiSearchErrorBody } from "@/types/ai-search";

export const dynamic = "force-dynamic";

const PER_IP_LIMIT = 10;
const DAILY_LIMIT = 500;
const MINUTE_MS = 60_000;
const DAY_MS = 86_400_000;
const localPerIpLimiter = new InMemoryRateLimiter(PER_IP_LIMIT, MINUTE_MS);
const localDailyLimiter = new InMemoryRateLimiter(DAILY_LIMIT, DAY_MS);

function configuredLimit(name: string, fallback: number, maximum: number): number {
  const value = Number(process.env[name] ?? fallback);
  return Number.isInteger(value) && value >= 1 && value <= maximum ? value : fallback;
}

function getAiLimiters(): { perIp: RateLimiter; daily: RateLimiter } | null {
  const perIpLimit = configuredLimit("AI_SEARCH_PER_IP_LIMIT", PER_IP_LIMIT, 60);
  const dailyLimit = configuredLimit("AI_SEARCH_DAILY_LIMIT", DAILY_LIMIT, 10_000);
  if (process.env.AI_SEARCH_USE_DISTRIBUTED_RATE_LIMITER === "true") {
    const perIp = createDistributedRateLimiter(perIpLimit, MINUTE_MS);
    const daily = createDistributedRateLimiter(dailyLimit, DAY_MS);
    return perIp && daily ? { perIp, daily } : null;
  }
  if (process.env.NODE_ENV === "production") return null;
  return { perIp: localPerIpLimiter, daily: localDailyLimiter };
}

function isSameOrigin(request: Request): boolean {
  const origin = request.headers.get("origin");
  if (!origin) return true;
  try {
    const requestOrigin = new URL(request.url).origin;
    const configured = process.env.SITE_URL ? new URL(process.env.SITE_URL).origin : requestOrigin;
    return origin === configured || (process.env.NODE_ENV !== "production" && origin === requestOrigin);
  } catch {
    return false;
  }
}

function rateHeaders(result: RateLimitResult): Record<string, string> {
  return {
    "RateLimit-Limit": String(result.limit),
    "RateLimit-Remaining": String(result.remaining),
    "RateLimit-Reset": String(Math.ceil(result.resetAt / 1000)),
  };
}

function error(status: number, code: string, message: string, headers: Record<string, string>) {
  return NextResponse.json<AiSearchErrorBody>({ status: "error", code, message }, { status, headers });
}

export async function POST(request: Request) {
  const startedAt = performance.now();
  if (process.env.AI_SEARCH_ENABLED !== "true") {
    return error(503, "AI_SEARCH_DISABLED", "AI Search is currently unavailable.", {});
  }
  if (!isSameOrigin(request)) return error(403, "ORIGIN_REJECTED", "Cross-origin requests are not allowed.", {});
  const limiters = getAiLimiters();
  if (!limiters) return error(503, "RATE_LIMITER_UNAVAILABLE", "AI Search is temporarily unavailable.", {});
  const rate = await limiters.perIp.consume(`ai-search:ip:${getClientIp(request.headers)}`);
  const daily = await limiters.daily.consume("ai-search:global:daily");
  const headers = {
    ...rateHeaders(rate),
    "AI-Daily-Limit": String(daily.limit),
    "AI-Daily-Remaining": String(daily.remaining),
    "AI-Daily-Reset": String(Math.ceil(daily.resetAt / 1000)),
  };
  if (!rate.allowed || !daily.allowed) {
    const resetAt = Math.max(rate.allowed ? 0 : rate.resetAt, daily.allowed ? 0 : daily.resetAt);
    return error(429, "RATE_LIMITED", "Too many AI Search requests. Please try again shortly.", {
      ...headers,
      "Retry-After": String(Math.max(1, Math.ceil((resetAt - Date.now()) / 1000))),
    });
  }
  if (!request.headers.get("content-type")?.toLowerCase().startsWith("application/json")) {
    return error(415, "JSON_REQUIRED", "Content-Type must be application/json.", headers);
  }
  const contentLength = Number(request.headers.get("content-length") ?? "0");
  if (Number.isFinite(contentLength) && contentLength > 4_096) {
    return error(413, "REQUEST_TOO_LARGE", "Request body is too large.", headers);
  }

  try {
    const rawBody = await request.text();
    if (new TextEncoder().encode(rawBody).byteLength > 4_096) {
      return error(413, "REQUEST_TOO_LARGE", "Request body is too large.", headers);
    }
    const payload = JSON.parse(rawBody) as { question?: unknown };
    const result = await executeAiSearch(payload?.question, getAiIntentProvider(), getAiSearchDataAdapter());
    console.info("AI Search request completed", {
      statusCode: result.statusCode,
      latencyMs: Math.round(performance.now() - startedAt),
    });
    return NextResponse.json(result.body, {
      status: result.statusCode,
      headers: { ...headers, "Cache-Control": "private, no-store" },
    });
  } catch (caught) {
    if (caught instanceof SyntaxError) return error(400, "INVALID_JSON", "Request body must be valid JSON.", headers);
    console.error("Unexpected AI Search API error", { name: caught instanceof Error ? caught.name : "UnknownError" });
    return error(503, "SERVICE_UNAVAILABLE", "AI Search is temporarily unavailable.", headers);
  }
}
