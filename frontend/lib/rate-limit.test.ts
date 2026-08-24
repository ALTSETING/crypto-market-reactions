import { afterEach, describe, expect, it, vi } from "vitest";

import { getClientIp, InMemoryRateLimiter, SupabaseRateLimiter } from "./rate-limit";

const TEST_SERVER_CREDENTIAL = "test_server_credential_with_enough_material";

afterEach(() => vi.restoreAllMocks());

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

describe("SupabaseRateLimiter", () => {
  it("uses the shared RPC result", async () => {
    const request = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ allowed: true, limit: 60, remaining: 41, reset_at_epoch_ms: 123000 })),
    );
    const limiter = new SupabaseRateLimiter(
      "https://example.supabase.co",
      TEST_SERVER_CREDENTIAL,
      new InMemoryRateLimiter(1, 100),
    );
    await expect(limiter.consume("203.0.113.10")).resolves.toEqual({
      allowed: true,
      limit: 60,
      remaining: 41,
      resetAt: 123000,
    });
    const body = JSON.parse(String(request.mock.calls[0]?.[1]?.body)) as { p_key_hash: string };
    expect(body.p_key_hash).toMatch(/^[0-9a-f]{64}$/);
    expect(JSON.stringify(request.mock.calls)).not.toContain("203.0.113.10");
  });

  it("keeps the API usable through the local fallback", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("missing", { status: 404 }));
    vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const limiter = new SupabaseRateLimiter(
      "https://example.supabase.co",
      TEST_SERVER_CREDENTIAL,
      new InMemoryRateLimiter(1, 100),
    );
    await expect(limiter.consume("ip", 0)).resolves.toMatchObject({ allowed: true });
    await expect(limiter.consume("ip", 1)).resolves.toMatchObject({ allowed: false });
  });
});
