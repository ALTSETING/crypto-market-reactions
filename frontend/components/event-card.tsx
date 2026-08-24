import Link from "next/link";

import { SourceTypeBadge } from "@/components/source-type-badge";
import { formatDate, formatReaction, reactionTone } from "@/lib/format";
import {
  AVERAGE_REACTION_TOOLTIP,
  getReactionValue,
  HORIZON_LABELS,
} from "@/lib/reactions";
import type { Asset, EventListItem, ReactionHorizon } from "@/types/events";

const summaryFields = {
  BTC: ["btc_1h", "btc_24h"],
  ETH: ["eth_1h", "eth_24h"],
  SOL: ["sol_1h", "sol_24h"],
} as const;

interface EventCardProps {
  event: EventListItem;
  selectedAsset: Asset | null;
  selectedHorizon: ReactionHorizon;
}

export function EventCard({ event, selectedAsset, selectedHorizon }: EventCardProps) {
  return (
    <article className="group min-w-0 overflow-hidden rounded-2xl border border-white/10 bg-slate-950/55 p-4 shadow-[0_18px_50px_rgba(0,0,0,0.12)] transition hover:border-emerald-400/30 hover:bg-slate-950/75 sm:p-6">
      <div className="flex flex-wrap items-center gap-2 text-xs font-medium text-slate-400">
        <time dateTime={event.published_at}>{formatDate(event.published_at, true)} UTC</time>
        <span aria-hidden="true">•</span>
        <span className="uppercase tracking-[0.12em] text-slate-300">{event.source}</span>
        <SourceTypeBadge sourceType={event.source_type} />
        <span className="rounded-full border border-white/10 bg-white/5 px-2.5 py-1 text-slate-300">
          {event.category.replaceAll("_", " ")}
        </span>
      </div>

      <h2 className="mt-4 max-w-4xl break-words text-base font-semibold leading-snug text-white min-[390px]:text-lg sm:text-xl">
        <Link
          className="outline-none transition group-hover:text-emerald-200 focus-visible:rounded focus-visible:ring-2 focus-visible:ring-emerald-300"
          href={`/events/${event.slug}`}
        >
          {event.title}
        </Link>
      </h2>

      <div className="mt-4 flex flex-wrap gap-2" aria-label="Related assets">
        {event.related_assets.map((asset) => (
          <span
            className="rounded-md border border-slate-700 bg-slate-900 px-2.5 py-1 text-xs font-semibold text-slate-200"
            key={asset}
          >
            {asset}
          </span>
        ))}
        {event.sentiment && (
          <span className="rounded-md bg-white/5 px-2.5 py-1 text-xs capitalize text-slate-300">
            {event.sentiment}
          </span>
        )}
      </div>

      {selectedAsset ? (
        <SelectedReaction asset={selectedAsset} event={event} horizon={selectedHorizon} />
      ) : (
        <div className="mt-5 grid gap-2 sm:grid-cols-3" aria-label="Market reaction summary">
          {event.related_assets.map((asset) => (
            <ReactionSummary asset={asset} event={event} key={asset} />
          ))}
        </div>
      )}

      <div className="mt-5 flex flex-col items-start gap-3 border-t border-white/8 pt-4 min-[420px]:flex-row min-[420px]:items-center min-[420px]:justify-between">
        <span className="text-xs text-slate-500">
          {selectedAsset
            ? `${selectedAsset} · ${HORIZON_LABELS[selectedHorizon]}`
            : "Reference returns · 1h / 24h"}
        </span>
        <Link
          className="inline-flex min-h-10 items-center text-sm font-semibold text-emerald-300 outline-none transition hover:text-emerald-200 focus-visible:rounded focus-visible:ring-2 focus-visible:ring-emerald-300"
          href={`/events/${event.slug}`}
        >
          View event <span aria-hidden="true">→</span>
        </Link>
      </div>
    </article>
  );
}

function SelectedReaction({ asset, event, horizon }: {
  asset: Asset;
  event: EventListItem;
  horizon: ReactionHorizon;
}) {
  const value = getReactionValue(event, asset, horizon);
  const average = horizon === "average";
  const label = average ? `Average ${asset} reaction` : `${asset} after ${HORIZON_LABELS[horizon]}`;

  return (
    <div
      aria-label={`${label}: ${value === null ? "No market data" : formatReaction(value)}`}
      className="mt-5 flex min-w-0 flex-wrap items-center justify-between gap-2 rounded-xl border border-white/8 bg-white/[0.035] px-4 py-3"
    >
      <span className="flex items-center gap-2 text-sm font-semibold text-slate-300">
        {label}
        {average && (
          <span
            aria-label={AVERAGE_REACTION_TOOLTIP}
            className="inline-flex size-5 items-center justify-center rounded-full border border-white/15 text-xs text-slate-400"
            role="img"
            title={AVERAGE_REACTION_TOOLTIP}
          >
            ?
          </span>
        )}
      </span>
      <span
        className={`font-mono text-sm font-semibold tabular-nums ${value === null ? "text-slate-500" : reactionTone(value)}`}
      >
        {value === null ? "No market data" : formatReaction(value)}
      </span>
    </div>
  );
}

function ReactionSummary({ asset, event }: { asset: Asset; event: EventListItem }) {
  const [oneHourField, dayField] = summaryFields[asset];
  const oneHour = event[oneHourField];
  const day = event[dayField];
  if (oneHour === null && day === null) return null;

  return (
    <div className="flex min-w-0 items-center justify-between rounded-xl bg-white/[0.035] px-3 py-2.5">
      <span className="text-xs font-bold text-slate-400">{asset}</span>
      <span className="flex gap-3 font-mono text-xs tabular-nums">
        {oneHour !== null && <span className={reactionTone(oneHour)} title="1 hour return">{formatReaction(oneHour)}</span>}
        {day !== null && <span className={reactionTone(day)} title="24 hour return">{formatReaction(day)}</span>}
      </span>
    </div>
  );
}
