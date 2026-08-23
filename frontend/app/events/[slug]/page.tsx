import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { cache } from "react";

import { ReactionTable } from "@/components/reaction-table";
import { getEventBySlug } from "@/lib/data/events";
import { formatDate, formatImportance, safeExternalUrl } from "@/lib/format";

export const dynamic = "force-dynamic";

const getEvent = cache(getEventBySlug);

interface EventPageProps {
  params: Promise<{ slug: string }>;
}

export async function generateMetadata({ params }: EventPageProps): Promise<Metadata> {
  const { slug } = await params;
  const event = await getEvent(slug);
  if (!event) return { title: "Event not found" };
  return {
    title: `${event.title} | Crypto Market Reactions`,
    description: `Historical ${event.related_assets.join(", ")} market reactions after this ${event.source} event.`,
  };
}

export default async function EventPage({ params }: EventPageProps) {
  const { slug } = await params;
  const event = await getEvent(slug);
  if (!event) notFound();
  const sourceUrl = safeExternalUrl(event.source_url);

  return (
    <main className="min-h-screen">
      <div className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-96 bg-[radial-gradient(circle_at_50%_0%,rgba(16,185,129,0.1),transparent_45%)]" />
      <div className="mx-auto w-full max-w-5xl px-4 py-8 sm:px-6 sm:py-12 lg:px-8">
        <Link className="inline-flex rounded-lg py-2 text-sm font-semibold text-slate-400 outline-none transition hover:text-white focus-visible:ring-2 focus-visible:ring-emerald-300" href="/">
          <span aria-hidden="true">←</span>&nbsp; Back to events
        </Link>

        <article className="mt-6">
          <header className="rounded-3xl border border-white/10 bg-slate-900/55 p-6 shadow-2xl shadow-black/20 sm:p-9">
            <div className="flex flex-wrap items-center gap-2 text-xs font-semibold text-slate-400">
              <time dateTime={event.published_at}>{formatDate(event.published_at, true)} UTC</time>
              <span aria-hidden="true">•</span>
              <span className="uppercase tracking-[0.14em] text-slate-300">{event.source}</span>
            </div>
            <h1 className="mt-5 text-balance text-3xl font-semibold leading-tight tracking-[-0.03em] text-white sm:text-5xl">
              {event.title}
            </h1>

            <div className="mt-6 flex flex-wrap gap-2">
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
                className="mt-8 inline-flex items-center rounded-xl bg-slate-100 px-4 py-2.5 text-sm font-bold text-slate-950 outline-none transition hover:bg-white focus-visible:ring-2 focus-visible:ring-emerald-300"
                href={sourceUrl}
                rel="noopener noreferrer"
                target="_blank"
              >
                Read original source <span aria-hidden="true">↗</span>
              </a>
            )}
          </header>

          <section className="mt-10" aria-labelledby="reactions-title">
            <div className="mb-5">
              <p className="text-xs font-bold uppercase tracking-[0.2em] text-emerald-400">Verified market data</p>
              <h2 className="mt-2 text-2xl font-semibold text-white sm:text-3xl" id="reactions-title">
                Price reactions
              </h2>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-500">
                Percentage returns from the documented reference price around the publication timestamp. Missing values remain intentionally blank.
              </p>
            </div>
            <ReactionTable event={event} />
          </section>

          <section className="mt-8 grid gap-4 rounded-2xl border border-white/10 bg-slate-900/45 p-5 text-sm sm:grid-cols-2 sm:p-6" aria-labelledby="method-title">
            <div>
              <h2 className="font-semibold text-white" id="method-title">Methodology</h2>
              <p className="mt-2 break-words leading-6 text-slate-400">{event.reaction_methodology}</p>
            </div>
            <dl className="grid content-start gap-3">
              {event.primary_asset && (
                <div className="flex justify-between gap-4"><dt className="text-slate-500">Primary asset</dt><dd className="font-semibold text-slate-200">{event.primary_asset}</dd></div>
              )}
              {event.sentiment_score !== null && (
                <div className="flex justify-between gap-4"><dt className="text-slate-500">Sentiment score</dt><dd className="font-mono text-slate-200">{event.sentiment_score.toFixed(2)}</dd></div>
              )}
              <div className="flex justify-between gap-4"><dt className="text-slate-500">Value unit</dt><dd className="text-slate-200">Percentage return</dd></div>
            </dl>
          </section>
        </article>
      </div>
    </main>
  );
}
