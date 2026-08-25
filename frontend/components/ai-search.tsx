"use client";

import { FormEvent, useState } from "react";

import type { AiSearchErrorBody, AiSearchSuccess } from "@/types/ai-search";

const EXAMPLES = [
  "How did ETH react to ETF news?",
  "Biggest SOL drops after news media at 1h",
  "BTC reaction to SEC actions",
  "How many positive ETH events were there in 2023?",
] as const;
const QUICK_FILTERS = ["BTC", "ETH", "SOL", "ETF", "SEC", "Macro"] as const;

type State =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "success"; data: AiSearchSuccess }
  | { kind: "clarification"; message: string }
  | { kind: "error"; message: string };

export function AiSearch() {
  const [question, setQuestion] = useState("");
  const [submittedQuestion, setSubmittedQuestion] = useState("");
  const [state, setState] = useState<State>({ kind: "idle" });

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmittedQuestion(question.trim());
    setState({ kind: "loading" });
    try {
      const response = await fetch("/api/ai-search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });
      const body = await response.json() as AiSearchSuccess | AiSearchErrorBody;
      if (!response.ok || body.status !== "ok") {
        if (body.status !== "ok" && body.status === "clarification") {
          setState({ kind: "clarification", message: body.message });
        } else {
          setState({ kind: "error", message: body.status === "ok" ? "AI Search request failed." : body.message });
        }
        return;
      }
      setState({ kind: "success", data: body });
    } catch {
      setState({ kind: "error", message: "AI Search is unavailable. Please try again." });
    }
  }

  return (
    <section className="mt-10 min-w-0 max-w-full rounded-3xl border border-emerald-400/20 bg-slate-900/45 p-5 shadow-[0_24px_80px_rgba(2,6,23,0.18)] sm:p-7" aria-label="AI Research search">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="text-xl font-semibold text-white">Ask a question</h2>
          <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-400">English and Ukrainian supported. Every number is calculated from historical data.</p>
        </div>
        <span className="w-fit rounded-full border border-emerald-400/20 bg-emerald-400/10 px-3 py-1 text-xs font-semibold text-emerald-300">Based on Reaction V2</span>
      </div>

      <form className="mt-5" onSubmit={submit}>
        <label className="sr-only" htmlFor="ai-search-question">Historical market question</label>
        <div className="flex flex-col gap-3 sm:flex-row">
          <input
            className="min-h-12 min-w-0 flex-1 rounded-xl border border-white/15 bg-slate-950/55 px-4 text-sm text-white outline-none placeholder:text-slate-600 focus:border-emerald-400/50"
            id="ai-search-question"
            maxLength={500}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="Ask about historical BTC, ETH, or SOL reactions…"
            value={question}
          />
          <button className="min-h-12 rounded-xl bg-emerald-400 px-5 text-sm font-bold text-slate-950 disabled:cursor-not-allowed disabled:opacity-50" disabled={state.kind === "loading" || question.trim().length < 3} type="submit">
            {state.kind === "loading" ? "Analyzing…" : "Analyze"}
          </button>
        </div>
      </form>

      {state.kind === "idle" && <>
        <div className="mt-3 flex flex-wrap gap-2" aria-label="Quick filters">
          {QUICK_FILTERS.map((filter) => <button className="rounded-full border border-white/10 px-3 py-1.5 text-xs text-slate-400 hover:text-white" key={filter} onClick={() => setQuestion((value) => `${value}${value ? " " : ""}${filter}`)} type="button">{filter}</button>)}
        </div>
        <div className="mt-3 grid gap-2 sm:grid-cols-2" aria-label="Example questions">
          {EXAMPLES.map((example) => (
            <button className="min-w-0 break-words rounded-lg border border-white/10 bg-white/[0.035] px-3 py-2 text-left text-xs leading-5 text-slate-400 hover:border-white/20 hover:text-white" key={example} onClick={() => setQuestion(example)} type="button">{example}</button>
          ))}
        </div>
      </>}

      <div aria-live="polite" className="mt-5">
        {state.kind === "idle" && <p className="text-sm text-slate-500">Ask a specific historical question to begin.</p>}
        {state.kind !== "idle" && submittedQuestion && <p className="mb-3 text-sm text-slate-500"><span className="font-medium text-slate-300">You:</span> {submittedQuestion}</p>}
        {state.kind === "loading" && <div className="h-28 animate-pulse rounded-2xl bg-white/[0.035]" />}
        {state.kind === "clarification" && <p className="rounded-xl border border-sky-200/20 bg-sky-200/5 p-4 text-sm text-sky-200"><span className="font-semibold">Please clarify:</span> {state.message}</p>}
        {state.kind === "error" && <p className="rounded-xl border border-rose-300/20 bg-rose-300/5 p-4 text-sm text-rose-200">{state.message}</p>}
        {state.kind === "success" && <AiResult data={state.data} />}
      </div>
    </section>
  );
}

