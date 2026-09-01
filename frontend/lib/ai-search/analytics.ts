import type {
  AiCitation,
  AiSearchIntent,
  AnalyticsEvent,
  AnalyticsResult,
} from "@/types/ai-search";
import type { MultiHorizonAnalyticsResult } from "@/types/ai-search";
import {
  classifySemanticEvent,
  requiresSemanticMatching,
  SEMANTIC_CONFIDENCE_THRESHOLD,
  type SemanticEventMatch,
} from "@/lib/ai-search/semantic-matcher";
import { HORIZONS } from "@/types/events";
import type { SourceType } from "@/types/events";
import { groupIndependentEvents } from "@/lib/ai-search/event-dedup";

const round = (value: number): number => Math.round((value + Number.EPSILON) * 1_000_000) / 1_000_000;
const cite = (event: AnalyticsEvent, match?: SemanticEventMatch, groupSize = 1): AiCitation => ({
  eventId: event.eventId,
  title: event.title,
  href: `/events/${encodeURIComponent(event.slug)}`,
  ...(match ? { relevanceConfidence: match.confidence, assetRole: match.assetRole } : {}),
  ...(groupSize > 1 ? { groupSize } : {}),
});

function broadFiltered(events: readonly AnalyticsEvent[], intent: AiSearchIntent): AnalyticsEvent[] {
  return events.filter((event) => {
    if (intent.asset && !event.assets.includes(intent.asset)) return false;
    if (intent.dateFrom && event.publishedAt.slice(0, 10) < intent.dateFrom) return false;
    if (intent.dateTo && event.publishedAt.slice(0, 10) > intent.dateTo) return false;
    if (intent.category && event.category !== intent.category) return false;
    if (intent.sourceClass && event.sourceClass !== intent.sourceClass) return false;
    if (intent.sentiment && event.sentiment !== intent.sentiment) return false;
    if (intent.importance && event.importance !== intent.importance) return false;
    if (intent.reactionSign) {
      if (!intent.asset || !intent.horizon) return false;
      const reaction = event.reactionV2[intent.asset][intent.horizon];
      if (reaction === null || (intent.reactionSign === "positive" ? reaction <= 0 : reaction >= 0)) return false;
    }
    return true;
  });
}

function filtered(events: readonly AnalyticsEvent[], intent: AiSearchIntent): {
  matches: AnalyticsEvent[];
  topicFilter: AnalyticsResult["topicFilter"];
  semanticMatches: Map<string, SemanticEventMatch>;
} {
  const broad = broadFiltered(events, intent);
  const semanticMatches = new Map<string, SemanticEventMatch>();
  const semantic = requiresSemanticMatching(intent);
  const matches = semantic ? broad.filter((event) => {
    const match = classifySemanticEvent(event, intent);
    if (match.matched) semanticMatches.set(event.eventId, match);
    return match.matched;
  }) : broad;
  return {
    matches,
    topicFilter: intent.topic ? {
      topic: intent.topic,
      broadSampleSize: broad.length,
      matchedSampleSize: matches.length,
      independentEventCount: matches.length,
      duplicateGroupCount: 0,
      largestDuplicateGroup: matches.length > 0 ? 1 : 0,
      largestEntity: null,
      largestEntityShare: 0,
      entityConcentrationWarning: false,
      confidenceThreshold: SEMANTIC_CONFIDENCE_THRESHOLD,
      heuristicMatches: [...semanticMatches.values()].filter(({ confidence }) => confidence === SEMANTIC_CONFIDENCE_THRESHOLD).length,
    } : undefined,
    semanticMatches,
  };
}

function stableNewest(a: AnalyticsEvent, b: AnalyticsEvent): number {
  return b.publishedAt.localeCompare(a.publishedAt) || a.eventId.localeCompare(b.eventId);
}

function semanticRelevanceNewest(
  semanticMatches: ReadonlyMap<string, SemanticEventMatch>,
  a: AnalyticsEvent,
  b: AnalyticsEvent,
): number {
  return (semanticMatches.get(b.eventId)?.relevanceScore ?? 0) - (semanticMatches.get(a.eventId)?.relevanceScore ?? 0)
    || stableNewest(a, b);
}

function values(events: AnalyticsEvent[], intent: AiSearchIntent): Array<{ event: AnalyticsEvent; value: number }> {
  if (!intent.asset || !intent.horizon) return [];
  return events.flatMap((event) => {
    const value = event.reactionV2[intent.asset!][intent.horizon!];
    return value === null ? [] : [{ event, value }];
  });
}

