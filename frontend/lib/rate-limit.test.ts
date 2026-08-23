import { describe, expect, it } from "vitest";

import { getClientIp, InMemoryRateLimiter } from "./rate-limit";

describe("InMemoryRateLimiter", () => {
  it("returns 429-ready state after the configured threshold", () => {
    const limiter = new InMemoryRateLimiter(2, 60_000);
    expect(limiter.consume("ip", 1).allowed).toBe(true);
    expect(limiter.consume("ip", 2).allowed).toBe(true);
    expect(limiter.consume("ip", 3)).toMatchObject({ allowed: false, remaining: 0 });
  });

  it("resets after its window", () => {
    const limiter = new InMemoryRateLimiter(1, 100);
    limiter.consume("ip", 0);
    expect(limiter.consume("ip", 50).allowed).toBe(false);
    expect(limiter.consume("ip", 101).allowed).toBe(true);
  });
});

it("uses the first forwarded IP", () => {
  expect(getClientIp(new Headers({ "x-forwarded-for": "203.0.113.10, 10.0.0.1" }))).toBe(
    "203.0.113.10",
  );
});
