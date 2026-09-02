import type { Metadata } from "next";
import { unstable_cache } from "next/cache";
import Link from "next/link";
import { redirect } from "next/navigation";

import { SeoJsonLd } from "@/components/seo-json-ld";
import { getDatasetStats } from "@/lib/data/events";
import { buildWebPageStructuredData, buildWebsiteStructuredData, HOME_DESCRIPTION, HOME_TITLE, SITE_NAME, siteUrl } from "@/lib/seo";
import { SEO_TOPIC_LANDINGS } from "@/lib/seo-topics";

export const dynamic = "force-dynamic";

const getCachedDatasetStats = unstable_cache(getDatasetStats, ["public-dataset-stats-v9073"], {
  revalidate: 3_600,
  tags: ["public-events"],
});

interface HomePageProps {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export const metadata: Metadata = {
  title: { absolute: HOME_TITLE },
  description: HOME_DESCRIPTION,
  alternates: { canonical: siteUrl("/") },
  robots: { index: true, follow: true },
  openGraph: { title: HOME_TITLE, description: HOME_DESCRIPTION, url: siteUrl("/"), type: "website", siteName: SITE_NAME },
  twitter: { card: "summary", title: HOME_TITLE, description: HOME_DESCRIPTION },
};

function appendSearchValue(target: URLSearchParams, key: string, value: string | string[] | undefined) {
  if (Array.isArray(value)) value.forEach((item) => target.append(key, item));
  else if (value !== undefined) target.append(key, value);
}

export default async function HomePage({ searchParams }: HomePageProps) {
  const query = await searchParams;
  if (Object.keys(query).length > 0) {
    const target = new URLSearchParams();
    Object.entries(query).forEach(([key, value]) => appendSearchValue(target, key, value));
    redirect(`/events?${target.toString()}`);
  }
  const stats = await getCachedDatasetStats();
  const eventCount = stats.events.toLocaleString("en-US");
  return (
    <main className="min-h-screen overflow-hidden">
      <SeoJsonLd data={[buildWebsiteStructuredData(), buildWebPageStructuredData({
        name: HOME_TITLE,
        description: HOME_DESCRIPTION,
        path: "/",
        breadcrumbs: [{ name: "Home", path: "/" }],
      })]} />
      <div className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-[620px] bg-[radial-gradient(circle_at_25%_0%,rgba(16,185,129,0.14),transparent_40%),radial-gradient(circle_at_80%_15%,rgba(56,189,248,0.08),transparent_32%)]" />
      <div className="mx-auto w-full max-w-6xl px-4 pb-16 pt-24 sm:px-6 sm:pt-32 lg:px-8">
        <header className="max-w-4xl">
          <p className="text-xs font-bold uppercase tracking-[0.24em] text-emerald-400">Historical crypto market intelligence</p>
          <h1 className="mt-5 text-balance text-4xl font-semibold tracking-[-0.045em] text-white sm:text-6xl">
            Crypto Market Reactions <span className="text-slate-400">after major events</span>
          </h1>
          <p className="mt-6 max-w-3xl text-pretty text-base leading-7 text-slate-400 sm:text-lg">
            See how Bitcoin, Ethereum and Solana moved after ETFs, SEC actions, hacks, institutional flows and other archived crypto events. Every displayed return comes from historical Reaction V2 data.
          </p>
          <div className="mt-8 flex flex-col gap-3 sm:flex-row">
            <Link className="inline-flex min-h-12 items-center justify-center rounded-xl bg-emerald-400 px-5 text-sm font-bold text-slate-950 hover:bg-emerald-300" href="/events">Explore {eventCount} events</Link>
            <Link className="inline-flex min-h-12 items-center justify-center rounded-xl border border-white/15 px-5 text-sm font-bold text-slate-200 hover:border-white/25 hover:text-white" href="/ai">Ask AI Research</Link>
          </div>
        </header>

        <section className="mt-16" aria-labelledby="topics-title">
          <p className="text-xs font-bold uppercase tracking-[0.2em] text-emerald-400">Research topics</p>
          <h2 className="mt-2 text-2xl font-semibold text-white sm:text-3xl" id="topics-title">Browse historical event themes</h2>
          <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-500">Topic pages use explicit headline matching and deterministic statistics. They do not infer events that are absent from the archive.</p>
          <div className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {SEO_TOPIC_LANDINGS.map((topic) => (
              <Link className="rounded-2xl border border-white/10 bg-slate-900/45 p-5 outline-none transition hover:border-emerald-400/35 focus-visible:ring-2 focus-visible:ring-emerald-300" href={`/topics/${topic.slug}`} key={topic.slug}>
                <h3 className="font-semibold text-white">{topic.name}</h3>
                <p className="mt-2 text-sm leading-6 text-slate-500">{topic.description}</p>
              </Link>
            ))}
          </div>
        </section>

        <section className="mt-12 grid gap-4 md:grid-cols-3" aria-label="Dataset methodology">
          <Info title="Reaction V2">Historical percentage returns at 1m, 5m, 15m, 1h, 4h and 24h from the recorded publication timestamp.</Info>
          <Info title={`${stats.firstYear}–${stats.lastYear} archive`}>Coverage is uneven by year. Event counts describe this database and do not claim a complete news record.</Info>
          <Info title="Evidence, not causality">Source links and event dates are shown with the observations. Price movement after an event does not prove that event caused it.</Info>
        </section>
      </div>
    </main>
  );
}

function Info({ title, children }: { title: string; children: React.ReactNode }) {
  return <article className="rounded-2xl border border-white/10 bg-slate-900/35 p-5"><h2 className="font-semibold text-white">{title}</h2><p className="mt-2 text-sm leading-6 text-slate-500">{children}</p></article>;
}
