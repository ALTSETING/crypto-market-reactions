import { SOURCE_TYPE_LABELS } from "@/types/events";
import type { AnalyticsResult } from "@/types/ai-search";
import { formatPercent } from "@/lib/ai-search/format";

const number = (value: number | null): string => value === null
  ? "—"
  : String(Math.round((value + Number.EPSILON) * 100) / 100);
const percent = (value: number | null): string => formatPercent(value);

export function groundedAnswer(result: AnalyticsResult): { answer: string; calculation: string } {
  const empty = result.kind === "search" ? result.matched === 0
    : result.kind === "comparison" ? result.left.sampleSize + result.right.sampleSize === 0
      : result.kind === "topic_comparison" ? result.left.independentSampleSize + result.right.independentSampleSize === 0
        : result.kind === "topic_ranking" ? false
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
        answer: `Positive: ${formatPercent(result.positivePercent, false)}; negative: ${formatPercent(result.negativePercent, false)}; neutral: ${formatPercent(result.neutralPercent, false)}.`,
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
        answer: "Historical reaction across all horizons.",
        calculation: "Mean, median, positive share, and sample size are shown for each horizon.",
      };
    case "topic_ranking":
      return result.insufficientData
        ? {
          answer: `Insufficient data for a reliable topic ranking at ${result.horizon}.`,
          calculation: `No topic met the minimum of ${result.minimumSampleSize} independent Reaction V2 observations.`,
        }
        : {
          answer: `${result.items.length} deterministically ranked topics are shown below.`,
          calculation: `${result.metric} ranking at ${result.horizon}; minimum independent sample ${result.minimumSampleSize}.`,
        };
    case "topic_comparison":
      return {
        answer: "Deterministic topic comparison is shown below.",
        calculation: `${result.metric} comparison at ${result.horizon}; null Reaction V2 values were excluded.`,
      };
  }
}
