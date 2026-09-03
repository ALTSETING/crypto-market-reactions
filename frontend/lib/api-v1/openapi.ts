import { AI_TOPICS } from "@/types/ai-search";
import { ASSETS, EVENT_CATEGORIES, HORIZONS, SOURCE_TYPES } from "@/types/events";
import { API_DIRECTIONS, API_MAX_LIMIT } from "@/lib/api-v1/types";
import { API_EVENT_ID_MAX_LENGTH, API_EVENT_ID_PATTERN } from "@/lib/api-v1/validation";

const errorResponse = {
  description: "Error",
  content: {
    "application/json": {
      schema: {
        type: "object",
        required: ["error"],
        properties: {
          error: {
            type: "object",
            required: ["code", "message"],
            properties: { code: { type: "string" }, message: { type: "string" } },
          },
        },
      },
    },
  },
} as const;

const authenticatedErrors = {
  "400": errorResponse,
  "401": errorResponse,
  "429": errorResponse,
  "503": errorResponse,
};

const dateParameter = (name: "dateFrom" | "dateTo") => ({
  name,
  in: "query",
  required: false,
  schema: { type: "string", format: "date" },
});

const reactionProperties = Object.fromEntries(HORIZONS.map((horizon) => [horizon, {
  anyOf: [{ type: "number" }, { type: "null" }],
}])) as Record<string, unknown>;

const eventSchema = {
  type: "object",
  required: ["id", "slug", "title", "publishedAt", "source", "primaryAsset", "relatedAssets", "category", "sourceClass", "reactionV2"],
  properties: {
    id: { type: "string" },
    slug: { type: "string" },
    title: { type: "string" },
    publishedAt: { type: "string", format: "date-time" },
    source: { type: "string" },
    sourceUrl: { type: "string", format: "uri" },
    primaryAsset: { anyOf: [{ type: "string", enum: ASSETS }, { type: "null" }] },
    relatedAssets: { type: "array", items: { type: "string", enum: ASSETS } },
    category: { type: "string", enum: EVENT_CATEGORIES },
    sourceClass: { type: "string", enum: SOURCE_TYPES },
    topic: { type: "string", enum: AI_TOPICS },
    reactionV2: {
      type: "object",
      required: ASSETS,
      properties: Object.fromEntries(ASSETS.map((asset) => [asset, {
        type: "object", required: HORIZONS, properties: reactionProperties,
      }])),
    },
  },
} as const;

const reactionRowSchema = {
  type: "object",
  required: ["horizon", "matchedArticles", "independentEvents", "mean", "median", "positivePercent", "negativePercent", "sampleSize"],
  properties: {
    horizon: { type: "string", enum: HORIZONS },
    matchedArticles: { type: "integer", minimum: 0 },
    independentEvents: { type: "integer", minimum: 0 },
    mean: { anyOf: [{ type: "number" }, { type: "null" }] },
    median: { anyOf: [{ type: "number" }, { type: "null" }] },
    positivePercent: { anyOf: [{ type: "number" }, { type: "null" }] },
    negativePercent: { anyOf: [{ type: "number" }, { type: "null" }] },
    sampleSize: { type: "integer", minimum: 0 },
  },
} as const;

const nullableTopic = { anyOf: [{ type: "string", enum: AI_TOPICS }, { type: "null" }] } as const;
const nullableDirection = { anyOf: [{ type: "string", enum: API_DIRECTIONS }, { type: "null" }] } as const;
const paginationSchema = {
  type: "object",
  required: ["nextCursor", "hasMore"],
  properties: {
    nextCursor: { anyOf: [{ type: "string" }, { type: "null" }] },
    hasMore: { type: "boolean" },
  },
} as const;

const singleReactionDataSchema = {
  type: "object",
  required: ["asset", "topic", "direction", ...reactionRowSchema.required],
  properties: {
    asset: { type: "string", enum: ASSETS },
    topic: nullableTopic,
    direction: nullableDirection,
    ...reactionRowSchema.properties,
  },
} as const;

const multiReactionDataSchema = {
  type: "object",
  required: ["asset", "topic", "direction", "rows"],
  properties: {
    asset: { type: "string", enum: ASSETS },
    topic: nullableTopic,
    direction: nullableDirection,
    rows: { type: "array", minItems: 6, maxItems: 6, items: reactionRowSchema },
  },
} as const;

