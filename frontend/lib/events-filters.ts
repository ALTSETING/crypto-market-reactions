import type { EventSort } from "@/types/events";

export type FilterUpdate = Record<string, string | null>;
export type QuickAction = "gainers" | "losers";

const REACTION_SORTS: EventSort[] = ["growth", "decline"];

export function isReactionSort(value: string | null): value is "growth" | "decline" {
  return value !== null && REACTION_SORTS.includes(value as EventSort);
}

export function applyFilterUpdates(
  current: URLSearchParams,
  updates: FilterUpdate,
): URLSearchParams {
  const next = new URLSearchParams(current.toString());
  for (const [key, value] of Object.entries(updates)) {
    if (value === null || value === "") next.delete(key);
    else next.set(key, value);
  }

  if (!next.get("asset")) {
    if (isReactionSort(next.get("sort"))) next.delete("sort");
    next.delete("marketDataOnly");
  }
  return next;
}

export function applyQuickAction(
  current: URLSearchParams,
  action: QuickAction,
): URLSearchParams {
  if (!current.get("asset")) return new URLSearchParams(current.toString());
  return applyFilterUpdates(current, {
    sort: action === "gainers" ? "growth" : "decline",
    horizon: "average",
    marketDataOnly: "true",
    page: null,
  });
}

export function clearAllEventFilters(): URLSearchParams {
  return new URLSearchParams();
}