export function mean(numbers: readonly number[]): number | null {
  return numbers.length === 0 ? null : round(numbers.reduce((sum, value) => sum + value, 0) / numbers.length);
}

export function median(numbers: readonly number[]): number | null {
  if (numbers.length === 0) return null;
  const sorted = [...numbers].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0 ? round((sorted[middle - 1] + sorted[middle]) / 2) : sorted[middle];
}

export function standardDeviation(numbers: readonly number[]): number | null {
  if (numbers.length < 2) return null;
  const average = numbers.reduce((sum, value) => sum + value, 0) / numbers.length;
  const variance = numbers.reduce((sum, value) => sum + ((value - average) ** 2), 0) / (numbers.length - 1);
  return round(Math.sqrt(variance));
}

export function standardError(numbers: readonly number[]): number | null {
  const deviation = standardDeviation(numbers);
  return deviation === null ? null : round(deviation / Math.sqrt(numbers.length));
}

export function trimmedMean(numbers: readonly number[], fraction = 0.05): number | null {
  if (numbers.length === 0) return null;
  const sorted = [...numbers].sort((a, b) => a - b);
  const trim = Math.floor(sorted.length * fraction);
  return mean(trim > 0 && trim * 2 < sorted.length ? sorted.slice(trim, -trim) : sorted);
}

export function wilson95Interval(successes: number, sampleSize: number): { low: number; high: number } | null {
  if (sampleSize === 0) return null;
  const z = 1.959963984540054;
  const proportion = successes / sampleSize;
  const denominator = 1 + (z * z) / sampleSize;
  const center = (proportion + (z * z) / (2 * sampleSize)) / denominator;
  const margin = z * Math.sqrt((proportion * (1 - proportion) + (z * z) / (4 * sampleSize)) / sampleSize) / denominator;
  return { low: round(Math.max(0, (center - margin) * 100)), high: round(Math.min(100, (center + margin) * 100)) };
}

function comparisonSide(
  rows: Array<{ event: AnalyticsEvent; value: number }>,
  sourceClass: SourceType,
  metric: "mean" | "median",
) {
  const group = rows.filter(({ event }) => event.sourceClass === sourceClass).map(({ value }) => value);
  return { sourceClass, value: metric === "mean" ? mean(group) : median(group), sampleSize: group.length };
}

