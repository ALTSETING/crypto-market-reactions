import { describe, expect, it } from "vitest";

import { buildStructuredResponseRequest } from "@/lib/ai-search/openai-request-factory";
import { AI_RESOLUTION_JSON_SCHEMA } from "@/lib/ai-search/schema";
import { StrictSchemaValidationError, validateStrictStructuredSchema, validateStructuredTextFormat } from "@/lib/ai-search/strict-schema";

const variantA = {
  type: "object",
  properties: { intent: { type: "string", enum: ["database", "clarification"] } },
  required: ["intent"],
  additionalProperties: false,
} as const;
const nullableString = { anyOf: [{ type: "string" }, { type: "null" }] } as const;
const variantB = {
  type: "object",
  properties: { ...variantA.properties, asset: nullableString, horizon: nullableString },
  required: ["intent", "asset", "horizon"],
  additionalProperties: false,
} as const;
const variantC = {
  type: "object",
  properties: {
    ...variantB.properties,
    topic: nullableString,
    direction: { type: "string", enum: ["inflow", "outflow", "unknown"] },
    date: nullableString,
  },
  required: ["intent", "asset", "horizon", "topic", "direction", "date"],
  additionalProperties: false,
} as const;

function objectSchema(properties: Record<string, unknown>, required = Object.keys(properties)) {
  return { type: "object", properties, required, additionalProperties: false };
}

describe("strict OpenAI Structured Outputs schema validator", () => {
  it.each([
    ["missing required", objectSchema({ value: { type: "string" } }, [])],
    ["extra required", objectSchema({}, ["ghost"])],
    ["additional properties", { ...objectSchema({ value: { type: "string" } }), additionalProperties: true }],
    ["non-object root", { type: "string" }],
    ["root anyOf", { anyOf: [variantA, variantA] }],
    ["array without items", objectSchema({ values: { type: "array" } })],
    ["invalid nullable enum", objectSchema({ value: { type: ["string", "null"], enum: ["ok", 3] } })],
  ])("rejects %s", (_label, schema) => {
    expect(() => validateStrictStructuredSchema(schema)).toThrow(StrictSchemaValidationError);
  });

  it.each(["allOf", "not", "if", "then", "else", "dependentRequired", "dependentSchemas", "minLength", "maxLength"])(
    "rejects unsupported keyword %s",
    (keyword) => {
      expect(() => validateStrictStructuredSchema(objectSchema({
        value: { type: "string", [keyword]: keyword === "minLength" || keyword === "maxLength" ? 1 : {} },
      }))).toThrow(StrictSchemaValidationError);
    },
  );

  it("rejects invalid format names, strict placement, and text.format shape", () => {
    expect(() => validateStructuredTextFormat({ type: "json_schema", name: "bad name", strict: true, schema: variantA })).toThrow();
    expect(() => validateStructuredTextFormat({ type: "json_schema", name: "x".repeat(65), strict: true, schema: variantA })).toThrow();
    expect(() => validateStructuredTextFormat({ type: "json_schema", name: "valid", strict: false, schema: variantA })).toThrow();
    expect(() => validateStructuredTextFormat({ type: "json_schema", name: "valid", strict: true })).toThrow();
    expect(() => validateStructuredTextFormat({ type: "json_schema", name: "valid", strict: true, schema: variantA, prompt: "forbidden" })).toThrow();
  });

  it("returns the safe internal schema code", () => {
    try {
      validateStrictStructuredSchema({ type: "string" });
      throw new Error("Expected schema validation to fail.");
    } catch (error) {
      expect(error).toMatchObject({ name: "StrictSchemaValidationError", code: "OPENAI_SCHEMA_INVALID" });
      expect(String(error)).not.toMatch(/Bearer|OPENAI_API_KEY|prompt/);
    }
  });

  it("validates sanitized schema bisect variants A-D and canonical request snapshots", () => {
    const variants = [variantA, variantB, variantC, AI_RESOLUTION_JSON_SCHEMA];
    const snapshots = variants.map((schema, index) => {
      validateStrictStructuredSchema(schema);
      const request = buildStructuredResponseRequest({
        model: "gpt-5-mini",
        input: "redacted",
        instructions: "redacted",
        maxOutputTokens: 500,
        schemaName: `schema_variant_${String.fromCharCode(65 + index)}`,
        schema,
      });
      return {
        variant: String.fromCharCode(65 + index),
        requestKeys: Object.keys(request).sort(),
        formatKeys: Object.keys(request.text.format).sort(),
        schemaBytes: JSON.stringify(schema).length,
        propertyCount: Object.keys(schema.properties).length,
      };
    });
    expect(snapshots).toMatchInlineSnapshot(`
      [
        {
          "formatKeys": [
            "name",
            "schema",
            "strict",
            "type",
          ],
          "propertyCount": 1,
          "requestKeys": [
            "input",
            "instructions",
            "max_output_tokens",
            "model",
            "reasoning",
            "store",
            "text",
          ],
          "schemaBytes": 146,
          "variant": "A",
        },
        {
          "formatKeys": [
            "name",
            "schema",
            "strict",
            "type",
          ],
          "propertyCount": 3,
          "requestKeys": [
            "input",
            "instructions",
            "max_output_tokens",
            "model",
            "reasoning",
            "store",
            "text",
          ],
          "schemaBytes": 274,
          "variant": "B",
        },
        {
          "formatKeys": [
            "name",
            "schema",
            "strict",
            "type",
          ],
          "propertyCount": 6,
          "requestKeys": [
            "input",
            "instructions",
            "max_output_tokens",
            "model",
            "reasoning",
            "store",
            "text",
          ],
          "schemaBytes": 476,
          "variant": "C",
        },
        {
          "formatKeys": [
            "name",
            "schema",
            "strict",
            "type",
          ],
          "propertyCount": 3,
          "requestKeys": [
            "input",
            "instructions",
            "max_output_tokens",
            "model",
            "reasoning",
            "store",
            "text",
          ],
          "schemaBytes": 3836,
          "variant": "D",
        },
      ]
    `);
    expect(JSON.stringify(snapshots)).not.toMatch(/Bearer|OPENAI_API_KEY|Convert the English|redacted/);
  });
});
