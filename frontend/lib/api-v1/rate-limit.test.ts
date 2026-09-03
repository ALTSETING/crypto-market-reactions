import { describe, expect, it } from "vitest";

import { consumeApiV1RateLimit } from "@/lib/api-v1/rate-limit";

describe("API V1 rate limiting", () => {
  it("has an independent 60 request/minute owner-key bucket", async () => {
    const consumer = `rate-test-${crypto.randomUUID()}`;
    let result;
    for (let index = 0; index < 61; index += 1) result = await consumeApiV1RateLimit(consumer);
    expect(result?.minute.limit).toBe(60);
    expect(result?.minute.allowed).toBe(false);
    expect(result?.daily.limit).toBe(10_000);
    expect(result?.daily.allowed).toBe(true);
  });
});

