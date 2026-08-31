import { afterEach, describe, expect, it, vi } from "vitest";

import * as route from "@/app/api/internal/openai-schema-bisect/route";

function request(body: unknown, ip: string, headers: Record<string, string> = {}) {
  return new Request("http://localhost/api/internal/openai-schema-bisect", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-forwarded-for": ip,
      "x-schema-bisect-run": "production-bisect-v1",
      ...headers,
    },
    body: typeof body === "string" ? body : JSON.stringify(body),
  });
}

describe("temporary production schema bisect endpoint", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    delete process.env.OPENAI_API_KEY;
  });

  it("is POST-only and absent from navigation code", () => {
    expect(route).not.toHaveProperty("GET");
  });

  it("returns only the bounded diagnostic result", async () => {
    process.env.OPENAI_API_KEY = "server-secret";
    vi.spyOn(console, "info").mockImplementation(() => undefined);
    const fetchImpl = vi.fn().mockResolvedValue(Response.json({ output_text: "OK" }));
    vi.stubGlobal("fetch", fetchImpl);
    const response = await route.POST(request({ variant: "A" }, "198.51.100.31"));
    const body = await response.json();
    expect(response.status).toBe(200);
    expect(body).toMatchObject({ variant: "A", model: "gpt-5-mini", result: "PASS", category: "NONE" });
    expect(Object.keys(body).sort()).toEqual(["category", "latencyMs", "model", "result", "variant"]);
    expect(JSON.stringify(body)).not.toMatch(/server-secret|prompt|schema|request|type|param/i);
  });

  it("rejects arbitrary prompt, schema, model, and unknown variants before fetch", async () => {
    process.env.OPENAI_API_KEY = "server-secret";
    const fetchImpl = vi.fn();
    vi.stubGlobal("fetch", fetchImpl);
    for (const [index, body] of [
      { variant: "A", prompt: "custom" },
      { variant: "A", schema: {} },
      { variant: "A", model: "custom" },
      { variant: "UNKNOWN" },
    ].entries()) {
      const response = await route.POST(request(body, `198.51.100.${40 + index}`));
      expect(response.status).toBe(400);
      await expect(response.json()).resolves.toEqual({ status: "error", code: "INVALID_VARIANT" });
    }
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("requires marker, JSON, bounded body, key, and enforces the local limit", async () => {
    expect((await route.POST(request({ variant: "A" }, "198.51.100.50", { "x-schema-bisect-run": "wrong" }))).status).toBe(404);
    expect((await route.POST(request("{", "198.51.100.51"))).status).toBe(400);
    expect((await route.POST(request({ variant: "A" }, "198.51.100.52", { "content-length": "129" }))).status).toBe(413);
    expect((await route.POST(request({ variant: "A" }, "198.51.100.53"))).status).toBe(503);

    process.env.OPENAI_API_KEY = "server-secret";
    vi.spyOn(console, "info").mockImplementation(() => undefined);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ output_text: "OK" })));
    let response: Response | undefined;
    for (let index = 0; index < 10; index += 1) {
      response = await route.POST(request({ variant: "A" }, "198.51.100.54"));
    }
    expect(response?.status).toBe(429);
  });
});