export const OPENAPI_V1_SCHEMA = {
  openapi: "3.1.0",
  info: {
    title: "Crypto Market Reactions API",
    version: "1.0.0",
    description: "Authenticated read-only access to historical events and deterministic Reaction V2 analytics.",
  },
  servers: [{ url: "https://crypto-market-reactions.com" }],
  security: [{ bearerAuth: [] }],
  paths: {
    "/api/v1/health": {
      get: {
        operationId: "getHealth",
        responses: {
          "200": { description: "API health", content: { "application/json": { schema: { type: "object", required: ["status", "apiVersion"], properties: { status: { const: "ok" }, apiVersion: { const: "v1" } } } } } },
          "401": errorResponse,
          "429": errorResponse,
          "503": errorResponse,
        },
      },
    },
    "/api/v1/meta": {
      get: {
        operationId: "getMetadata",
        responses: {
          "200": {
            description: "Supported API values",
            content: { "application/json": { schema: { type: "object", required: ["data"], properties: { data: { type: "object", required: ["assets", "horizons", "topics", "categories", "apiVersion"], properties: {
              assets: { type: "array", items: { type: "string", enum: ASSETS } },
              horizons: { type: "array", items: { type: "string", enum: HORIZONS } },
              topics: { type: "array", items: { type: "string", enum: AI_TOPICS } },
              categories: { type: "array", items: { type: "string", enum: EVENT_CATEGORIES } },
              apiVersion: { const: "v1" },
            } } } } } },
          },
          ...authenticatedErrors,
        },
      },
    },
    "/api/v1/events": {
      get: {
        operationId: "listEvents",
        parameters: [
          { name: "asset", in: "query", schema: { type: "string", enum: ASSETS } },
          { name: "topic", in: "query", schema: { type: "string", enum: AI_TOPICS } },
          { name: "category", in: "query", schema: { type: "string", enum: EVENT_CATEGORIES } },
          { name: "sourceClass", in: "query", schema: { type: "string", enum: SOURCE_TYPES } },
          dateParameter("dateFrom"), dateParameter("dateTo"),
          { name: "search", in: "query", schema: { type: "string", maxLength: 160 } },
          { name: "limit", in: "query", schema: { type: "integer", minimum: 1, maximum: API_MAX_LIMIT, default: 50 } },
          { name: "cursor", in: "query", schema: { type: "string", maxLength: 512 } },
        ],
        responses: {
          "200": { description: "Cursor-paginated events", content: { "application/json": { schema: { type: "object", required: ["data", "pagination"], properties: { data: { type: "array", maxItems: API_MAX_LIMIT, items: eventSchema }, pagination: paginationSchema } } } } },
          ...authenticatedErrors,
        },
      },
    },
    "/api/v1/events/{slug}": {
      get: {
        operationId: "getEvent",
        parameters: [{ name: "slug", in: "path", required: true, schema: { type: "string", minLength: 1, maxLength: 180 } }],
        responses: { "200": { description: "One event", content: { "application/json": { schema: { type: "object", properties: { data: eventSchema } } } } }, "404": errorResponse, ...authenticatedErrors },
      },
    },
    "/api/v1/events/by-id/{eventId}": {
      get: {
        operationId: "getEventById",
        description: "Return at most one event using exact equality on the internal event ID primary key.",
        parameters: [{
          name: "eventId",
          in: "path",
          required: true,
          description: "Internal event ID returned as data[].id by GET /api/v1/events.",
          schema: { type: "string", minLength: 1, maxLength: API_EVENT_ID_MAX_LENGTH, pattern: API_EVENT_ID_PATTERN },
        }],
        responses: {
          "200": { description: "One event", content: { "application/json": { schema: { type: "object", required: ["data"], properties: { data: eventSchema } } } } },
          "400": errorResponse,
          "401": errorResponse,
          "404": errorResponse,
          "429": errorResponse,
          "500": errorResponse,
          "503": errorResponse,
        },
      },
    },
    "/api/v1/reactions": {
      get: {
        operationId: "getReactions",
        parameters: [
          { name: "asset", in: "query", required: true, schema: { type: "string", enum: ASSETS } },
          { name: "topic", in: "query", schema: { type: "string", enum: AI_TOPICS } },
          { name: "horizon", in: "query", schema: { type: "string", enum: HORIZONS } },
          dateParameter("dateFrom"), dateParameter("dateTo"),
          { name: "direction", in: "query", schema: { type: "string", enum: API_DIRECTIONS } },
        ],
        responses: {
          "200": {
            description: "Reaction V2 analytics",
            content: { "application/json": { schema: { type: "object", required: ["data", "basedOn"], properties: {
              data: { oneOf: [singleReactionDataSchema, multiReactionDataSchema] },
              basedOn: { const: "Reaction V2" },
            } } } },
          },
          ...authenticatedErrors,
        },
      },
    },
    "/api/v1/openapi.json": {
      get: { operationId: "getOpenApiSchema", responses: { "200": { description: "This OpenAPI 3.1 schema", content: { "application/json": { schema: { type: "object" } } } }, "401": errorResponse, "429": errorResponse, "503": errorResponse } },
    },
  },
  components: {
    securitySchemes: {
      bearerAuth: { type: "http", scheme: "bearer", bearerFormat: "API key" },
    },
  },
} as const;
