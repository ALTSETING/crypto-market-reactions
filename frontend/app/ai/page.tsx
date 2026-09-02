import type { Metadata } from "next";
import Link from "next/link";

import { AiSearch } from "@/components/ai-search";
import { SeoJsonLd } from "@/components/seo-json-ld";
import { AI_DESCRIPTION, AI_TITLE, buildWebPageStructuredData, SITE_NAME, siteUrl } from "@/lib/seo";

export const metadata: Metadata = {
  title: { absolute: AI_TITLE },
  description: AI_DESCRIPTION,
  alternates: { canonical: siteUrl("/ai") },
  openGraph: { title: AI_TITLE, description: AI_DESCRIPTION, url: siteUrl("/ai"), type: "website", siteName: SITE_NAME },
  twitter: { card: "summary", title: AI_TITLE, description: AI_DESCRIPTION },
};

export default function AiResearchPage() {
  return (
    <main className="min-h-screen overflow-hidden">
      <SeoJsonLd data={buildWebPageStructuredData({
        name: AI_TITLE,
        description: AI_DESCRIPTION,
        path: "/ai",
        breadcrumbs: [{ name: "Home", path: "/" }, { name: "AI Research", path: "/ai" }],
        about: ["Bitcoin", "Ethereum", "Solana", "Reaction V2"],
      })} />
      <div className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-[600px] bg-[radial-gradient(circle_at_30%_0%,rgba(16,185,129,0.14),transparent_40%),radial-gradient(circle_at_80%_15%,rgba(56,189,248,0.08),transparent_32%)]" />
      <div className="mx-auto w-full min-w-0 max-w-4xl px-4 pb-[max(3.5rem,env(safe-area-inset-bottom))] pt-[calc(6rem+env(safe-area-inset-top))] sm:px-6 sm:pt-[calc(7rem+env(safe-area-inset-top))]">
        <header className="text-center">
          <p className="text-xs font-bold uppercase tracking-[0.22em] text-emerald-400">AI Research</p>
          <h1 className="mt-4 break-words text-balance text-3xl font-semibold tracking-[-0.04em] text-white min-[390px]:text-4xl sm:text-6xl">Ask Crypto Market History</h1>
          <p className="mx-auto mt-4 max-w-2xl text-pretty text-base leading-7 text-slate-400 sm:text-lg">Ask how BTC, ETH or SOL reacted when similar events happened before. Historical statistics use Reaction V2 and linked archive evidence.</p>
        </header>
        <AiSearch />
        <aside className="mt-8 rounded-2xl border border-white/10 bg-slate-900/35 p-5 text-sm leading-6 text-slate-500">
          AI Research separates general explanations from historical database evidence and does not claim access to live market data. You can also <Link className="font-semibold text-emerald-300 hover:text-emerald-200" href="/events">browse the event archive</Link> directly.
        </aside>
      </div>
    </main>
  );
}
