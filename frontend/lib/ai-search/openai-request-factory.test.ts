import { describe, expect, it } from "vitest";

import { assertCanonicalResponseRequest, buildStructuredResponseRequest, extractOpenAiOutputText } from "@/lib/ai-search/openai-request-factory";
import { StrictSchemaValidationError } from "@/lib/ai-search/strict-schema";

const tinySchema = {
  type: "object",
  additionalProperties: false,
  required: ["intent"],
  properties: { intent: { type: "string", enum: ["database", "clarification"] } },
} as const;

function request() {
  return buildStructuredResponseRequest({
    model: "gpt-5-mini",
    input: "redacted input",
    instructions: "redacted instructions",
    maxOutputTokens: 500,
    schemaName: "ai_search_resolution",
    schema: tinySchema,
  });
}

describe("canonical OpenAI Responses request factory", () => {
  it("uses strict JSON Schema under text.format and no legacy response_format", () => {
    const value = request();
    expect(value.text.format).toEqual({
      type: "json_schema",
      name: "ai_search_resolution",
      strict: true,
      schema: tinySchema,
    });
    expect(value).not.toHaveProperty("response_format");
    expect(value).not.toHaveProperty("tools");
    expect(() => assertCanonicalResponseRequest(value)).not.toThrow();
  });

  it("rejects malformed text.format and tampered schemas before transport", () => {
    const value = request();
    expect(() => assertCanonicalResponseRequest({
      ...value,
      text: { format: { ...value.text.format, strict: false } },
    } as never)).toThrow(StrictSchemaValidationError);
    expect(() => assertCanonicalResponseRequest({
      ...value,
      text: { format: { ...value.text.format, schema: { ...tinySchema, additionalProperties: true } } },
    } as never)).toThrow(StrictSchemaValidationError);
  });

  it("extracts top-level and nested output text with a controlled null fallback", () => {
    expect(extractOpenAiOutputText({ output_text: "top-level" })).toBe("top-level");
    expect(extractOpenAiOutputText({ output: [{ content: [{ type: "output_text", text: "nested" }] }] })).toBe("nested");
    expect(extractOpenAiOutputText({ output_text: "", output: [{ content: [{ type: "output_text", text: "nested" }] }] })).toBe("nested");
    expect(extractOpenAiOutputText({ output: [] })).toBeNull();
  });
});
