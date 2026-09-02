import type { Metadata } from "next";
import { unstable_cache } from "next/cache";
import Link from "next/link";
import { notFound } from "next/navigation";
import { cache } from "react";

import { ReactionTable } from "@/components/reaction-table";
import { SeoJsonLd } from "@/components/seo-json-ld";
import { SourceTypeBadge } from "@/components/source-type-badge";
import { matchesTopic } from "@/lib/ai-search/topic-matcher";
import { getEventBySlug } from "@/lib/data/events";
import { formatDate, formatImportance, safeExternalUrl } from "@/lib/format";
import {
  buildEventSeoDescription,
  buildEventSeoTitle,
  buildWebPageStructuredData,
  SITE_NAME,
  siteUrl,
} from "@/lib/seo";
import { SEO_TOPIC_LANDINGS } from "@/lib/seo-topics";

export const revalidate = 3_600;

const getCachedEvent = unstable_cache(getEventBySlug, ["public-event-by-slug-v9073"], {
  revalidate,
  tags: ["public-events"],
});
const getEvent = cache(getCachedEvent);

interface EventPageProps {
  params: Promise<{ slug: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export async function generateMetadata({ params, searchParams }: EventPageProps): Promise<Metadata> {
  const { slug } = await params;
  const event = await getEvent(slug);
  if (!event) {
    return {
      title: { absolute: `Event not found | ${SITE_NAME}` },
      robots: { index: false, follow: false },
    };
  }

  const title = buildEventSeoTitle(event);
  const description = buildEventSeoDescription(event);
  const canonical = siteUrl(`/events/${event.slug}`);
  const hasQueryParameters = Object.keys(await searchParams).length > 0;

  return {
    title: { absolute: title },
    description,
    alternates: { canonical },
    robots: { index: !hasQueryParameters, follow: true },
    openGraph: {
      title,
      description,
      url: canonical,
      type: "website",
      siteName: SITE_NAME,
    },
    twitter: {
      card: "summary",
      title,
      description,
    },
  };
}

export default async function EventPage({ params }: EventPageProps) {
  const { slug } = await params;
  const event = await getEvent(slug);
  if (!event) notFound();

  const sourceUrl = safeExternalUrl(event.source_url);
  const relatedTopics = SEO_TOPIC_LANDINGS.filter((topic) =>
    (!topic.asset || event.related_assets.includes(topic.asset)) && matchesTopic(event, topic.topic)
  ).slice(0, 3);

  return (
    <main className="min-h-screen">
      <SeoJsonLd data={buildWebPageStructuredData({
        name: event.title,
        description: buildEventSeoDescription(event),
        path: `/events/${event.slug}`,
        breadcrumbs: [{ name: "Home", path: "/" }, { name: "Events", path: "/events" }, { name: event.title, path: `/events/${event.slug}` }],
        datePublished: event.published_at,
        citation: sourceUrl,
        about: [...event.related_assets, event.category.replaceAll("_", " "), "Reaction V2"],
      })} />
      <div className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-96 bg-[radial-gradient(circle_at_50%_0%,rgba(16,185,129,0.1),transparent_45%)]" />
      <div className="mx-auto w-full max-w-5xl px-4 pb-8 pt-20 sm:px-6 sm:py-12 lg:px-8">
        <Link className="inline-flex rounded-lg py-2 text-sm font-semibold text-slate-400 outline-none transition hover:text-white focus-visible:ring-2 focus-visible:ring-emerald-300" href="/events">
          <span aria-hidden="true">←</span>&nbsp; Back to events
        </Link>

        <article className="mt-6">
          <header className="min-w-0 overflow-hidden rounded-3xl border border-white/10 bg-slate-900/55 p-5 shadow-2xl shadow-black/15 sm:p-9">
            <div className="flex flex-wrap items-center gap-2 text-xs font-semibold text-slate-400">
              <time dateTime={event.published_at}>{formatDate(event.published_at, true)} UTC</time>
              <span aria-hidden="true">•</span>
              <span className="uppercase tracking-[0.14em] text-slate-300">{event.source}</span>
              <SourceTypeBadge sourceType={event.source_type} />
            </div>
            <h1 className="mt-5 break-words text-balance text-2xl font-semibold leading-tight tracking-[-0.03em] text-white min-[390px]:text-3xl sm:text-5xl">
              {event.title}
            </h1>

            <div className="mt-6 flex flex-wrap gap-2">
              {event.primary_asset && (
                <span className="rounded-lg border border-sky-400/25 bg-sky-400/8 px-3 py-1.5 text-xs font-bold text-sky-200">
                  Primary {event.primary_asset}
                </span>
              )}
              {event.related_assets.map((asset) => (
                <span className="rounded-lg border border-emerald-400/20 bg-emerald-400/8 px-3 py-1.5 text-xs font-bold text-emerald-200" key={asset}>
                  {asset}
                </span>
              ))}
              <span className="rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs capitalize text-slate-300">
                {event.category.replaceAll("_", " ")}
              </span>
              {event.sentiment && (
                <span className="rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs capitalize text-slate-300">
                  {event.sentiment}
                </span>
              )}
              {event.importance !== null && (
                <span className="rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-slate-300">
                  Importance {formatImportance(event.importance)}
                </span>
              )}
            </div>

            {sourceUrl && (
              <a
                className="mt-8 inline-flex min-h-11 w-full items-center justify-center rounded-xl bg-slate-100 px-4 py-2.5 text-center text-sm font-bold text-slate-950 outline-none transition hover:bg-white focus-visible:ring-2 focus-visible:ring-emerald-300 sm:w-auto"
                href={sourceUrl}
                rel="noopener noreferrer"
                target="_blank"
              >
                Read original source <span aria-hidden="true">↗</span>
              </a>
            )}
          </header>

          <section className="mt-8 rounded-2xl border border-white/10 bg-slate-900/35 p-5 sm:p-6" aria-labelledby="event-summary-title">
            <h2 className="text-lg font-semibold text-white" id="event-summary-title">Event summary</h2>
            <p className="mt-2 text-sm leading-6 text-slate-400">
              {event.source} published this {event.category.replaceAll("_", " ")} event on {formatDate(event.published_at, true)} UTC. The archive associates it with {event.related_assets.length ? event.related_assets.join(", ") : "the broader crypto market"}; the tables below report observed post-publication returns without asserting causality.
            </p>
          </section>

          <section className="mt-10" aria-labelledby="reactions-title">
            <div className="mb-5">
              <p className="text-xs font-bold uppercase tracking-[0.2em] text-emerald-400">Historical market reactions</p>
              <div className="mt-2 flex flex-wrap items-center gap-3">
                <h2 className="text-2xl font-semibold text-white sm:text-3xl" id="reactions-title">
                  Price reactions
                </h2>
                <span
                  aria-label="Reaction V2: historical returns calculated with the current methodology from the recorded publication timestamp; this does not prove the event caused the price move."
                  className="inline-flex items-center gap-1.5 rounded-full border border-emerald-400/25 bg-emerald-400/8 px-3 py-1 text-xs font-bold text-emerald-200"
                  role="img"
                  title="Calculated with the current methodology from the recorded publication timestamp. This is an observed association, not proof that the event caused the price move."
                >
                  Reaction V2 <span aria-hidden="true">?</span>
                </span>
              </div>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-500">
                Historical percentage returns from the recorded publication timestamp. Missing values remain intentionally blank; these observations do not establish causality.
              </p>
            </div>
            <ReactionTable event={event} />
          </section>

          <section className="mt-8 grid gap-4 rounded-2xl border border-white/10 bg-slate-900/45 p-5 text-sm sm:grid-cols-2 sm:p-6" aria-labelledby="method-title">
            <div>
              <h2 className="font-semibold text-white" id="method-title">Methodology</h2>
              <p className="mt-2 leading-6 text-slate-400">
                Reaction V2 uses the current documented publication-time methodology. Alternative research alignments are not displayed as production data.
              </p>
            </div>
            <dl className="grid content-start gap-3">
              {event.primary_asset && (
                <div className="flex flex-wrap justify-between gap-2"><dt className="text-slate-500">Primary asset</dt><dd className="font-semibold text-slate-200">{event.primary_asset}</dd></div>
              )}
              {event.sentiment_score !== null && (
                <div className="flex flex-wrap justify-between gap-2"><dt className="text-slate-500">Sentiment score</dt><dd className="font-mono text-slate-200">{event.sentiment_score.toFixed(2)}</dd></div>
              )}
              <div className="flex flex-wrap justify-between gap-2"><dt className="text-slate-500">Value unit</dt><dd className="text-slate-200">Percentage return</dd></div>
              <div className="flex flex-wrap justify-between gap-2"><dt className="text-slate-500">Reaction version</dt><dd className="text-slate-200">Reaction V2</dd></div>
              <div className="flex flex-wrap justify-between gap-2"><dt className="text-slate-500">Publication date</dt><dd className="text-slate-200">{formatDate(event.published_at, true)} UTC</dd></div>
              <div className="flex flex-wrap justify-between gap-2"><dt className="text-slate-500">Source</dt><dd className="text-slate-200">{event.source}</dd></div>
              <div className="flex flex-wrap justify-between gap-2"><dt className="text-slate-500">Related assets</dt><dd className="text-slate-200">{event.related_assets.length ? event.related_assets.join(", ") : "None assigned"}</dd></div>
              <div className="flex flex-wrap justify-between gap-2"><dt className="text-slate-500">Data availability</dt><dd className="text-slate-200">Missing horizons remain blank</dd></div>
            </dl>
          </section>

          <nav aria-label="Explore related events" className="mt-8 rounded-2xl border border-white/10 bg-slate-900/35 p-5 sm:p-6">
            <h2 className="text-sm font-semibold text-white">Explore the archive</h2>
            <div className="mt-3 grid gap-2 min-[420px]:flex min-[420px]:flex-wrap">
              <Link className="min-h-11 rounded-xl border border-white/10 px-3 py-2.5 text-center text-sm text-slate-300 outline-none hover:border-white/25 hover:text-white focus-visible:ring-2 focus-visible:ring-emerald-300" href="/events">
                All events
              </Link>
              {event.related_assets.map((asset) => (
                <Link className="min-h-11 rounded-xl border border-emerald-400/20 px-3 py-2.5 text-center text-sm text-emerald-200 outline-none hover:border-emerald-300/50 focus-visible:ring-2 focus-visible:ring-emerald-300" href={`/events?asset=${asset}`} key={asset}>
                  {asset} events
                </Link>
              ))}
              <Link className="min-h-11 rounded-xl border border-white/10 px-3 py-2.5 text-center text-sm text-slate-300 outline-none hover:border-white/25 hover:text-white focus-visible:ring-2 focus-visible:ring-emerald-300" href={`/events?source=${encodeURIComponent(event.source)}`}>
                More from {event.source}
              </Link>
              {relatedTopics.map((topic) => (
                <Link className="min-h-11 rounded-xl border border-sky-400/20 px-3 py-2.5 text-center text-sm text-sky-200 outline-none hover:border-sky-300/50 focus-visible:ring-2 focus-visible:ring-emerald-300" href={`/topics/${topic.slug}`} key={topic.slug}>
                  {topic.name}
                </Link>
              ))}
            </div>
          </nav>
        </article>
      </div>
    </main>
  );
}
