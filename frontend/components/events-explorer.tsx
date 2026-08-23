"use client";

import { useCallback, useEffect, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { EventCard } from "@/components/event-card";
import {
  applyFilterUpdates,
  applyQuickAction,
  clearAllEventFilters,
  isReactionSort,
  type FilterUpdate,
} from "@/lib/events-filters";
import { HORIZON_LABELS } from "@/lib/reactions";
import {
  ASSETS,
  EVENT_SORTS,
  REACTION_HORIZONS,
  type ApiErrorBody,
  type Asset,
  type EventSort,
  type EventsPage,
  type ReactionHorizon,
} from "@/types/events";

const assetOptions: Array<{ label: string; value: Asset | null }> = [
  { label: "All events", value: null },
  { label: "BTC", value: "BTC" },
  { label: "ETH", value: "ETH" },
  { label: "SOL", value: "SOL" },
];

const sortLabels: Record<EventSort, string> = {
  newest: "Newest",
  oldest: "Oldest",
  growth: "Highest average growth",
  decline: "Highest average decline",
};

export function EventsExplorer() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const queryString = searchParams.toString();
  const currentQuery = searchParams.get("q") ?? "";
  const rawAsset = searchParams.get("asset")?.toUpperCase() ?? "";
  const currentAsset = ASSETS.includes(rawAsset as Asset) ? (rawAsset as Asset) : null;
  const rawSort = searchParams.get("sort") ?? "newest";
  const currentSort = EVENT_SORTS.includes(rawSort as EventSort)
    ? (rawSort as EventSort)
    : "newest";
  const rawHorizon = searchParams.get("horizon") ?? "average";
  const currentHorizon = REACTION_HORIZONS.includes(rawHorizon as ReactionHorizon)
    ? (rawHorizon as ReactionHorizon)
    : "average";
  const marketDataOnly = searchParams.get("marketDataOnly") === "true";
  const [data, setData] = useState<EventsPage | null>(null);
  const [requestError, setRequestError] = useState<string | null>(null);
  const [resolvedQuery, setResolvedQuery] = useState<string | null>(null);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const loading = resolvedQuery !== queryString;
  const error = resolvedQuery === queryString ? requestError : null;

  const navigateTo = useCallback(
    (params: URLSearchParams) => {
      const next = params.toString();
      router.replace(next ? `${pathname}?${next}` : pathname, { scroll: false });
    },
    [pathname, router],
  );

  const replaceParams = useCallback(
    (updates: FilterUpdate) => navigateTo(applyFilterUpdates(searchParams, updates)),
    [navigateTo, searchParams],
  );

  useEffect(() => {
    const controller = new AbortController();
    fetch(queryString ? `/api/events?${queryString}` : "/api/events", {
      cache: "no-store",
      signal: controller.signal,
    })
      .then(async (response) => {
        const body = (await response.json()) as EventsPage | ApiErrorBody;
        if (!response.ok) throw new Error("error" in body ? body.error : "Unable to load events.");
        return body as EventsPage;
      })
      .then((page) => {
        setData(page);
        setRequestError(null);
        setResolvedQuery(queryString);
      })
      .catch((fetchError: unknown) => {
        if (fetchError instanceof DOMException && fetchError.name === "AbortError") return;
        setRequestError(fetchError instanceof Error ? fetchError.message : "Unable to load events.");
        setResolvedQuery(queryString);
      });
    return () => controller.abort();
  }, [queryString]);

  function submitSearch(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const trimmed = String(form.get("q") ?? "").trim();
    if (trimmed !== currentQuery) replaceParams({ q: trimmed || null, page: null });
  }

  function applyAdvancedFilters(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    replaceParams({
      source: String(form.get("source") ?? "").trim() || null,
      from: String(form.get("from") ?? "") || null,
      to: String(form.get("to") ?? "") || null,
      page: null,
    });
  }

  function selectSort(sort: EventSort) {
    replaceParams({
      sort: sort === "newest" ? null : sort,
      marketDataOnly: isReactionSort(sort) ? "true" : marketDataOnly ? "true" : null,
      page: null,
    });
  }

  function runQuickAction(action: "gainers" | "losers") {
    navigateTo(applyQuickAction(searchParams, action));
  }

  const chips = getActiveChips(searchParams, currentAsset, currentSort, currentHorizon);
  const hasFilters = chips.length > 0 || Boolean(searchParams.get("page"));
  const csvParams = new URLSearchParams(queryString);
  csvParams.delete("limit");

  return (
    <section aria-labelledby="events-heading" className="mt-8 sm:mt-10">
      <div className="rounded-3xl border border-white/10 bg-slate-900/55 p-4 shadow-2xl shadow-black/20 backdrop-blur sm:p-6">
        <form key={currentQuery} onSubmit={submitSearch} role="search">
          <label className="text-sm font-semibold text-slate-200" htmlFor="event-search">
            Search historical events
          </label>
          <div className="mt-2 flex flex-col gap-2 sm:flex-row">
            <div className="relative min-w-0 flex-1">
              <svg aria-hidden="true" className="pointer-events-none absolute left-4 top-1/2 size-5 -translate-y-1/2 text-slate-500" fill="none" viewBox="0 0 24 24">
                <path d="m21 21-4.3-4.3m2.3-5.2a7.5 7.5 0 1 1-15 0 7.5 7.5 0 0 1 15 0Z" stroke="currentColor" strokeLinecap="round" strokeWidth="1.8" />
              </svg>
              <input aria-describedby="search-hint" autoComplete="off" className="h-[54px] w-full rounded-2xl border border-white/10 bg-slate-950/80 pl-12 pr-4 text-base text-white outline-none transition placeholder:text-slate-600 hover:border-white/20 focus:border-emerald-400/70 focus:ring-4 focus:ring-emerald-400/10" defaultValue={currentQuery} id="event-search" maxLength={120} name="q" placeholder="Try “ethereum etf” or “binance hack”" type="search" />
            </div>
            <button className="h-[54px] w-full shrink-0 rounded-2xl bg-emerald-400 px-6 text-sm font-bold text-slate-950 outline-none transition hover:bg-emerald-300 focus-visible:ring-2 focus-visible:ring-emerald-200 sm:w-auto" type="submit">Search</button>
          </div>
        </form>
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs text-slate-500" id="search-hint">Press Enter or select Search to update the results.</p>
          <button
            aria-controls="event-filters"
            aria-expanded={filtersOpen}
            className="inline-flex min-h-10 items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-3.5 text-sm font-semibold text-slate-300 outline-none transition hover:border-emerald-400/40 focus-visible:ring-2 focus-visible:ring-emerald-300"
            onClick={() => setFiltersOpen((open) => !open)}
            type="button"
          >
            <span aria-hidden="true">{filtersOpen ? "−" : "+"}</span>
            {filtersOpen ? "Hide filters" : "Show filters"}
            {chips.length > 0 && <span className="rounded-full bg-emerald-400/15 px-2 py-0.5 text-xs text-emerald-300">{chips.length}</span>}
          </button>
        </div>

        {filtersOpen && <div className="mt-5 border-t border-white/8 pt-5" id="event-filters">
        <fieldset>
          <legend className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">Related asset</legend>
          <div className="mt-2 flex flex-wrap gap-2">
            {assetOptions.map((option) => {
              const active = currentAsset === option.value;
              return (
                <button aria-pressed={active} className={`rounded-xl border px-4 py-2 text-sm font-semibold outline-none transition focus-visible:ring-2 focus-visible:ring-emerald-300 ${active ? "border-emerald-400/50 bg-emerald-400/12 text-emerald-200" : "border-white/10 bg-white/[0.025] text-slate-400 hover:border-white/20 hover:text-white"}`} key={option.label} onClick={() => replaceParams({ asset: option.value, page: null })} type="button">
                  {option.label}
                </button>
              );
            })}
          </div>
        </fieldset>

        <div className="mt-5 grid gap-3 border-t border-white/8 pt-5 sm:grid-cols-2 lg:grid-cols-4">
          <label className="text-xs font-medium text-slate-400">
            Sort by
            <select aria-describedby={!currentAsset ? "reaction-sort-hint" : undefined} className="mt-1.5 w-full rounded-xl border border-white/10 bg-slate-950/70 px-3 py-2.5 text-sm text-white outline-none focus:border-emerald-400/60" onChange={(event) => selectSort(event.target.value as EventSort)} value={currentSort}>
              <option value="newest">Newest</option>
              <option value="oldest">Oldest</option>
              <option disabled={!currentAsset} value="growth">Highest average growth</option>
              <option disabled={!currentAsset} value="decline">Highest average decline</option>
            </select>
          </label>
          <label className="text-xs font-medium text-slate-400">
            Reaction horizon
            <select aria-label="Reaction horizon" className="mt-1.5 w-full rounded-xl border border-white/10 bg-slate-950/70 px-3 py-2.5 text-sm text-white outline-none disabled:cursor-not-allowed disabled:opacity-45 focus:border-emerald-400/60" disabled={!currentAsset} onChange={(event) => replaceParams({ horizon: event.target.value === "average" ? null : event.target.value, page: null })} value={currentHorizon}>
              {REACTION_HORIZONS.map((horizon) => <option key={horizon} value={horizon}>{HORIZON_LABELS[horizon]}</option>)}
            </select>
          </label>
          <div className="sm:col-span-2">
            <span className="text-xs font-medium text-slate-400">Quick actions</span>
            <div className="mt-1.5 grid gap-2 sm:flex sm:flex-wrap">
              <button className="min-h-11 rounded-xl border border-emerald-400/30 bg-emerald-400/8 px-3 py-2.5 text-sm font-semibold text-emerald-200 outline-none enabled:hover:bg-emerald-400/15 disabled:cursor-not-allowed disabled:opacity-35 focus-visible:ring-2 focus-visible:ring-emerald-300" disabled={!currentAsset} onClick={() => runQuickAction("gainers")} type="button">Top gainers</button>
              <button className="min-h-11 rounded-xl border border-rose-400/30 bg-rose-400/8 px-3 py-2.5 text-sm font-semibold text-rose-200 outline-none enabled:hover:bg-rose-400/15 disabled:cursor-not-allowed disabled:opacity-35 focus-visible:ring-2 focus-visible:ring-rose-300" disabled={!currentAsset} onClick={() => runQuickAction("losers")} type="button">Top losers</button>
              <label className={`flex min-h-11 items-center gap-2 rounded-xl border border-white/10 px-3 py-2.5 text-sm ${currentAsset ? "cursor-pointer text-slate-300" : "cursor-not-allowed text-slate-600"}`}>
                <input checked={marketDataOnly} disabled={!currentAsset} onChange={(event) => replaceParams({ marketDataOnly: event.target.checked ? "true" : null, page: null })} type="checkbox" />
                Only with market data
              </label>
            </div>
          </div>
        </div>
        {!currentAsset && <p className="mt-2 text-xs text-slate-500" id="reaction-sort-hint">Select BTC, ETH, or SOL to sort by market reaction.</p>}

        <form className="mt-5 grid gap-3 border-t border-white/8 pt-5 sm:grid-cols-2 lg:grid-cols-[1fr_160px_160px_auto]" key={`${searchParams.get("source")}-${searchParams.get("from")}-${searchParams.get("to")}`} onSubmit={applyAdvancedFilters}>
          <label className="text-xs font-medium text-slate-400">Source<input className="mt-1.5 w-full rounded-xl border border-white/10 bg-slate-950/70 px-3 py-2.5 text-sm text-white outline-none focus:border-emerald-400/60" defaultValue={searchParams.get("source") ?? ""} maxLength={80} name="source" placeholder="e.g. coindesk" /></label>
          <label className="text-xs font-medium text-slate-400">From<input className="mt-1.5 w-full rounded-xl border border-white/10 bg-slate-950/70 px-3 py-2.5 text-sm text-white outline-none focus:border-emerald-400/60" defaultValue={searchParams.get("from") ?? ""} name="from" type="date" /></label>
          <label className="text-xs font-medium text-slate-400">To<input className="mt-1.5 w-full rounded-xl border border-white/10 bg-slate-950/70 px-3 py-2.5 text-sm text-white outline-none focus:border-emerald-400/60" defaultValue={searchParams.get("to") ?? ""} name="to" type="date" /></label>
          <div className="flex items-end gap-2 sm:col-span-2 lg:col-span-1">
            <button className="h-[44px] flex-1 rounded-xl bg-slate-100 px-4 text-sm font-bold text-slate-950 outline-none transition hover:bg-white focus-visible:ring-2 focus-visible:ring-emerald-300 sm:flex-none" type="submit">Apply</button>
            {hasFilters && <button className="h-[42px] rounded-xl px-3 text-sm text-slate-400 outline-none hover:text-white focus-visible:ring-2 focus-visible:ring-emerald-300" onClick={() => navigateTo(clearAllEventFilters())} type="button">Clear all filters</button>}
          </div>
        </form>
        </div>}

        {chips.length > 0 && (
          <div aria-label="Active filters" className="mt-4 flex flex-wrap gap-2">
            {chips.map((chip) => (
              <button aria-label={`Remove ${chip.label} filter`} className="rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-slate-300 outline-none hover:border-rose-300/40 hover:text-white focus-visible:ring-2 focus-visible:ring-emerald-300" key={chip.key} onClick={() => replaceParams({ [chip.key]: null, page: null })} type="button">
                {chip.label} <span aria-hidden="true">×</span>
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="mt-8 flex flex-col items-stretch gap-4 sm:flex-row sm:flex-wrap sm:items-end sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-emerald-400">Event archive</p>
          <h2 className="mt-1 text-2xl font-semibold text-white" id="events-heading">{data ? `${data.total.toLocaleString("en-US")} results` : "Market events"}</h2>
        </div>
        <div className="flex flex-col items-stretch gap-2 min-[420px]:flex-row min-[420px]:items-center">
          <a className="min-h-11 rounded-lg border border-white/10 px-3 py-3 text-center text-xs font-semibold text-slate-300 outline-none hover:border-emerald-400/40 hover:text-white focus-visible:ring-2 focus-visible:ring-emerald-300 min-[420px]:py-2.5" href={`/api/events/export${csvParams.size ? `?${csvParams}` : ""}`}>Download current page CSV</a>
          <label className="flex min-h-11 items-center justify-between rounded-lg border border-white/10 px-3 text-xs text-slate-500 min-[420px]:border-0 min-[420px]:px-0">Per page
            <select aria-label="Events per page" className="ml-2 rounded-lg border border-white/10 bg-slate-900 px-2 py-1.5 text-sm text-white outline-none focus:border-emerald-400" onChange={(event) => replaceParams({ pageSize: event.target.value === "25" ? null : event.target.value, limit: null, page: null })} value={searchParams.get("pageSize") === "50" ? "50" : "25"}>
              <option value="25">25</option><option value="50">50</option>
            </select>
          </label>
        </div>
      </div>

      <div aria-busy={loading} aria-live="polite" className="mt-5">
        {error && <div className="rounded-2xl border border-rose-400/20 bg-rose-400/8 p-5 text-sm text-rose-100" role="alert"><p className="font-semibold">Events could not be loaded.</p><p className="mt-1 text-rose-200/75">{error}</p></div>}
        {!error && !data && loading && <EventSkeletons />}
        {!error && data && data.items.length === 0 && <div className="rounded-2xl border border-dashed border-white/15 px-6 py-16 text-center"><p className="text-lg font-semibold text-white">No matching events</p><p className="mt-2 text-sm text-slate-500">Try a broader query or clear one of the filters.</p></div>}
        {!error && data && data.items.length > 0 && (
          <div className={`grid gap-4 transition-opacity ${loading ? "opacity-50" : "opacity-100"}`}>
            {data.items.map((event) => <EventCard event={event} key={event.event_id} selectedAsset={currentAsset} selectedHorizon={currentHorizon} />)}
          </div>
        )}
      </div>

      {data && data.totalPages > 0 && (
        <nav aria-label="Event result pages" className="mt-8 flex items-center justify-between gap-2 rounded-2xl border border-white/10 bg-slate-900/50 p-2.5 sm:p-4">
          <button className="min-h-11 rounded-xl border border-white/10 px-3 py-2 text-sm font-semibold text-slate-200 outline-none transition enabled:hover:border-white/25 enabled:hover:bg-white/5 focus-visible:ring-2 focus-visible:ring-emerald-300 disabled:cursor-not-allowed disabled:opacity-35 sm:px-4" disabled={data.page <= 1 || loading} onClick={() => replaceParams({ page: String(data.page - 1) })} type="button"><span aria-hidden="true">←</span> <span className="hidden min-[360px]:inline">Previous</span></button>
          <p className="text-center text-xs text-slate-500 sm:text-sm">Page <span className="font-semibold text-white">{data.page}</span> of {data.totalPages}</p>
          <button className="min-h-11 rounded-xl border border-white/10 px-3 py-2 text-sm font-semibold text-slate-200 outline-none transition enabled:hover:border-white/25 enabled:hover:bg-white/5 focus-visible:ring-2 focus-visible:ring-emerald-300 disabled:cursor-not-allowed disabled:opacity-35 sm:px-4" disabled={data.page >= data.totalPages || loading} onClick={() => replaceParams({ page: String(data.page + 1) })} type="button"><span className="hidden min-[360px]:inline">Next</span> <span aria-hidden="true">→</span></button>
        </nav>
      )}
    </section>
  );
}

function getActiveChips(params: URLSearchParams, asset: Asset | null, sort: EventSort, horizon: ReactionHorizon) {
  const chips: Array<{ key: string; label: string }> = [];
  if (params.get("q")) chips.push({ key: "q", label: `Search: ${params.get("q")}` });
  if (asset) chips.push({ key: "asset", label: `Asset: ${asset}` });
  if (sort !== "newest") chips.push({ key: "sort", label: `Sort: ${sortLabels[sort]}` });
  if (asset && params.has("horizon")) chips.push({ key: "horizon", label: `Horizon: ${HORIZON_LABELS[horizon]}` });
  if (params.get("marketDataOnly") === "true") chips.push({ key: "marketDataOnly", label: "Only with market data" });
  if (params.get("source")) chips.push({ key: "source", label: `Source: ${params.get("source")}` });
  if (params.get("from")) chips.push({ key: "from", label: `From: ${params.get("from")}` });
  if (params.get("to")) chips.push({ key: "to", label: `To: ${params.get("to")}` });
  return chips;
}

function EventSkeletons() {
  return (
    <div aria-label="Loading events" className="grid gap-4" role="status">
      {[0, 1, 2].map((item) => <div className="animate-pulse rounded-2xl border border-white/8 bg-slate-950/40 p-6" key={item}><div className="h-3 w-44 rounded bg-white/8" /><div className="mt-5 h-6 w-4/5 rounded bg-white/8" /><div className="mt-3 h-6 w-2/5 rounded bg-white/5" /><div className="mt-6 h-12 rounded-xl bg-white/5" /></div>)}
      <span className="sr-only">Loading events…</span>
    </div>
  );
}
