import "server-only";

import { InMemoryRateLimiter, type RateLimitResult } from "@/lib/rate-limit";

const MINUTE_MS = 60_000;
const DAY_MS = 86_400_000;

function configuredLimit(name: string, fallback: number, maximum: number): number {
  const value = Number(process.env[name] ?? fallback);
  return Number.isInteger(value) && value >= 1 && value <= maximum ? value : fallback;
}

const minuteLimit = configuredLimit("CMR_API_RATE_LIMIT_PER_MINUTE", 60, 1_000);
const dailyLimit = configuredLimit("CMR_API_DAILY_LIMIT", 10_000, 1_000_000);
const minuteLimiter = new InMemoryRateLimiter(minuteLimit, MINUTE_MS);
const dailyLimiter = new InMemoryRateLimiter(dailyLimit, DAY_MS);

export interface ApiV1RateLimitResult {
  minute: RateLimitResult;
  daily: RateLimitResult;
}

export async function consumeApiV1RateLimit(consumer: string): Promise<ApiV1RateLimitResult> {
  return {
    minute: await minuteLimiter.consume(`cmr-api-v1:minute:${consumer}`),
    daily: await dailyLimiter.consume(`cmr-api-v1:daily:${consumer}`),
  };
}

export function apiV1RateHeaders(result: ApiV1RateLimitResult): Record<string, string> {
  return {
    "RateLimit-Limit": String(result.minute.limit),
    "RateLimit-Remaining": String(result.minute.remaining),
    "RateLimit-Reset": String(Math.ceil(result.minute.resetAt / 1_000)),
    "X-Daily-Limit": String(result.daily.limit),
    "X-Daily-Remaining": String(result.daily.remaining),
    "X-Daily-Reset": String(Math.ceil(result.daily.resetAt / 1_000)),
  };
}

