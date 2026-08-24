import { AI_SEARCH_MAX_QUESTION_LENGTH } from "@/lib/ai-search/schema";

const SQL_PATTERNS = [
  /\bselect\b[\s\S]{0,80}\bfrom\b/i,
  /\b(?:drop|alter|truncate|insert|update|delete)\s+(?:table|from|into|public\.|events\b)/i,
  /\bunion\s+select\b/i,
  /\b(?:pg_catalog|information_schema|service_role)\b/i,
];
const INJECTION_PATTERNS = [
  /ignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions?/i,
  /reveal\s+(?:the\s+)?(?:system|developer)\s+prompt/i,
  /(?:show|print|return|expose)\s+(?:me\s+)?(?:the\s+)?(?:api[_ -]?key|secret|credentials?)/i,
  /jailbreak|developer\s+mode/i,
];
const PREDICTION_PATTERNS = [
  /\b(?:predict|forecast)\b/i,
  /\b(?:price|ціна)\b[\s\S]{0,30}\b(?:tomorrow|next|буде|завтра)\b/i,
  /(?:should i\s+(?:buy|sell)\b|чи варто\s+(?:купувати|продавати))/i,
  /guaranteed\s+(?:return|profit)|гарантован(?:ий|і)\s+прибут/i,
];

export type QuestionSafety = { safe: true; question: string } | { safe: false; code: string; message: string };

export function checkQuestionSafety(input: unknown): QuestionSafety {
  if (typeof input !== "string") return { safe: false, code: "INVALID_QUESTION", message: "question must be a string." };
  const question = input.trim();
  if (question.length < 3) return { safe: false, code: "INVALID_QUESTION", message: "Please enter a more specific question." };
  if (question.length > AI_SEARCH_MAX_QUESTION_LENGTH) return { safe: false, code: "QUESTION_TOO_LONG", message: `Question must be at most ${AI_SEARCH_MAX_QUESTION_LENGTH} characters.` };
  if (SQL_PATTERNS.some((pattern) => pattern.test(question))) return { safe: false, code: "RAW_SQL_REJECTED", message: "Raw SQL and database instructions are not supported." };
  if (INJECTION_PATTERNS.some((pattern) => pattern.test(question))) return { safe: false, code: "PROMPT_INJECTION_REJECTED", message: "Prompt or credential extraction instructions are not supported." };
  if (PREDICTION_PATTERNS.some((pattern) => pattern.test(question))) return { safe: false, code: "FINANCIAL_PREDICTION_REJECTED", message: "This tool analyzes historical reactions and does not provide financial predictions or advice." };
  return { safe: true, question };
}
