import { Suspense } from "react";
import type { Metadata } from "next";
import { unstable_cache } from "next/cache";

import { EventsExplorer } from "@/components/events-explorer";
import { SeoJsonLd } from "@/components/seo-json-ld";
import { getDatasetStats } from "@/lib/data/events";
import { buildWebPageStructuredData, EVENTS_DESCRIPTION, EVENTS_TITLE, SITE_NAME, siteUrl } from "@/lib/seo";

export const dynamic = "force-dynamic";

const getCachedDatasetStats = unstable_cache(getDatasetStats, ["public-dataset-stats-v9073"], {
  revalidate: 3_600,
  tags: ["public-events"],
});

interface EventsPageProps {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export async function generateMetadata({ searchParams }: EventsPageProps): Promise<Metadata> {
  const hasSearchState = Object.keys(await searchParams).length > 0;
  const canonical = siteUrl("/events");
  return {
    title: { absolute: EVENTS_TITLE },
    description: EVENTS_DESCRIPTION,
    alternates: { canonical },
    robots: { index: !hasSearchState, follow: true },
    openGraph: { title: EVENTS_TITLE, description: EVENTS_DESCRIPTION, url: canonical, type: "website", siteName: SITE_NAME },
    twitter: { card: "summary", title: EVENTS_TITLE, description: EVENTS_DESCRIPTION },
  };
}

export default async function EventsPage() {
  const stats = await getCachedDatasetStats();
  const eventCount = stats.events.toLocaleString("en-US");
  const dateRange = `${stats.firstYear}–${stats.lastYear}`;
  return (
    <main className="min-h-screen overflow-hidden">
      <SeoJsonLd data={buildWebPageStructuredData({
        name: EVENTS_TITLE,
        description: EVENTS_DESCRIPTION,
        path: "/events",
        breadcrumbs: [{ name: "Home", path: "/" }, { name: "Events", path: "/events" }],
      })} />
      <div className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-[520px] bg-[radial-gradient(circle_at_25%_0%,rgba(16,185,129,0.1),transparent_40%),radial-gradient(circle_at_80%_15%,rgba(56,189,248,0.05),transparent_34%)]" />
      <div className="mx-auto w-full max-w-6xl px-4 pb-10 pt-20 sm:px-6 sm:py-16 lg:px-8">
        <header className="max-w-4xl">
          <div className="flex items-center gap-3">
            <span className="size-2 rounded-full bg-emerald-400 shadow-[0_0_18px_rgba(52,211,153,0.8)]" />
            <p className="text-xs font-bold uppercase tracking-[0.24em] text-emerald-300">Historical market intelligence</p>
          </div>
          <h1 className="mt-5 text-balance text-3xl font-semibold tracking-[-0.04em] text-white min-[390px]:text-4xl sm:mt-6 sm:text-6xl">
            Historical Crypto <span className="text-slate-400">Event Archive</span>
          </h1>
          <p className="mt-5 max-w-3xl text-pretty text-base leading-7 text-slate-400 sm:text-lg">
            Search {eventCount} archived crypto events and inspect historical BTC, ETH and SOL Reaction V2 returns from one minute through twenty-four hours after publication.
          </p>
          <dl className="mt-7 grid max-w-2xl grid-cols-3 gap-2 sm:mt-8 sm:gap-3">
            <Stat label="Events" value={eventCount} />
            <Stat label="Date range" value={dateRange} />
            <Stat label="Horizons" value="6 per asset" />
          </dl>
        </header>

        <Suspense fallback={<div className="mt-10 h-72 animate-pulse rounded-3xl border border-white/8 bg-slate-900/40" />}>
          <EventsExplorer />
        </Suspense>

        <section className="mt-12 border-t border-white/8 pt-6" aria-labelledby="coverage-heading">
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-emerald-400">Coverage transparency</p>
          <h2 className="mt-2 text-xl font-semibold text-white" id="coverage-heading">Events by year</h2>
          <p className="mt-2 text-sm leading-6 text-slate-500">Historical coverage is uneven; counts show archived event pages, not completeness of the news record.</p>
          <dl className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-5">
            {stats.eventsByYear.map(({ year, events }) => (
              <div className="border-l border-white/10 px-3 py-1" key={year}>
                <dt className="text-xs text-slate-500">{year}</dt>
                <dd className="mt-1 font-mono text-sm font-semibold text-slate-200">{events.toLocaleString("en-US")}</dd>
              </div>
            ))}
          </dl>
        </section>
      </div>
    </main>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 border-l border-white/10 px-2.5 py-2 sm:px-4">
      <dt className="text-[10px] font-semibold uppercase tracking-wider text-slate-600 sm:text-xs">{label}</dt>
      <dd className="mt-1 break-words text-xs font-semibold text-slate-200 min-[390px]:text-sm sm:text-base">{value}</dd>
    </div>
  );
}
