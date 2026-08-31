import { afterEach, describe, expect, it, vi } from "vitest";

import {
  buildSchemaBisectRequest,
  runSchemaBisectVariant,
  SCHEMA_BISECT_VARIANTS,
} from "@/lib/ai-search/schema-bisect";

describe("temporary OpenAI schema bisect runner", () => {
  afterEach(() => vi.restoreAllMocks());

  it("uses only hardcoded models, prompts, and schemas for allowlisted IDs", () => {
    const shapes = SCHEMA_BISECT_VARIANTS.map((variant) => {
      const request = buildSchemaBisectRequest(variant);
      return {
        variant,
        model: request.model,
        keys: Object.keys(request.body).sort(),
        formatKeys: "text" in request.body
          ? Object.keys((request.body.text as { format: object }).format).sort()
          : [],
      };
    });
    expect(shapes).toMatchInlineSnapshot(`
      [
        {
          "formatKeys": [],
          "keys": [
            "input",
            "max_output_tokens",
            "model",
            "store",
          ],
          "model": "gpt-5-mini",
          "variant": "P",
        },
        {
          "formatKeys": [
            "name",
            "schema",
            "strict",
            "type",
          ],
          "keys": [
            "input",
            "max_output_tokens",
            "model",
            "store",
            "text",
          ],
          "model": "gpt-5-mini",
          "variant": "A",
        },
        {
          "formatKeys": [
            "name",
            "schema",
            "strict",
            "type",
          ],
          "keys": [
            "input",
            "max_output_tokens",
            "model",
            "store",
            "text",
          ],
          "model": "gpt-5-mini",
          "variant": "B",
        },
        {
          "formatKeys": [
            "name",
            "schema",
            "strict",
            "type",
          ],
          "keys": [
            "input",
            "max_output_tokens",
            "model",
            "store",
            "text",
          ],
          "model": "gpt-5-mini",
          "variant": "C",
        },
        {
          "formatKeys": [
            "name",
            "schema",
            "strict",
            "type",
          ],
          "keys": [
            "input",
            "max_output_tokens",
            "model",
            "store",
            "text",
          ],
          "model": "gpt-5-mini",
          "variant": "D",
        },
        {
          "formatKeys": [
            "name",
            "schema",
            "strict",
            "type",
          ],
          "keys": [
            "input",
            "max_output_tokens",
            "model",
            "store",
            "text",
          ],
          "model": "gpt-5-mini",
          "variant": "E",
        },
        {
          "formatKeys": [
            "name",
            "schema",
            "strict",
            "type",
          ],
          "keys": [
            "input",
            "max_output_tokens",
            "model",
            "store",
            "text",
          ],
          "model": "gpt-5-mini",
          "variant": "F",
        },
        {
          "formatKeys": [
            "name",
            "schema",
            "strict",
            "type",
          ],
          "keys": [
            "input",
            "max_output_tokens",
            "model",
            "store",
            "text",
          ],
          "model": "gpt-5.6-terra",
          "variant": "T",
        },
        {
          "formatKeys": [
            "name",
            "schema",
            "strict",
            "type",
          ],
          "keys": [
            "input",
            "max_output_tokens",
            "model",
            "store",
            "text",
          ],
          "model": "gpt-5-mini",
          "variant": "D0",
        },
        {
          "formatKeys": [
            "name",
            "schema",
            "strict",
            "type",
          ],
          "keys": [
            "input",
            "max_output_tokens",
            "model",
            "store",
            "text",
          ],
          "model": "gpt-5-mini",
          "variant": "F1",
        },
        {
          "formatKeys": [
            "name",
            "schema",
            "strict",
            "type",
          ],
          "keys": [
            "input",
            "max_output_tokens",
            "model",
            "store",
            "text",
          ],
          "model": "gpt-5-mini",
          "variant": "F2",
        },
      ]
    `);
    expect(JSON.stringify(shapes)).not.toMatch(/Bearer|OPENAI_API_KEY|Classify this|Reply with/);
  });

  it("runs plain Mini without text.format and allows one transient retry", async () => {
    const fetchImpl = vi.fn()
      .mockResolvedValueOnce(new Response("temporary", { status: 503 }))
      .mockResolvedValueOnce(Response.json({ output_text: "OK" }));
    await expect(runSchemaBisectVariant("P", { apiKey: "server-secret", fetchImpl, timeoutMs: 50 })).resolves.toMatchObject({
      variant: "P", model: "gpt-5-mini", result: "PASS", category: "NONE",
    });
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    const body = JSON.parse(fetchImpl.mock.calls[0][1]?.body as string);
    expect(body).not.toHaveProperty("text");
    expect(JSON.stringify(fetchImpl.mock.calls).replaceAll("server-secret", "[redacted]")).not.toContain("server-secret");
  });

  it("does not retry HTTP 400 and never exposes its raw body", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(Response.json({
      error: { message: "raw secret prompt schema request-id", type: "invalid_request_error" },
    }, { status: 400 }));
    const result = await runSchemaBisectVariant("D", { apiKey: "server-secret", fetchImpl, timeoutMs: 50 });
    expect(result).toMatchObject({
      variant: "D", model: "gpt-5-mini", result: "HTTP_400", category: "BAD_REQUEST",
    });
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    expect(Object.keys(result).sort()).toEqual(["category", "latencyMs", "model", "result", "variant"]);
    expect(JSON.stringify(result)).not.toMatch(/raw secret|prompt|schema|request-id|invalid_request_error/);
  });

  it("uses the identical minimal schema for Mini A and Terra T", () => {
    const mini = buildSchemaBisectRequest("A");
    const terra = buildSchemaBisectRequest("T");
    expect(mini.model).toBe("gpt-5-mini");
    expect(terra.model).toBe("gpt-5.6-terra");
    expect((mini.body.text as { format: { schema: unknown } }).format.schema)
      .toEqual((terra.body.text as { format: { schema: unknown } }).format.schema);
  });
});
