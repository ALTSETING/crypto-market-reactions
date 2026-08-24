import { SOURCE_TYPE_LABELS } from "@/types/events";
import type { AnalyticsResult } from "@/types/ai-search";

const number = (value: number | null): string => value === null
  ? "unavailable"
  : String(Math.round((value + Number.EPSILON) * 100) / 100);

export function groundedAnswer(result: AnalyticsResult): { answer: string; calculation: string } {
  switch (result.kind) {
    case "search":
      return {
        answer: `Found ${result.matched} matching events and returned ${result.returned}.`,
        calculation: `Deterministic filter match: ${result.matched}; cited results: ${result.returned}.`,
      };
    case "count":
      return {
        answer: `The count is ${result.value}.`,
        calculation: `Counted ${result.sampleSize} matching events.`,
      };
    case "scalar":
      return {
        answer: `${result.metric === "mean" ? "Mean" : "Median"} historical reaction is ${number(result.value)}%.`,
        calculation: `${result.metric} over ${result.sampleSize} non-null observations; null values were excluded.`,
      };
    case "share":
      return {
        answer: `Positive: ${number(result.positivePercent)}%; negative: ${number(result.negativePercent)}%; neutral: ${number(result.neutralPercent)}%.`,
        calculation: `Sign shares over ${result.sampleSize} non-null historical reaction observations.`,
      };
    case "ranking":
      return {
        answer: result.items.length === 0
          ? "No non-null Reaction V2 observations matched."
          : `${result.items.length} ranked events are shown below.`,
        calculation: `Ranked ${result.sampleSize} non-null observations; returned ${result.items.length}.`,
      };
    case "comparison":
      return {
        answer: `${SOURCE_TYPE_LABELS[result.left.sourceClass]}: ${number(result.left.value)}%; ${SOURCE_TYPE_LABELS[result.right.sourceClass]}: ${number(result.right.value)}%; difference: ${number(result.difference)} percentage points.`,
        calculation: `${result.metric} comparison with sample sizes ${result.left.sampleSize} and ${result.right.sampleSize}; null values were excluded.`,
      };
  }
}
