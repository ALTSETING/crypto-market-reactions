import { groundedAnswer } from "@/lib/ai-search/answer";
import type { AiSearchDataAdapter } from "@/lib/ai-search/adapter";
import { AiSearchDataError } from "@/lib/ai-search/adapter";
import type { AiIntentProvider } from "@/lib/ai-search/provider";
import { checkQuestionSafety } from "@/lib/ai-search/safety";
import { HORIZONS } from "@/types/events";
import type { AiSearchErrorBody, AiSearchSuccess, AnalyticsResult } from "@/types/ai-search";

export type AiSearchServiceResult =
  | { statusCode: 200; body: AiSearchSuccess }
  | { statusCode: 400 | 422 | 503; body: AiSearchErrorBody };

export async function executeAiSearch(
  questionInput: unknown,
  provider: AiIntentProvider,
  adapter: AiSearchDataAdapter,
): Promise<AiSearchServiceResult> {
  const safety = checkQuestionSafety(questionInput);
  if (!safety.safe) {
    return { statusCode: 400, body: { status: "rejected", code: safety.code, message: safety.message } };
  }
  const resolution = await provider.resolve(safety.question);
  if (resolution.status !== "ready") {
    return {
      statusCode: resolution.status === "clarification" ? 422 : 503,
      body: {
        status: resolution.status === "clarification" ? "clarification" : "error",
        code: resolution.status === "clarification" ? "CLARIFICATION_REQUIRED" : "AI_PROVIDER_UNAVAILABLE",
        message: resolution.message,
      },
    };
  }
  let result: AnalyticsResult;
  try {
    if (resolution.intent.intent === "aggregate" && resolution.intent.horizon === null) {
      const metric: "mean" | "median" = resolution.intent.metric === "median" ? "median" : "mean";
      const perHorizon = await Promise.all(HORIZONS.map((horizon) => adapter.analyze({
        ...resolution.intent, horizon, metric,
      })));
      const median24 = await adapter.analyze({ ...resolution.intent, horizon: "24h", metric: "median" });
      const share24 = await adapter.analyze({ ...resolution.intent, horizon: "24h", metric: "sign_share" });
      const citations = [...new Map(perHorizon.flatMap((entry) => entry.citations).map((citation) => [citation.eventId, citation])).values()].slice(0, 50);
      result = {
        kind: "multi_horizon" as const,
        metric,
        rows: perHorizon.map((entry, index) => ({
          horizon: HORIZONS[index],
          value: entry.kind === "scalar" ? entry.value : null,
          sampleSize: entry.kind === "scalar" ? entry.sampleSize : 0,
        })),
        median24h: median24.kind === "scalar" ? median24.value : null,
        positivePercent24h: share24.kind === "share" ? share24.positivePercent : null,
        sampleSize24h: share24.kind === "share" ? share24.sampleSize : 0,
        citations,
      };
    } else {
      result = await adapter.analyze(resolution.intent);
    }
  } catch (error) {
    if (error instanceof AiSearchDataError) {
      return {
        statusCode: error.code === "QUERY_TOO_BROAD" ? 422 : 503,
        body: {
          status: error.code === "QUERY_TOO_BROAD" ? "clarification" : "error",
          code: error.code,
          message: error.message,
        },
      };
    }
    throw error;
  }
  const wording = groundedAnswer(result);
  return {
    statusCode: 200,
    body: {
      status: "ok",
      basedOn: "Reaction V2",
      intent: resolution.intent,
      ...wording,
      result,
      citations: result.citations.slice(0, 50),
      disclaimer: "Historical analysis only — not financial advice.",
    },
  };
}
