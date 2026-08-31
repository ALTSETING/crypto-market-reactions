import { describe, expect, it } from "vitest";

import { AI_INTENT_JSON_SCHEMA, IntentValidationError, validateIntent } from "@/lib/ai-search/schema";

const validIntent = {
  intent: "search",
  asset: "BTC",
  dateFrom: null,
  dateTo: null,
  category: null,
  topic: "institutional_purchase",
  actorType: "institution",
  action: "buy",
  direction: "inflow",
  magnitude: "standard",
  amount: null,
  entity: "BlackRock",
  assetRole: "primary",
  sourceClass: null,
  sentiment: null,
  reactionSign: null,
  importance: null,
  horizon: null,
  metric: "events",
  sort: "newest",
  groupBy: "none",
  comparison: null,
  limit: 10,
} as const;

describe("confirmed OpenAI structured schema compatibility", () => {
  it("omits the production-incompatible entity pattern from provider schema", () => {
    const entityString = AI_INTENT_JSON_SCHEMA.properties.entity.anyOf[0];
    expect(entityString).toEqual({ type: "string", minLength: 1, maxLength: 80 });
    expect(entityString).not.toHaveProperty("pattern");
  });

  it("keeps the same entity restrictions in runtime validation", () => {
    expect(validateIntent(validIntent)).toMatchObject({ entity: "BlackRock" });
    expect(() => validateIntent({ ...validIntent, entity: "<invalid>" })).toThrow(IntentValidationError);
    expect(() => validateIntent({ ...validIntent, entity: "x".repeat(81) })).toThrow(IntentValidationError);
    expect(() => validateIntent({ ...validIntent, entity: " BlackRock" })).toThrow(IntentValidationError);
  });
});
