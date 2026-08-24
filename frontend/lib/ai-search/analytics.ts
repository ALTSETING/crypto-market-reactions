import type {
  AiCitation,
  AiSearchIntent,
  AnalyticsEvent,
  AnalyticsResult,
} from "@/types/ai-search";
import type { SourceType } from "@/types/events";

const round = (value: number): number => Math.round((value + Number.EPSILON) * 1_000_000) / 1_000_000;
const cite = (event: AnalyticsEvent): AiCitation => ({
  eventId: event.eventId,
  title: event.title,
  href: `/events/${encodeURIComponent(event.slug)}`,
});

function filtered(events: readonly AnalyticsEvent[], intent: AiSearchIntent): AnalyticsEvent[] {
  return events.filter((event) => {
    if (intent.asset && !event.assets.includes(intent.asset)) return false;
    if (intent.dateFrom && event.publishedAt.slice(0, 10) < intent.dateFrom) return false;
    if (intent.dateTo && event.publishedAt.slice(0, 10) > intent.dateTo) return false;
    if (intent.category && event.category !== intent.category) return false;
    if (intent.sourceClass && event.sourceClass !== intent.sourceClass) return false;
    if (intent.sentiment && event.sentiment !== intent.sentiment) return false;
    if (intent.importance && event.importance !== intent.importance) return false;
    return true;
  });
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
  const matches = filtered(events, intent).sort(stableNewest);
  if (intent.intent === "search") {
    const selected = (intent.sort === "oldest" ? [...matches].reverse() : matches).slice(0, intent.limit);
    return { kind: "search", matched: matches.length, returned: selected.length, citations: selected.map(cite) };
  }
  if (intent.intent === "count") {
    const selected = matches.slice(0, intent.limit);
    return { kind: "count", value: matches.length, sampleSize: matches.length, citations: selected.map(cite) };
  }

  const rows = values(matches, intent);
  const citations = rows.slice(0, intent.limit).map(({ event }) => cite(event));
  if (intent.intent === "rank") {
    const direction = intent.sort as "gainers" | "losers";
    const ordered = [...rows].sort((a, b) =>
      (direction === "gainers" ? b.value - a.value : a.value - b.value) || a.event.eventId.localeCompare(b.event.eventId),
    ).slice(0, intent.limit);
    const items = ordered.map(({ event, value }) => ({ ...cite(event), reaction: value }));
    return { kind: "ranking", direction, sampleSize: rows.length, items, unit: "percent", citations: items.map(({ eventId, title, href }) => ({ eventId, title, href })) };
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
    return { kind: "comparison", metric, left, right, difference, unit: "percentage_points", citations: comparisonCitations };
  }
  if (intent.metric === "sign_share") {
    const positive = rows.filter(({ value }) => value > 0).length;
    const negative = rows.filter(({ value }) => value < 0).length;
    const neutral = rows.length - positive - negative;
    const percent = (count: number) => rows.length === 0 ? null : round(count * 100 / rows.length);
    return { kind: "share", positivePercent: percent(positive), negativePercent: percent(negative), neutralPercent: percent(neutral), sampleSize: rows.length, unit: "percent", citations };
  }
  const metric = intent.metric as "mean" | "median";
  const sample = rows.map(({ value }) => value);
  return { kind: "scalar", metric, value: metric === "mean" ? mean(sample) : median(sample), sampleSize: sample.length, unit: "percent", citations };
}
