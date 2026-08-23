import { formatDate, formatReaction, reactionTone } from "@/lib/format";
import { ASSETS, HORIZONS, type Asset, type EventDetail, type Horizon } from "@/types/events";

function reactionValue(event: EventDetail, asset: Asset, horizon: Horizon): number | null {
  const key = `${asset.toLowerCase()}_${horizon}` as keyof EventDetail;
  return event[key] as number | null;
}

export function ReactionTable({ event }: { event: EventDetail }) {
  const availableAssets = ASSETS.filter((asset) =>
    HORIZONS.some((horizon) => reactionValue(event, asset, horizon) !== null),
  );

  if (availableAssets.length === 0) {
    return <p className="text-sm text-slate-400">No verified reaction metrics are available.</p>;
  }

  return (
    <div className="space-y-4">
      {availableAssets.map((asset) => {
        const source = event[`${asset.toLowerCase()}_reaction_source` as keyof EventDetail] as
          | string
          | null;
        const referenceTime = event[
          `${asset.toLowerCase()}_reference_time` as keyof EventDetail
        ] as string | null;
        const latency = event[
          `${asset.toLowerCase()}_reference_latency_minutes` as keyof EventDetail
        ] as number | null;
        return (
          <section className="rounded-2xl border border-white/10 bg-slate-950/45 p-4 sm:p-5" key={asset}>
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h3 className="text-sm font-bold tracking-[0.15em] text-white">{asset}</h3>
              {(referenceTime || latency !== null) && (
                <p className="text-xs text-slate-500">
                  {referenceTime && <>Reference {formatDate(referenceTime, true)} UTC</>}
                  {latency !== null && <> · latency {latency}m</>}
                </p>
              )}
            </div>
            <dl className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
              {HORIZONS.map((horizon) => {
                const value = reactionValue(event, asset, horizon);
                if (value === null) return null;
                return (
                  <div className="rounded-xl bg-white/[0.04] p-3" key={horizon}>
                    <dt className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                      {horizon}
                    </dt>
                    <dd className={`mt-1 font-mono text-sm font-semibold tabular-nums ${reactionTone(value)}`}>
                      {formatReaction(value)}
                    </dd>
                  </div>
                );
              })}
            </dl>
            {source && <p className="mt-3 break-words text-xs text-slate-500">Source: {source}</p>}
          </section>
        );
      })}
    </div>
  );
}
