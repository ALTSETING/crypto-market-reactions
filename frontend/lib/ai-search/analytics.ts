import type {
  AiCitation,
  AiSearchIntent,
  AnalyticsEvent,
  AnalyticsResult,
} from "@/types/ai-search";
import type { MultiHorizonAnalyticsResult } from "@/types/ai-search";
import { matchesTopic } from "@/lib/ai-search/topic-matcher";
import { HORIZONS } from "@/types/events";
import type { SourceType } from "@/types/events";

const round = (value: number): number => Math.round((value + Number.EPSILON) * 1_000_000) / 1_000_000;
const cite = (event: AnalyticsEvent): AiCitation => ({
  eventId: event.eventId,
  title: event.title,
  href: `/events/${encodeURIComponent(event.slug)}`,
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
} {
  const broad = broadFiltered(events, intent);
  const matches = intent.topic ? broad.filter((event) => matchesTopic(event, intent.topic!)) : broad;
  return {
    matches,
    topicFilter: intent.topic ? {
      topic: intent.topic,
      broadSampleSize: broad.length,
      matchedSampleSize: matches.length,
    } : undefined,
  };
}

function stableNewest(a: AnalyticsEvent, b: AnalyticsEvent): number {
  return b.publishedAt.localeCompare(a.publishedAt) || a.eventId.localeCompare(b.eventId);
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
  const matches = filteredResult.matches.sort(stableNewest);
  const topic = filteredResult.topicFilter ? { topicFilter: filteredResult.topicFilter } : {};
  if (intent.intent === "search") {
    const selected = (intent.sort === "oldest" ? [...matches].reverse() : matches).slice(0, intent.limit);
    return { kind: "search", matched: matches.length, returned: selected.length, citations: selected.map(cite), ...topic };
  }
  if (intent.intent === "count") {
    const selected = matches.slice(0, intent.limit);
    return { kind: "count", value: matches.length, sampleSize: matches.length, citations: selected.map(cite), ...topic };
  }

  const rows = values(matches, intent);
  const citations = rows.slice(0, intent.limit).map(({ event }) => cite(event));
  if (intent.intent === "rank") {
    const direction = intent.sort as "gainers" | "losers";
    const ordered = [...rows].sort((a, b) =>
      (direction === "gainers" ? b.value - a.value : a.value - b.value) || a.event.eventId.localeCompare(b.event.eventId),
    ).slice(0, intent.limit);
    const items = ordered.map(({ event, value }) => ({ ...cite(event), reaction: value }));
    return { kind: "ranking", direction, sampleSize: rows.length, items, unit: "percent", citations: items.map(({ eventId, title, href }) => ({ eventId, title, href })), ...topic };
  }
  if (intent.intent === "compare" && intent.comparison) {
    const metric = intent.metric as "mean" | "median";
    const left = comparisonSide(rows, intent.comparison.left, metric);
    const right = comparisonSide(rows, intent.comparison.right, metric);
    const difference = left.value === null || right.value === null ? null : round(left.value - right.value);
    const comparisonCitations = rows
      .filter(({ event }) => event.sourceClass === intent.comparison!.left || event.sourceClass === intent.comparison!.right)
      .slice(0, intent.limit)
      .map(({ event }) => cite(event));
    return { kind: "comparison", metric, left, right, difference, unit: "percentage_points", citations: comparisonCitations, ...topic };
  }
  if (intent.metric === "sign_share") {
    const positive = rows.filter(({ value }) => value > 0).length;
    const negative = rows.filter(({ value }) => value < 0).length;
    const neutral = rows.length - positive - negative;
    const percent = (count: number) => rows.length === 0 ? null : round(count * 100 / rows.length);
    return { kind: "share", positivePercent: percent(positive), negativePercent: percent(negative), neutralPercent: percent(neutral), sampleSize: rows.length, unit: "percent", citations, ...topic };
  }
  const metric = intent.metric as "mean" | "median";
  const sample = rows.map(({ value }) => value);
  return { kind: "scalar", metric, value: metric === "mean" ? mean(sample) : median(sample), sampleSize: sample.length, unit: "percent", citations, ...topic };
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
    })),
    citations,
    ...(results[0]?.topicFilter ? { topicFilter: results[0].topicFilter } : {}),
  };
}
