import {
  AI_ACTIONS,
  AI_ACTOR_TYPES,
  AI_AMOUNT_CURRENCIES,
  AI_ASSET_ROLES,
  AI_DIRECTIONS,
  AI_IMPORTANCE,
  AI_INTENTS,
  AI_MAGNITUDES,
  AI_METRICS,
  AI_REACTION_SIGNS,
  AI_SENTIMENTS,
  AI_SORTS,
  AI_TOPICS,
  type AiSearchIntent,
} from "@/types/ai-search";
import { ASSETS, EVENT_CATEGORIES, HORIZONS, SOURCE_TYPES } from "@/types/events";

export const AI_SEARCH_MAX_QUESTION_LENGTH = 500;
export const AI_SEARCH_MAX_LIMIT = 50;

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const NORMALIZED_ENTITY = /^[\p{L}\p{N}][\p{L}\p{N} .&'’_-]{0,79}$/u;

export class IntentValidationError extends Error {
  readonly code = "INVALID_INTENT";
  constructor(message: string) {
    super(message);
    this.name = "IntentValidationError";
  }
}

function enumValue<T extends string>(value: unknown, values: readonly T[], field: string): T {
  if (typeof value !== "string" || !values.includes(value as T)) {
    throw new IntentValidationError(`${field} is outside the supported allowlist.`);
  }
  return value as T;
}

function nullableEnum<T extends string>(value: unknown, values: readonly T[], field: string): T | null {
  return value === null ? null : enumValue(value, values, field);
}

function nullableDate(value: unknown, field: string): string | null {
  if (value === null) return null;
  const parsed = typeof value === "string" && ISO_DATE.test(value) ? new Date(`${value}T00:00:00Z`) : null;
  if (!parsed || Number.isNaN(parsed.valueOf()) || parsed.toISOString().slice(0, 10) !== value) {
    throw new IntentValidationError(`${field} must be a valid ISO date.`);
  }
  return value;
}

export function validateIntent(input: unknown): AiSearchIntent {
  if (!input || typeof input !== "object" || Array.isArray(input)) {
    throw new IntentValidationError("Structured intent must be an object.");
  }
  const value = input as Record<string, unknown>;
  const allowedKeys = new Set([
    "intent", "asset", "dateFrom", "dateTo", "category", "topic", "actorType", "action", "direction",
    "magnitude", "amount", "entity", "assetRole", "sourceClass", "sentiment",
    "reactionSign", "importance", "horizon", "metric", "sort", "groupBy", "comparison", "limit",
  ]);
  if (Object.keys(value).some((key) => !allowedKeys.has(key))) {
    throw new IntentValidationError("Structured intent contains unsupported fields.");
  }

  const intent = enumValue(value.intent, AI_INTENTS, "intent");
  const asset = nullableEnum(value.asset, ASSETS, "asset");
  const dateFrom = nullableDate(value.dateFrom, "dateFrom");
  const dateTo = nullableDate(value.dateTo, "dateTo");
  const category = nullableEnum(value.category, EVENT_CATEGORIES, "category");
  const topic = nullableEnum(value.topic, AI_TOPICS, "topic");
  const actorType = enumValue(value.actorType ?? "unknown", AI_ACTOR_TYPES, "actorType");
  const action = nullableEnum(value.action ?? null, AI_ACTIONS, "action");
  const direction = enumValue(value.direction ?? "unknown", AI_DIRECTIONS, "direction");
  const magnitude = enumValue(value.magnitude ?? "unknown", AI_MAGNITUDES, "magnitude");
  const assetRole = enumValue(value.assetRole ?? (asset ? "primary" : "any"), AI_ASSET_ROLES, "assetRole");
  let amount: AiSearchIntent["amount"] = null;
  if (value.amount !== null && value.amount !== undefined) {
    if (!value.amount || typeof value.amount !== "object" || Array.isArray(value.amount)) {
      throw new IntentValidationError("amount must be null or a bounded object.");
    }
    const candidate = value.amount as Record<string, unknown>;
    if (Object.keys(candidate).sort().join(",") !== "currency,value") {
      throw new IntentValidationError("amount contains unsupported fields.");
    }
    const currency = enumValue(candidate.currency, AI_AMOUNT_CURRENCIES, "amount.currency");
    if (typeof candidate.value !== "number" || !Number.isFinite(candidate.value) || candidate.value <= 0 || candidate.value > 1_000_000_000_000_000) {
      throw new IntentValidationError("amount.value is outside the supported range.");
    }
    amount = { currency, value: candidate.value };
  }
  const entity = value.entity === null || value.entity === undefined
    ? null
    : typeof value.entity === "string" && NORMALIZED_ENTITY.test(value.entity) && value.entity === value.entity.normalize("NFKC").trim()
      ? value.entity
      : (() => { throw new IntentValidationError("entity must be a bounded normalized value."); })();
  const sourceClass = nullableEnum(value.sourceClass, SOURCE_TYPES, "sourceClass");
  const sentiment = nullableEnum(value.sentiment, AI_SENTIMENTS, "sentiment");
  const reactionSign = nullableEnum(value.reactionSign, AI_REACTION_SIGNS, "reactionSign");
  const importance = nullableEnum(value.importance, AI_IMPORTANCE, "importance");
  const horizon = nullableEnum(value.horizon, HORIZONS, "horizon");
  const metric = enumValue(value.metric, AI_METRICS, "metric");
  const sort = enumValue(value.sort, AI_SORTS, "sort");
  const groupBy = enumValue(value.groupBy, ["none", "source_class"] as const, "groupBy");
  if (!Number.isInteger(value.limit) || (value.limit as number) < 1 || (value.limit as number) > AI_SEARCH_MAX_LIMIT) {
    throw new IntentValidationError(`limit must be an integer from 1 to ${AI_SEARCH_MAX_LIMIT}.`);
  }
  if (dateFrom && dateTo && dateFrom > dateTo) {
    throw new IntentValidationError("dateFrom must not be after dateTo.");
  }

  let comparison: AiSearchIntent["comparison"] = null;
  if (value.comparison !== null) {
    if (!value.comparison || typeof value.comparison !== "object" || Array.isArray(value.comparison)) {
      throw new IntentValidationError("comparison must be null or an object.");
    }
    const candidate = value.comparison as Record<string, unknown>;
    if (Object.keys(candidate).sort().join(",") !== "field,left,right") {
      throw new IntentValidationError("comparison contains unsupported fields.");
    }
    if (candidate.field !== "sourceClass") throw new IntentValidationError("Only sourceClass comparison is supported.");
    const left = enumValue(candidate.left, SOURCE_TYPES, "comparison.left");
    const right = enumValue(candidate.right, SOURCE_TYPES, "comparison.right");
    if (left === right) throw new IntentValidationError("Comparison groups must differ.");
    comparison = { field: "sourceClass", left, right };
  }

  const needsAsset = intent === "aggregate" || intent === "rank" || intent === "compare";
  if (needsAsset && !asset) {
    throw new IntentValidationError("Reaction analytics require one explicit asset.");
  }
  if ((intent === "rank" || intent === "compare") && !horizon) {
    throw new IntentValidationError("Ranking and comparison require one explicit horizon.");
  }
  if (intent === "compare" && (!comparison || !["mean", "median"].includes(metric))) {
    throw new IntentValidationError("Comparison requires two source classes and a mean or median metric.");
  }
  if (intent === "aggregate" && !["mean", "median", "sign_share"].includes(metric)) {
    throw new IntentValidationError("Aggregate intent requires mean, median, or sign_share.");
  }
  if (intent === "rank" && !["gainers", "losers"].includes(sort)) {
    throw new IntentValidationError("Ranking requires gainers or losers sort.");
  }
  if (reactionSign && (!asset || !horizon)) {
    throw new IntentValidationError("Reaction sign filtering requires one asset and horizon.");
  }

  return {
    intent, asset, dateFrom, dateTo, category, topic, actorType, action, direction, magnitude, amount, entity, assetRole,
    sourceClass, sentiment, reactionSign, importance,
    horizon, metric, sort, groupBy, comparison, limit: value.limit as number,
  };
}

export const AI_INTENT_JSON_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: [
    "intent", "asset", "dateFrom", "dateTo", "category", "topic", "actorType", "action", "direction",
    "magnitude", "amount", "entity", "assetRole", "sourceClass", "sentiment",
    "reactionSign", "importance", "horizon", "metric", "sort", "groupBy", "comparison", "limit",
  ],
  properties: {
    intent: { type: "string", enum: AI_INTENTS },
    asset: { anyOf: [{ type: "string", enum: ASSETS }, { type: "null" }] },
    dateFrom: { anyOf: [{ type: "string", pattern: "^\\d{4}-\\d{2}-\\d{2}$" }, { type: "null" }] },
    dateTo: { anyOf: [{ type: "string", pattern: "^\\d{4}-\\d{2}-\\d{2}$" }, { type: "null" }] },
    category: { anyOf: [{ type: "string", enum: EVENT_CATEGORIES }, { type: "null" }] },
    topic: { anyOf: [{ type: "string", enum: AI_TOPICS }, { type: "null" }] },
    actorType: { type: "string", enum: AI_ACTOR_TYPES },
    action: { anyOf: [{ type: "string", enum: AI_ACTIONS }, { type: "null" }] },
    direction: { type: "string", enum: AI_DIRECTIONS },
    magnitude: { type: "string", enum: AI_MAGNITUDES },
    amount: {
      anyOf: [
        { type: "null" },
        {
          type: "object", additionalProperties: false, required: ["currency", "value"],
          properties: {
            currency: { type: "string", enum: AI_AMOUNT_CURRENCIES },
            value: { type: "number", exclusiveMinimum: 0, maximum: 1_000_000_000_000_000 },
          },
        },
      ],
    },
    entity: { anyOf: [{ type: "string", minLength: 1, maxLength: 80 }, { type: "null" }] },
    assetRole: { type: "string", enum: AI_ASSET_ROLES },
    sourceClass: { anyOf: [{ type: "string", enum: SOURCE_TYPES }, { type: "null" }] },
    sentiment: { anyOf: [{ type: "string", enum: AI_SENTIMENTS }, { type: "null" }] },
    reactionSign: { anyOf: [{ type: "string", enum: AI_REACTION_SIGNS }, { type: "null" }] },
    importance: { anyOf: [{ type: "string", enum: AI_IMPORTANCE }, { type: "null" }] },
    horizon: { anyOf: [{ type: "string", enum: HORIZONS }, { type: "null" }] },
    metric: { type: "string", enum: AI_METRICS },
    sort: { type: "string", enum: AI_SORTS },
    groupBy: { type: "string", enum: ["none", "source_class"] },
    comparison: {
      anyOf: [
        { type: "null" },
        {
          type: "object",
          additionalProperties: false,
          required: ["field", "left", "right"],
          properties: {
            field: { type: "string", enum: ["sourceClass"] },
            left: { type: "string", enum: SOURCE_TYPES },
            right: { type: "string", enum: SOURCE_TYPES },
          },
        },
      ],
    },
    limit: { type: "integer", minimum: 1, maximum: AI_SEARCH_MAX_LIMIT },
  },
} as const;

