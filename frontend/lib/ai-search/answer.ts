import { SOURCE_TYPE_LABELS } from "@/types/events";
import type { AnalyticsResult } from "@/types/ai-search";

const number = (value: number | null): string => value === null
  ? "—"
  : String(Math.round((value + Number.EPSILON) * 100) / 100);
const percent = (value: number | null): string => value === null ? "—" : `${number(value)}%`;

export function groundedAnswer(result: AnalyticsResult): { answer: string; calculation: string } {
  const empty = result.kind === "search" ? result.matched === 0
    : result.kind === "comparison" ? result.left.sampleSize + result.right.sampleSize === 0
      : result.kind === "multi_horizon" ? result.rows.every((row) => row.sampleSize === 0)
        : result.sampleSize === 0;
  if (empty) return { answer: "No matching historical events found.", calculation: "" };
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
        answer: `${result.metric === "mean" ? "Mean" : "Median"} historical reaction is ${percent(result.value)}.`,
        calculation: `${result.metric} over ${result.sampleSize} non-null observations; null values were excluded.`,
      };
    case "share":
      return {
        answer: `Positive: ${percent(result.positivePercent)}; negative: ${percent(result.negativePercent)}; neutral: ${percent(result.neutralPercent)}.`,
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
        answer: `${SOURCE_TYPE_LABELS[result.left.sourceClass]}: ${percent(result.left.value)}; ${SOURCE_TYPE_LABELS[result.right.sourceClass]}: ${percent(result.right.value)}; difference: ${number(result.difference)} percentage points.`,
        calculation: `${result.metric} comparison with sample sizes ${result.left.sampleSize} and ${result.right.sampleSize}; null values were excluded.`,
      };
    case "multi_horizon":
      return {
        answer: "Historical reaction across all Reaction V2 horizons.",
        calculation: `24h median: ${percent(result.median24h)}; positive 24h: ${percent(result.positivePercent24h)}; n=${result.sampleSize24h}.`,
      };
  }
}
