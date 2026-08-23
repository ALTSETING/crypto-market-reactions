import { Suspense } from "react";

import { EventsExplorer } from "@/components/events-explorer";

export default function HomePage() {
  return (
    <main className="min-h-screen overflow-hidden">
      <div className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-[520px] bg-[radial-gradient(circle_at_25%_0%,rgba(16,185,129,0.11),transparent_38%),radial-gradient(circle_at_80%_15%,rgba(56,189,248,0.07),transparent_32%)]" />
      <div className="mx-auto w-full max-w-6xl px-4 py-10 sm:px-6 sm:py-16 lg:px-8">
        <header className="max-w-4xl">
          <div className="flex items-center gap-3">
            <span className="size-2 rounded-full bg-emerald-400 shadow-[0_0_18px_rgba(52,211,153,0.8)]" />
            <p className="text-xs font-bold uppercase tracking-[0.24em] text-emerald-300">
              Historical market intelligence
            </p>
          </div>
          <h1 className="mt-6 text-balance text-4xl font-semibold tracking-[-0.04em] text-white sm:text-6xl">
            Crypto Market <span className="text-slate-400">Reaction Database</span>
          </h1>
          <p className="mt-5 max-w-3xl text-pretty text-base leading-7 text-slate-400 sm:text-lg">
            Search 7,878 canonical crypto news events and inspect verified BTC, ETH, and SOL returns from one minute to twenty-four hours after publication.
          </p>
          <dl className="mt-8 grid max-w-2xl grid-cols-3 gap-3">
            <Stat label="Events" value="7,878" />
            <Stat label="Date range" value="2017–2026" />
            <Stat label="Horizons" value="6 per asset" />
          </dl>
        </header>

        <Suspense fallback={<div className="mt-10 h-72 animate-pulse rounded-3xl border border-white/8 bg-slate-900/40" />}>
          <EventsExplorer />
        </Suspense>
      </div>
    </main>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-white/8 bg-white/[0.025] px-3 py-3 sm:px-4">
      <dt className="text-[10px] font-semibold uppercase tracking-wider text-slate-600 sm:text-xs">{label}</dt>
      <dd className="mt-1 text-sm font-semibold text-slate-200 sm:text-base">{value}</dd>
    </div>
  );
}