export const AI_RESOLUTION_JSON_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["status", "intent", "message"],
  properties: {
    status: { type: "string", enum: ["ready", "clarification", "rejected"] },
    intent: { anyOf: [AI_INTENT_JSON_SCHEMA, { type: "null" }] },
    message: { anyOf: [{ type: "string", minLength: 1, maxLength: 240 }, { type: "null" }] },
  },
} as const;

export function validateResolutionEnvelope(input: unknown): import("@/types/ai-search").IntentResolution {
  if (!input || typeof input !== "object" || Array.isArray(input)) {
    throw new IntentValidationError("Provider resolution must be an object.");
  }
  const value = input as Record<string, unknown>;
  if (Object.keys(value).sort().join(",") !== "intent,message,status") {
    throw new IntentValidationError("Provider resolution contains unsupported fields.");
  }
  if (value.status === "ready") {
    if (value.message !== null) throw new IntentValidationError("Ready resolution must not include a message.");
    return { status: "ready", intent: validateIntent(value.intent) };
  }
  if (value.status === "clarification" || value.status === "rejected") {
    if (value.intent !== null || typeof value.message !== "string" || value.message.length < 1 || value.message.length > 240) {
      throw new IntentValidationError("Non-ready resolution must contain only a safe message.");
    }
    return { status: value.status, message: value.message };
  }
  throw new IntentValidationError("Provider resolution status is invalid.");
}
