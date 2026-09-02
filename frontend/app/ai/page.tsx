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
      <div className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-[420px] bg-[radial-gradient(circle_at_30%_0%,rgba(16,185,129,0.09),transparent_44%),radial-gradient(circle_at_80%_15%,rgba(56,189,248,0.04),transparent_36%)]" />
      <div className="mx-auto w-full min-w-0 max-w-5xl px-4 pb-[max(3.5rem,env(safe-area-inset-bottom))] pt-[calc(4.75rem+env(safe-area-inset-top))] sm:px-6 sm:pt-[calc(6.5rem+env(safe-area-inset-top))]">
        <header className="text-center">
          <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-emerald-400">AI Research</p>
          <h1 className="mt-2 break-words text-balance text-[1.75rem] font-semibold leading-tight tracking-[-0.035em] text-white min-[390px]:text-3xl sm:mt-3 sm:text-5xl">Ask Crypto Market History</h1>
          <p className="mx-auto mt-2 max-w-xl text-pretty text-sm leading-5 text-slate-400 sm:mt-3 sm:text-base sm:leading-6">Clear explanations and historical BTC, ETH and SOL reactions.</p>
        </header>
        <AiSearch />
        <aside className="mt-10 border-t border-white/8 pt-4 text-xs leading-5 text-slate-500">
          No live market data. <Link className="font-medium text-emerald-300 hover:text-emerald-200" href="/events">Browse the event archive</Link>.
        </aside>
      </div>
    </main>
  );
}
