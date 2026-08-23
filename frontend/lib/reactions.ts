import type { Asset, EventListItem, Horizon, ReactionHorizon } from "@/types/events";

export const AVERAGE_REACTION_TOOLTIP =
  "Average of the available market returns across six time horizons. At least three values are required.";

export const HORIZON_LABELS: Record<ReactionHorizon, string> = {
  "1m": "1 minute",
  "5m": "5 minutes",
  "15m": "15 minutes",
  "1h": "1 hour",
  "4h": "4 hours",
  "24h": "24 hours",
  average: "Average",
};

export function calculateAverageReaction(values: Array<number | null>): number | null {
  const available = values.filter((value): value is number => value !== null);
  if (available.length < 3) return null;
  return available.reduce((sum, value) => sum + value, 0) / available.length;
}

export function reactionColumn(asset: Asset, horizon: ReactionHorizon): keyof EventListItem {
  const prefix = asset.toLowerCase();
  return (horizon === "average"
    ? `${prefix}_average_reaction`
    : `${prefix}_${horizon}`) as keyof EventListItem;
}

export function getReactionValue(
  event: EventListItem,
  asset: Asset,
  horizon: ReactionHorizon,
): number | null {
  const value = event[reactionColumn(asset, horizon)];
  return typeof value === "number" ? value : null;
}

export function getAssetReactionValues(event: EventListItem, asset: Asset): Array<number | null> {
  return (["1m", "5m", "15m", "1h", "4h", "24h"] as Horizon[]).map((horizon) =>
    getReactionValue(event, asset, horizon),
  );
}
