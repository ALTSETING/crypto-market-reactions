import type { Metadata } from "next";

import { AiSearch } from "@/components/ai-search";
import { siteUrl } from "@/lib/seo";

export const metadata: Metadata = {
  title: "AI Research",
  description: "Ask how BTC, ETH, or SOL reacted when similar events happened before.",
  alternates: { canonical: siteUrl("/ai") },
};

export default function AiResearchPage() {
  return (
    <main className="min-h-screen overflow-hidden">
      <div className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-[600px] bg-[radial-gradient(circle_at_30%_0%,rgba(16,185,129,0.14),transparent_40%),radial-gradient(circle_at_80%_15%,rgba(56,189,248,0.08),transparent_32%)]" />
      <div className="mx-auto w-full max-w-4xl px-4 pb-14 pt-24 sm:px-6 sm:pt-28">
        <header className="text-center">
          <p className="text-xs font-bold uppercase tracking-[0.22em] text-emerald-400">AI Research</p>
          <h1 className="mt-4 break-words text-balance text-3xl font-semibold tracking-[-0.04em] text-white min-[390px]:text-4xl sm:text-6xl">Ask Crypto Market History</h1>
          <p className="mx-auto mt-4 max-w-2xl text-pretty text-base leading-7 text-slate-400 sm:text-lg">Ask how BTC, ETH or SOL reacted when similar events happened before.</p>
        </header>
        <AiSearch />
      </div>
    </main>
  );
}
