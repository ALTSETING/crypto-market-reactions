import type { Metadata } from "next";
import { unstable_cache } from "next/cache";
import Link from "next/link";
import { notFound } from "next/navigation";
import { cache } from "react";

import { SeoJsonLd } from "@/components/seo-json-ld";
import { formatPercent } from "@/lib/ai-search/format";
import { getTopicLandingData } from "@/lib/data/topic-landings";
import { buildWebPageStructuredData, SITE_NAME, siteUrl } from "@/lib/seo";
import { getSeoTopicLanding } from "@/lib/seo-topics";
import type { Asset } from "@/types/events";

export const revalidate = 3_600;

const getCachedTopicData = cache(unstable_cache(
  getTopicLandingData,
  ["seo-topic-landing-v1"],
  { revalidate, tags: ["public-events", "seo-topics"] },
));

interface TopicPageProps {
  params: Promise<{ slug: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export async function generateMetadata({ params, searchParams }: TopicPageProps): Promise<Metadata> {
  const { slug } = await params;
  const landing = getSeoTopicLanding(slug);
  const data = landing ? await getCachedTopicData(slug) : null;
  if (!landing || !data) return { title: { absolute: `Topic not found | ${SITE_NAME}` }, robots: { index: false, follow: false } };
  const canonical = siteUrl(`/topics/${landing.slug}`);
  const hasQueryParameters = Object.keys(await searchParams).length > 0;
  return {
    title: { absolute: landing.seoTitle },
    description: landing.description,
    alternates: { canonical },
    robots: { index: !hasQueryParameters, follow: true },
    openGraph: { title: landing.seoTitle, description: landing.description, url: canonical, type: "website", siteName: SITE_NAME },
    twitter: { card: "summary", title: landing.seoTitle, description: landing.description },
  };
}

export default async function TopicPage({ params }: TopicPageProps) {
  const { slug } = await params;
  const landing = getSeoTopicLanding(slug);
  const data = landing ? await getCachedTopicData(slug) : null;
  if (!landing || !data) notFound();
  const populatedAssets = (Object.entries(data.assetBreakdown) as Array<[Asset, number]>).filter(([, count]) => count > 0);
  return (
    <main className="min-h-screen">
      <SeoJsonLd data={buildWebPageStructuredData({
        name: landing.seoTitle,
        description: landing.description,
        path: `/topics/${landing.slug}`,
        breadcrumbs: [{ name: "Home", path: "/" }, { name: landing.name, path: `/topics/${landing.slug}` }],
        about: [landing.name, landing.summaryAsset, "Reaction V2"],
      })} />
      <div className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-[500px] bg-[radial-gradient(circle_at_35%_0%,rgba(16,185,129,0.12),transparent_42%)]" />
      <div className="mx-auto w-full max-w-5xl px-4 pb-16 pt-24 sm:px-6 sm:pt-28">
        <nav aria-label="Breadcrumb" className="text-sm text-slate-500"><Link className="hover:text-white" href="/">Home</Link><span aria-hidden="true"> / </span><span>{landing.name}</span></nav>
        <header className="mt-7 max-w-4xl">
          <p className="text-xs font-bold uppercase tracking-[0.2em] text-emerald-400">Historical topic archive</p>
          <h1 className="mt-3 text-balance text-3xl font-semibold tracking-[-0.04em] text-white sm:text-5xl">{landing.name}</h1>
          <p className="mt-5 max-w-3xl text-base leading-7 text-slate-400">{landing.intro}</p>
          <dl className="mt-7 grid max-w-2xl grid-cols-2 gap-3 sm:grid-cols-4">
            <Metric label="Matched records" value={String(data.matchedRecords)} />
            <Metric label="Independent events" value={String(data.independentEvents)} />
            {populatedAssets.slice(0, 2).map(([asset, count]) => <Metric key={asset} label={`${asset} records`} value={String(count)} />)}
          </dl>
        </header>

        <section className="mt-12" aria-labelledby="reaction-summary">
          <p className="text-xs font-bold uppercase tracking-[0.2em] text-emerald-400">Reaction V2</p>
          <h2 className="mt-2 text-2xl font-semibold text-white" id="reaction-summary">{landing.summaryAsset} reaction summary</h2>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-500">Deterministic historical returns after each recorded publication timestamp. The sample varies by horizon, missing values are not estimated, and association does not establish causality.</p>
          <div className="mt-5 overflow-x-auto rounded-2xl border border-white/10">
            <table className="w-full min-w-[560px] border-collapse text-sm">
              <thead className="bg-slate-900/55 text-left text-slate-400"><tr><th className="p-3">Horizon</th><th className="p-3 text-right">Mean</th><th className="p-3 text-right">Median</th><th className="p-3 text-right">Positive share</th><th className="p-3 text-right">Sample</th></tr></thead>
              <tbody>{data.overview.rows.map((row) => <tr className="border-t border-white/10" key={row.horizon}><th className="p-3 text-left font-semibold text-slate-200">{row.horizon}</th><td className="p-3 text-right font-mono text-slate-300">{formatPercent(row.mean)}</td><td className="p-3 text-right font-mono text-slate-300">{formatPercent(row.median)}</td><td className="p-3 text-right font-mono text-slate-300">{formatPercent(row.positivePercent, false)}</td><td className="p-3 text-right font-mono text-slate-300">{row.sampleSize}</td></tr>)}</tbody>
            </table>
          </div>
        </section>

        <section className="mt-12" aria-labelledby="sources-title">
          <h2 className="text-2xl font-semibold text-white" id="sources-title">Example events and sources</h2>
          <p className="mt-2 text-sm leading-6 text-slate-500">Open an event page for its publication date, original-source citation and all available asset horizons.</p>
          <ul className="mt-5 grid gap-3 sm:grid-cols-2">
            {data.overview.citations.slice(0, 12).map((citation) => <li key={citation.eventId}><Link className="block rounded-xl border border-white/10 bg-slate-900/35 p-4 text-sm leading-6 text-slate-300 hover:border-emerald-400/35 hover:text-white" href={citation.href}>{citation.title}</Link></li>)}
          </ul>
        </section>

        <nav aria-label="Continue researching" className="mt-12 flex flex-col gap-3 border-t border-white/10 pt-8 sm:flex-row">
          <Link className="inline-flex min-h-11 items-center justify-center rounded-xl bg-emerald-400 px-4 text-sm font-bold text-slate-950" href="/events">Search all events</Link>
          <Link className="inline-flex min-h-11 items-center justify-center rounded-xl border border-white/15 px-4 text-sm font-bold text-slate-200" href="/ai">Ask AI Research</Link>
        </nav>
      </div>
    </main>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="rounded-xl border border-white/10 bg-slate-900/45 p-3"><dt className="text-xs text-slate-500">{label}</dt><dd className="mt-1 font-mono font-semibold text-slate-200">{value}</dd></div>;
}
