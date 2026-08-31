import "server-only";

import { AI_TOPICS, type AiDirection, type AiSearchIntent, type AiTopic } from "@/types/ai-search";
import { HORIZONS, type Asset, type Horizon } from "@/types/events";

export const AI_RESEARCH_ROUTES = ["database", "general", "hybrid", "clarification", "refusal", "live_unsupported"] as const;
export type AiResearchRoute = (typeof AI_RESEARCH_ROUTES)[number];

export const GENERAL_TOPICS = [
  "bitcoin", "ethereum", "solana", "etf", "staking", "defi", "hacks", "stablecoins",
  "proof_of_work", "proof_of_stake", "institutional_adoption", "general_crypto",
] as const;
export type GeneralTopic = (typeof GENERAL_TOPICS)[number];

export interface RouterDatabaseIntent {
  asset: Asset | null;
  horizon: Horizon | null;
  topic: AiTopic | null;
  direction: AiDirection;
  dateFrom: string | null;
  dateTo: string | null;
}

export interface AiRouterDecision {
  route: AiResearchRoute;
  language: "en" | "uk";
  generalTopic: GeneralTopic | null;
  databaseIntent: RouterDatabaseIntent | null;
  needsHistoricalAnalysis: boolean;
  needsCurrentInformation: boolean;
  clarificationQuestion: string | null;
  refusalReason: string | null;
}

const nullableString = { anyOf: [{ type: "string" }, { type: "null" }] } as const;
const nullableDate = { anyOf: [{ type: "string", pattern: "^20[0-9]{2}-[0-9]{2}-[0-9]{2}$" }, { type: "null" }] } as const;
export const AI_ROUTER_JSON_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["route", "language", "generalTopic", "databaseIntent", "needsHistoricalAnalysis", "needsCurrentInformation", "clarificationQuestion", "refusalReason"],
  properties: {
    route: { type: "string", enum: [...AI_RESEARCH_ROUTES] },
    language: { type: "string", enum: ["en", "uk"] },
    generalTopic: { anyOf: [{ type: "string", enum: [...GENERAL_TOPICS] }, { type: "null" }] },
    databaseIntent: {
      anyOf: [
        { type: "null" },
        {
          type: "object", additionalProperties: false,
          required: ["asset", "horizon", "topic", "direction", "dateFrom", "dateTo"],
          properties: {
            asset: { anyOf: [{ type: "string", enum: ["BTC", "ETH", "SOL"] }, { type: "null" }] },
            horizon: { anyOf: [{ type: "string", enum: [...HORIZONS] }, { type: "null" }] },
            topic: { anyOf: [{ type: "string", enum: [...AI_TOPICS] }, { type: "null" }] },
            direction: { type: "string", enum: ["inflow", "outflow", "neutral", "unknown"] },
            dateFrom: nullableDate,
            dateTo: nullableDate,
          },
        },
      ],
    },
    needsHistoricalAnalysis: { type: "boolean" },
    needsCurrentInformation: { type: "boolean" },
    clarificationQuestion: nullableString,
    refusalReason: nullableString,
  },
} as const;

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

export function validateRouterDecision(input: unknown): AiRouterDecision {
  if (!input || typeof input !== "object" || Array.isArray(input)) throw new Error("Invalid router decision.");
  const value = input as Record<string, unknown>;
  const exactKeys = ["route", "language", "generalTopic", "databaseIntent", "needsHistoricalAnalysis", "needsCurrentInformation", "clarificationQuestion", "refusalReason"];
  if (Object.keys(value).length !== exactKeys.length || exactKeys.some((key) => !(key in value))) throw new Error("Invalid router fields.");
  if (!AI_RESEARCH_ROUTES.includes(value.route as AiResearchRoute)) throw new Error("Invalid route.");
  if (value.language !== "en" && value.language !== "uk") throw new Error("Invalid language.");
  if (value.generalTopic !== null && !GENERAL_TOPICS.includes(value.generalTopic as GeneralTopic)) throw new Error("Invalid general topic.");
  if (typeof value.needsHistoricalAnalysis !== "boolean" || typeof value.needsCurrentInformation !== "boolean") throw new Error("Invalid route flags.");
  if (!isNullableString(value.clarificationQuestion) || !isNullableString(value.refusalReason)) throw new Error("Invalid route message.");
  if (value.databaseIntent !== null) {
    if (!value.databaseIntent || typeof value.databaseIntent !== "object" || Array.isArray(value.databaseIntent)) throw new Error("Invalid database intent.");
    const intent = value.databaseIntent as Record<string, unknown>;
    const keys = ["asset", "horizon", "topic", "direction", "dateFrom", "dateTo"];
    if (Object.keys(intent).length !== keys.length || keys.some((key) => !(key in intent))) throw new Error("Invalid database intent fields.");
    if (intent.asset !== null && !["BTC", "ETH", "SOL"].includes(String(intent.asset))) throw new Error("Invalid asset.");
    if (intent.horizon !== null && !HORIZONS.includes(intent.horizon as Horizon)) throw new Error("Invalid horizon.");
    if (intent.topic !== null && !AI_TOPICS.includes(intent.topic as AiTopic)) throw new Error("Invalid topic.");
    if (!["inflow", "outflow", "neutral", "unknown"].includes(String(intent.direction))) throw new Error("Invalid direction.");
    const validDate = (date: unknown) => date === null || (typeof date === "string" && /^20\d{2}-\d{2}-\d{2}$/.test(date));
    if (!validDate(intent.dateFrom) || !validDate(intent.dateTo)) throw new Error("Invalid dates.");
  }
  const route = value.route as AiResearchRoute;
  const historical = route === "database" || route === "hybrid";
  const general = route === "general" || route === "hybrid";
  const current = route === "live_unsupported";
  if (value.needsHistoricalAnalysis !== historical || value.needsCurrentInformation !== current) throw new Error("Inconsistent route flags.");
  if (historical && value.databaseIntent === null) throw new Error("Historical route requires a database intent.");
  if (!historical && value.databaseIntent !== null) throw new Error("Non-historical route cannot include a database intent.");
  if (general && value.generalTopic === null) throw new Error("Explanation route requires a general topic.");
  if (!general && value.generalTopic !== null) throw new Error("Non-explanation route cannot include a general topic.");
  if (route === "clarification" && !value.clarificationQuestion) throw new Error("Clarification text is required.");
  if (route !== "clarification" && value.clarificationQuestion !== null) throw new Error("Unexpected clarification text.");
  if ((route === "refusal" || route === "live_unsupported") && !value.refusalReason) throw new Error("Refusal text is required.");
  if (route !== "refusal" && route !== "live_unsupported" && value.refusalReason !== null) throw new Error("Unexpected refusal text.");
  return value as unknown as AiRouterDecision;
}

export function databaseIntentFromConstraints(constraints: Partial<AiSearchIntent>): RouterDatabaseIntent {
  return {
    asset: constraints.asset ?? null,
    horizon: constraints.horizon ?? null,
    topic: constraints.topic ?? null,
    direction: constraints.direction ?? "unknown",
    dateFrom: constraints.dateFrom ?? null,
    dateTo: constraints.dateTo ?? null,
  };
}
