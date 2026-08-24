import { groundedAnswer } from "@/lib/ai-search/answer";
import type { AiSearchDataAdapter } from "@/lib/ai-search/adapter";
import { AiSearchDataError } from "@/lib/ai-search/adapter";
import type { AiIntentProvider } from "@/lib/ai-search/provider";
import { checkQuestionSafety } from "@/lib/ai-search/safety";
import type { AiSearchErrorBody, AiSearchSuccess } from "@/types/ai-search";

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
  let result;
  try {
    result = await adapter.analyze(resolution.intent);
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
