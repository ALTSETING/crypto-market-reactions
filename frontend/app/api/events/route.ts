import { NextResponse } from "next/server";

import { EventsDataError, getEvents } from "@/lib/data/events";
import { EnvironmentConfigurationError } from "@/lib/env";
import { eventsRateLimiter, getClientIp, type RateLimitResult } from "@/lib/rate-limit";
import { parseEventsQuery, QueryValidationError } from "@/lib/validation/events-query";
import type { ApiErrorBody } from "@/types/events";

export const dynamic = "force-dynamic";

function rateHeaders(result: RateLimitResult): Record<string, string> {
  return {
    "RateLimit-Limit": String(result.limit),
    "RateLimit-Remaining": String(result.remaining),
    "RateLimit-Reset": String(Math.ceil(result.resetAt / 1000)),
  };
}

function errorResponse(
  status: number,
  error: string,
  code: string,
  headers?: Record<string, string>,
) {
  return NextResponse.json<ApiErrorBody>({ error, code }, { status, headers });
}

export async function GET(request: Request) {
  const rate = await eventsRateLimiter.consume(getClientIp(request.headers));
  const headers = rateHeaders(rate);
  if (!rate.allowed) {
    return errorResponse(429, "Too many requests. Please try again shortly.", "RATE_LIMITED", {
      ...headers,
      "Retry-After": String(Math.max(1, Math.ceil((rate.resetAt - Date.now()) / 1000))),
    });
  }

  try {
    const params = parseEventsQuery(new URL(request.url).searchParams);
    const result = await getEvents(params);
    return NextResponse.json(result, {
      headers: { ...headers, "Cache-Control": "private, no-store" },
    });
  } catch (error) {
    if (error instanceof QueryValidationError) {
      return errorResponse(400, error.message, error.code, headers);
    }
    if (error instanceof EnvironmentConfigurationError) {
      console.error("Frontend server environment is incomplete");
      return errorResponse(503, "The events service is not configured.", "SERVICE_UNAVAILABLE", headers);
    }
    if (error instanceof EventsDataError) {
      return errorResponse(502, error.message, error.code, headers);
    }
    console.error("Unexpected events API error", {
      name: error instanceof Error ? error.name : "UnknownError",
    });
    return errorResponse(500, "Unexpected server error.", "INTERNAL_ERROR", headers);
  }
}
