import { afterEach, describe, expect, it } from "vitest";

import { constantTimeKeyEquals } from "@/lib/api-v1/auth";
import { GET as getHealth } from "@/app/api/v1/health/route";

const API_KEY = "test-cmr-api-key-0123456789abcdef";
const originalKey = process.env.CMR_API_KEY;

afterEach(() => {
  if (originalKey === undefined) delete process.env.CMR_API_KEY;
  else process.env.CMR_API_KEY = originalKey;
});

function request(headers: Record<string, string> = {}): Request {
  return new Request("http://localhost/api/v1/health", { headers });
}

describe("API V1 authentication", () => {
  it("uses a constant-length digest comparison", () => {
    expect(constantTimeKeyEquals(API_KEY, API_KEY)).toBe(true);
    expect(constantTimeKeyEquals("short", API_KEY)).toBe(false);
  });

  it("returns 401 when the key is missing or wrong", async () => {
    process.env.CMR_API_KEY = API_KEY;
    const missing = await getHealth(request());
    const wrong = await getHealth(request({ authorization: "Bearer definitely-wrong" }));
    expect(missing.status).toBe(401);
    expect(wrong.status).toBe(401);
    expect(missing.headers.get("cache-control")).toBe("private, no-store");
    expect(JSON.stringify(await wrong.json())).not.toContain(API_KEY);
  });

  it("accepts only the canonical Authorization Bearer header", async () => {
    process.env.CMR_API_KEY = API_KEY;
    const valid = await getHealth(request({ authorization: `Bearer ${API_KEY}` }));
    const nonCanonical = await getHealth(request({ "x-api-key": API_KEY }));
    expect(valid.status).toBe(200);
    await expect(valid.json()).resolves.toEqual({ status: "ok", apiVersion: "v1" });
    expect(nonCanonical.status).toBe(401);
  });

  it("fails closed without server configuration and never leaks an environment value", async () => {
    delete process.env.CMR_API_KEY;
    const response = await getHealth(request({ authorization: `Bearer ${API_KEY}` }));
    const serialized = JSON.stringify(await response.json());
    expect(response.status).toBe(503);
    expect(serialized).not.toMatch(/SUPABASE|OPENAI|service_role|stack|test-cmr/i);
  });
});

