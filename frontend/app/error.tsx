"use client";

export default function GlobalError({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <main className="grid min-h-[70vh] place-items-center px-4">
      <div className="max-w-lg rounded-2xl border border-rose-400/20 bg-rose-400/8 p-7 text-center">
        <p className="text-sm font-semibold text-rose-100">This page could not be loaded.</p>
        <p className="mt-2 text-sm leading-6 text-rose-200/70">The event service may be temporarily unavailable. No private diagnostic details are exposed.</p>
        <button className="mt-5 rounded-xl bg-white px-4 py-2 text-sm font-bold text-slate-950 outline-none focus-visible:ring-2 focus-visible:ring-emerald-300" onClick={reset} type="button">
          Try again
        </button>
      </div>
    </main>
  );
}