function AiResult({ data }: { data: AiSearchSuccess }) {
  const formatPercent = (value: number | null) => value === null ? "—" : `${value > 0 ? "+" : ""}${value.toFixed(2)}%`;
  const metricLabel = data.result.kind === "count" ? "Count" : data.result.kind === "ranking" ? "Reaction ranking" : data.result.kind === "multi_horizon" ? "Reaction overview" : data.intent.metric === "mean" ? "Average reaction" : data.intent.metric === "median" ? "Median reaction" : "Historical events";
  const chips = [data.intent.asset, data.intent.horizon, data.intent.sourceClass, data.intent.category].filter(Boolean);
  const sampleSize = data.result.kind === "search"
    ? data.result.matched
    : data.result.kind === "comparison"
      ? data.result.left.sampleSize + data.result.right.sampleSize
      : data.result.kind === "multi_horizon"
        ? Math.max(...data.result.rows.map((row) => row.sampleSize))
        : data.result.sampleSize;
  return (
    <div className="rounded-2xl border border-white/10 bg-slate-950/45 p-4 sm:p-5">
      <div className="flex flex-wrap gap-2">
        {chips.map((chip) => <span className="rounded-full bg-white/5 px-2.5 py-1 font-mono text-xs text-slate-400" key={chip}>{chip}</span>)}
      </div>
      <p className="mt-3 text-base font-semibold leading-7 text-white">{data.answer}</p>
      {data.answer === "No matching historical events found." && <p className="mt-1 text-sm text-slate-500">Try a broader topic or date range.</p>}
      <dl className="mt-3 grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
        <div><dt className="text-slate-500">Asset</dt><dd className="text-slate-200">{data.intent.asset ?? "All"}</dd></div>
        <div><dt className="text-slate-500">Horizon</dt><dd className="text-slate-200">{data.intent.horizon ?? "All horizons"}</dd></div>
        <div><dt className="text-slate-500">Metric</dt><dd className="text-slate-200">{metricLabel}</dd></div>
        <div><dt className="text-slate-500">Sample size</dt><dd className="text-slate-200">{sampleSize}</dd></div>
      </dl>
      {data.result.kind === "multi_horizon" && sampleSize > 0 && (
        <div className="mt-4 overflow-x-auto rounded-lg border border-white/10 text-sm">
          <div className="grid min-w-[540px] grid-cols-5 bg-white/[0.04] px-3 py-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
            <span>Horizon</span><span className="text-right">Mean</span><span className="text-right">Median</span><span className="text-right">Positive</span><span className="text-right">Sample</span>
          </div>
          {data.result.rows.map((row) => (
            <div className="grid min-w-[540px] grid-cols-5 border-t border-white/10 px-3 py-2" key={row.horizon}>
              <span className="font-medium text-slate-200">{row.horizon}</span>
              <span className="text-right text-white">{formatPercent(row.mean)}</span>
              <span className="text-right text-white">{formatPercent(row.median)}</span>
              <span className="text-right text-white">{row.positivePercent === null ? "—" : `${row.positivePercent.toFixed(1)}%`}</span>
              <span className="text-right text-slate-500">{row.sampleSize}</span>
            </div>
          ))}
        </div>
      )}
      {data.calculation && <p className="mt-2 text-sm leading-6 text-slate-400"><span className="font-semibold text-slate-300">Summary:</span> {data.calculation}</p>}
      {data.result.kind === "ranking" && data.result.items.length > 0 && (
        <ol className="mt-4 grid gap-2">
          {data.result.items.map((item, index) => (
            <li className="rounded-lg border border-white/10 px-3 py-2" key={item.eventId}>
              <a className="text-sm text-sky-200 hover:text-white" href={item.href}>{index + 1}. {item.title}</a>
              <p className="mt-1 text-sm font-semibold text-white">{formatPercent(item.reaction)}</p>
            </li>
          ))}
        </ol>
      )}
      {data.citations.length > 0 ? (
        <ul className="mt-4 grid gap-2 sm:grid-cols-2">
          {data.citations.map((citation) => (
            <li key={citation.eventId}>
              <a className="block rounded-lg border border-white/10 px-3 py-2 text-sm text-sky-200 hover:border-white/20" href={citation.href}>{citation.title}</a>
            </li>
          ))}
        </ul>
      ) : null}
      <p className="mt-4 text-xs text-slate-500">{data.basedOn}. {data.disclaimer}</p>
    </div>
  );
}
