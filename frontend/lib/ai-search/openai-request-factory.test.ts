import { describe, expect, it } from "vitest";

import {
  assertCanonicalResponseRequest,
  buildPlainResponseRequest,
  buildStructuredResponseRequest,
  extractOpenAiOutputText,
  OpenAiRequestValidationError,
} from "@/lib/ai-search/openai-request-factory";

const tinySchema = {
  type: "object",
  additionalProperties: false,
  required: ["route"],
  properties: { route: { type: "string", enum: ["database", "general"] } },
} as const;

function sanitizedShape(value: object) {
  return Object.fromEntries(Object.entries(value).map(([key, item]) => [
    key,
    key === "input" || key === "instructions"
      ? "string:redacted"
      : Array.isArray(item)
        ? "array"
        : item === null
          ? "null"
          : typeof item,
  ]));
}

describe("canonical OpenAI Responses request factory", () => {
  it("builds the candidate general plain request with the stable transport contract", () => {
    const request = buildPlainResponseRequest({
      model: "gpt-5-mini", input: "redacted input", instructions: "redacted instructions", maxOutputTokens: 700,
    });
    expect(request).toEqual({
      model: "gpt-5-mini",
      store: false,
      max_output_tokens: 700,
      instructions: "redacted instructions",
      input: "redacted input",
    });
    expect(sanitizedShape(request)).toMatchInlineSnapshot(`
      {
        "input": "string:redacted",
        "instructions": "string:redacted",
        "max_output_tokens": "number",
        "model": "string",
        "store": "boolean",
      }
    `);
  });

  it("builds stable intent and candidate router structured requests through text.format", () => {
    const stableIntent = buildStructuredResponseRequest({
      model: "gpt-5-mini", input: "redacted input", instructions: "redacted instructions", maxOutputTokens: 500,
      schemaName: "ai_search_resolution", schema: tinySchema,
    });
    const candidateRouter = buildStructuredResponseRequest({
      model: "gpt-5-mini", input: "redacted input", instructions: "redacted instructions", maxOutputTokens: 400,
      schemaName: "ai_research_router", schema: tinySchema,
    });
    for (const request of [stableIntent, candidateRouter]) {
      expect(request.text.format).toEqual({ type: "json_schema", name: expect.any(String), strict: true, schema: tinySchema });
      expect(request).not.toHaveProperty("response_format");
      expect(request).not.toHaveProperty("service_tier");
      expect(request).not.toHaveProperty("temperature");
      expect(request).not.toHaveProperty("top_p");
      expect(() => assertCanonicalResponseRequest(request)).not.toThrow();
    }
    expect(sanitizedShape(stableIntent)).toEqual(sanitizedShape(candidateRouter));
  });

  it("rejects invalid schemas and extra request parameters before fetch", () => {
    expect(() => buildStructuredResponseRequest({
      model: "gpt-5-mini", input: "input", instructions: "instructions", maxOutputTokens: 100,
      schemaName: "invalid_schema",
      schema: { type: "object", additionalProperties: true, required: ["route"], properties: { route: { type: "string" } } },
    })).toThrow(OpenAiRequestValidationError);
    const request = buildPlainResponseRequest({
      model: "gpt-5-mini", input: "input", instructions: "instructions", maxOutputTokens: 100,
    });
    expect(() => assertCanonicalResponseRequest({ ...request, response_format: { type: "json_object" } } as never)).toThrow(OpenAiRequestValidationError);
  });

  it("enforces approved model and bounded input/output", () => {
    expect(() => buildPlainResponseRequest({ model: "other-model", input: "input", instructions: "instructions", maxOutputTokens: 100 })).toThrow();
    expect(() => buildPlainResponseRequest({ model: "gpt-5-mini", input: "input", instructions: "instructions", maxOutputTokens: 2_001 })).toThrow();
    expect(() => buildPlainResponseRequest({ model: "gpt-5-mini", input: "x".repeat(4_001), instructions: "instructions", maxOutputTokens: 100 })).toThrow();
  });

  it("extracts text from both SDK convenience and raw Responses API shapes", () => {
    expect(extractOpenAiOutputText({ output_text: "sdk text" })).toBe("sdk text");
    expect(extractOpenAiOutputText({
      output: [{ content: [{ type: "output_text", text: "raw REST text" }] }],
    })).toBe("raw REST text");
    expect(extractOpenAiOutputText({ output: [] })).toBeNull();
  });
});
