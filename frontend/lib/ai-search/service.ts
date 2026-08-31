import { groundedAnswer } from "@/lib/ai-search/answer";
import type { AiSearchDataAdapter } from "@/lib/ai-search/adapter";
import { AiSearchDataError } from "@/lib/ai-search/adapter";
import { MockGeneralAnswerProvider, type GeneralAnswerProvider } from "@/lib/ai-search/general-provider";
import type { AiIntentProvider } from "@/lib/ai-search/provider";
import { MockAiResearchRouter, type AiResearchRouter } from "@/lib/ai-search/router";
import { checkQuestionSafety } from "@/lib/ai-search/safety";
import type { AiGeneralSuccess, AiHybridSuccess, AiResearchSuccess, AiSearchErrorBody, AiSearchSuccess, AnalyticsResult } from "@/types/ai-search";

export type AiSearchServiceResult =
  | { statusCode: 200; body: AiSearchSuccess }
  | { statusCode: 400 | 422 | 503; body: AiSearchErrorBody };

export type AiResearchServiceResult =
  | { statusCode: 200; body: AiResearchSuccess }
  | { statusCode: 400 | 422 | 503; body: AiSearchErrorBody };

async function executeDatabaseSearch(
  question: string,
  language: "en" | "uk",
  provider: AiIntentProvider,
  adapter: AiSearchDataAdapter,
): Promise<AiSearchServiceResult> {
  const resolution = await provider.resolve(question);
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
    result = resolution.intent.intent === "aggregate" && resolution.intent.horizon === null
      ? await adapter.analyzeOverview(resolution.intent)
      : await adapter.analyze(resolution.intent);
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
      mode: "database",
      modeLabel: "Historical database analysis",
      language,
      basedOn: "Reaction V2",
      intent: resolution.intent,
      ...wording,
      result,
      citations: result.citations.slice(0, 50),
      disclaimer: "Historical analysis only — not financial advice.",
    },
  };
}

export function executeAiSearch(questionInput: unknown, provider: AiIntentProvider, adapter: AiSearchDataAdapter): Promise<AiSearchServiceResult>;
export function executeAiSearch(
  questionInput: unknown,
  provider: AiIntentProvider,
  adapter: AiSearchDataAdapter,
  router: AiResearchRouter,
  generalProvider: GeneralAnswerProvider,
): Promise<AiResearchServiceResult>;
export async function executeAiSearch(
  questionInput: unknown,
  provider: AiIntentProvider,
  adapter: AiSearchDataAdapter,
  router: AiResearchRouter = new MockAiResearchRouter(),
  generalProvider: GeneralAnswerProvider = new MockGeneralAnswerProvider(),
): Promise<AiResearchServiceResult> {
  const safety = checkQuestionSafety(questionInput);
  if (!safety.safe) {
    return { statusCode: 400, body: { status: "refusal", code: safety.code, message: safety.message } };
  }

  let routed;
  try {
    routed = await router.resolve(safety.question);
  } catch {
    return { statusCode: 503, body: { status: "error", code: "AI_ROUTER_UNAVAILABLE", message: "AI Research routing is temporarily unavailable." } };
  }
  if (routed.route === "clarification") {
    return { statusCode: 422, body: { status: "clarification", code: "CLARIFICATION_REQUIRED", message: routed.clarificationQuestion ?? "Please make the request more specific." } };
  }
  if (routed.route === "refusal") {
    return { statusCode: 400, body: { status: "refusal", code: "REQUEST_OUT_OF_SCOPE", message: routed.refusalReason ?? "This request is outside AI Research scope." } };
  }
  if (routed.route === "live_unsupported") {
    return { statusCode: 422, body: { status: "live_unsupported", code: "LIVE_DATA_UNSUPPORTED", message: routed.refusalReason ?? "Live data is not supported." } };
  }
  if (routed.route === "database") return executeDatabaseSearch(safety.question, routed.language, provider, adapter);
  if (!routed.generalTopic) {
    return { statusCode: 503, body: { status: "error", code: "INVALID_ROUTER_RESULT", message: "AI Research could not validate the selected route." } };
  }

  if (routed.route === "general") {
    try {
      const answer = await generalProvider.answer({ question: safety.question, language: routed.language, topic: routed.generalTopic });
      const body: AiGeneralSuccess = {
        status: "ok",
        mode: "general",
        modeLabel: "General AI explanation — no live sources",
        language: routed.language,
        answer,
        citations: [],
        disclaimer: routed.language === "uk" ? "Загальне освітнє пояснення — не фінансова порада." : "General educational explanation — not financial advice.",
      };
      return { statusCode: 200, body };
    } catch {
      return { statusCode: 503, body: { status: "error", code: "GENERAL_PROVIDER_UNAVAILABLE", message: "The general AI explanation is temporarily unavailable." } };
    }
  }

  const [database, explanation] = await Promise.all([
    executeDatabaseSearch(safety.question, routed.language, provider, adapter),
    generalProvider.answer({ question: safety.question, language: routed.language, topic: routed.generalTopic }).catch(() => null),
  ]);
  if (database.statusCode !== 200) return database;
  if (!explanation) {
    return { statusCode: 503, body: { status: "error", code: "GENERAL_PROVIDER_UNAVAILABLE", message: "The general AI explanation is temporarily unavailable." } };
  }
  const body: AiHybridSuccess = {
    ...database.body,
    mode: "hybrid",
    modeLabel: "Combined answer: general explanation + Reaction V2",
    generalExplanation: explanation,
  };
  return { statusCode: 200, body };
}
