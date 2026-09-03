import "server-only";

import { createHash, timingSafeEqual } from "node:crypto";

import { ApiV1Error } from "@/lib/api-v1/errors";

const MAX_AUTH_HEADER_LENGTH = 1_024;

function digest(value: string): Buffer {
  return createHash("sha256").update(value, "utf8").digest();
}

export function constantTimeKeyEquals(candidate: string, expected: string): boolean {
  return timingSafeEqual(digest(candidate), digest(expected));
}

export function getConfiguredApiKey(): string {
  const apiKey = process.env.CMR_API_KEY?.trim();
  if (!apiKey || apiKey.length < 32) {
    throw new ApiV1Error(503, "SERVICE_UNAVAILABLE", "The API is temporarily unavailable.");
  }
  return apiKey;
}

export function authenticateApiRequest(request: Request): string {
  const authorization = request.headers.get("authorization");
  if (!authorization || authorization.length > MAX_AUTH_HEADER_LENGTH) {
    throw new ApiV1Error(401, "UNAUTHORIZED", "A valid Bearer API key is required.");
  }

  const match = /^Bearer ([^\s]+)$/u.exec(authorization);
  const expected = getConfiguredApiKey();
  if (!match || !constantTimeKeyEquals(match[1], expected)) {
    throw new ApiV1Error(401, "UNAUTHORIZED", "A valid Bearer API key is required.");
  }
  return expected;
}

export function apiConsumerFingerprint(apiKey: string): string {
  return createHash("sha256").update(`cmr-api-v1:${apiKey}`, "utf8").digest("hex");
}