export function runAnalytics(events: readonly AnalyticsEvent[], intent: AiSearchIntent): AnalyticsResult {
  const filteredResult = filtered(events, intent);
  const rankedMatches = filteredResult.matches.sort((a, b) => semanticRelevanceNewest(filteredResult.semanticMatches, a, b));
  const independent = groupIndependentEvents(rankedMatches, intent, filteredResult.semanticMatches);
  const matches = independent.representatives;
  const semanticMatch = (event: AnalyticsEvent) => filteredResult.semanticMatches.get(event.eventId);
  const groupSize = (event: AnalyticsEvent) => independent.groupSizeByRepresentativeId.get(event.eventId) ?? 1;
  const topicFilter = filteredResult.topicFilter ? {
    ...filteredResult.topicFilter,
    independentEventCount: matches.length,
    duplicateGroupCount: independent.duplicateGroupCount,
    largestDuplicateGroup: independent.largestGroupSize,
    largestEntity: independent.largestEntity,
    largestEntityShare: independent.largestEntityShare,
    entityConcentrationWarning: independent.largestEntityShare > 50,
  } : undefined;
  const topic = topicFilter ? { topicFilter } : {};
  if (intent.intent === "search") {
    const selected = (intent.sort === "oldest" ? [...matches].reverse() : matches).slice(0, intent.limit);
    return { kind: "search", matched: matches.length, returned: selected.length, citations: selected.map((event) => cite(event, semanticMatch(event), groupSize(event))), ...topic };
  }
  if (intent.intent === "count") {
    const selected = matches.slice(0, intent.limit);
    return { kind: "count", value: matches.length, sampleSize: matches.length, citations: selected.map((event) => cite(event, semanticMatch(event), groupSize(event))), ...topic };
  }

  const rows = values(matches, intent);
  const citations = rows.slice(0, intent.limit).map(({ event }) => cite(event, semanticMatch(event), groupSize(event)));
  if (intent.intent === "rank") {
    const direction = intent.sort as "gainers" | "losers";
    const ordered = [...rows].sort((a, b) =>
      (direction === "gainers" ? b.value - a.value : a.value - b.value) || a.event.eventId.localeCompare(b.event.eventId),
    ).slice(0, intent.limit);
    const items = ordered.map(({ event, value }) => ({ ...cite(event, semanticMatch(event), groupSize(event)), reaction: value }));
    return { kind: "ranking", direction, sampleSize: rows.length, items, unit: "percent", citations: ordered.map(({ event }) => cite(event, semanticMatch(event), groupSize(event))), ...topic };
  }
  if (intent.intent === "compare" && intent.comparison) {
    const metric = intent.metric as "mean" | "median";
    const left = comparisonSide(rows, intent.comparison.left, metric);
    const right = comparisonSide(rows, intent.comparison.right, metric);
    const difference = left.value === null || right.value === null ? null : round(left.value - right.value);
    const comparisonCitations = rows
      .filter(({ event }) => event.sourceClass === intent.comparison!.left || event.sourceClass === intent.comparison!.right)
      .slice(0, intent.limit)
      .map(({ event }) => cite(event, semanticMatch(event), groupSize(event)));
    return { kind: "comparison", metric, left, right, difference, unit: "percentage_points", citations: comparisonCitations, ...topic };
  }
  if (intent.metric === "sign_share") {
    const positive = rows.filter(({ value }) => value > 0).length;
    const negative = rows.filter(({ value }) => value < 0).length;
    const neutral = rows.length - positive - negative;
    const percent = (count: number) => rows.length === 0 ? null : round(count * 100 / rows.length);
    return { kind: "share", positivePercent: percent(positive), negativePercent: percent(negative), neutralPercent: percent(neutral), sampleSize: rows.length, positive95Ci: wilson95Interval(positive, rows.length), unit: "percent", citations, ...topic };
  }
  const metric = intent.metric as "mean" | "median";
  const sample = rows.map(({ value }) => value);
  return {
    kind: "scalar", metric, value: metric === "mean" ? mean(sample) : median(sample), sampleSize: sample.length,
    standardDeviation: standardDeviation(sample), standardError: standardError(sample), trimmedMean5Percent: trimmedMean(sample),
    unit: "percent", citations, ...topic,
  };
}

export function runMultiHorizonAnalytics(events: readonly AnalyticsEvent[], intent: AiSearchIntent): MultiHorizonAnalyticsResult {
  const results = HORIZONS.map((horizon) => {
    const base = { ...intent, intent: "aggregate" as const, horizon };
    const meanResult = runAnalytics(events, { ...base, metric: "mean" });
    const medianResult = runAnalytics(events, { ...base, metric: "median" });
    const shareResult = runAnalytics(events, { ...base, metric: "sign_share" });
    return {
      horizon,
      mean: meanResult.kind === "scalar" ? meanResult.value : null,
      median: medianResult.kind === "scalar" ? medianResult.value : null,
      positivePercent: shareResult.kind === "share" ? shareResult.positivePercent : null,
      sampleSize: meanResult.kind === "scalar" ? meanResult.sampleSize : 0,
      standardDeviation: meanResult.kind === "scalar" ? meanResult.standardDeviation : null,
      standardError: meanResult.kind === "scalar" ? meanResult.standardError : null,
      trimmedMean5Percent: meanResult.kind === "scalar" ? meanResult.trimmedMean5Percent : null,
      positive95Ci: shareResult.kind === "share" ? shareResult.positive95Ci : null,
      citations: meanResult.citations,
      topicFilter: meanResult.topicFilter,
    };
  });
  const citations = [...new Map(results.flatMap((row) => row.citations).map((citation) => [citation.eventId, citation])).values()].slice(0, 50);
  return {
    kind: "multi_horizon",
    rows: results.map((row) => ({
      horizon: row.horizon,
      mean: row.mean,
      median: row.median,
      positivePercent: row.positivePercent,
      sampleSize: row.sampleSize,
      standardDeviation: row.standardDeviation,
      standardError: row.standardError,
      trimmedMean5Percent: row.trimmedMean5Percent,
      positive95Ci: row.positive95Ci,
    })),
    citations,
    ...(results[0]?.topicFilter ? { topicFilter: results[0].topicFilter } : {}),
  };
}
