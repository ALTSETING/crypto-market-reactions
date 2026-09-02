"use client";

import { FormEvent, KeyboardEvent, useState } from "react";

import { formatPercent } from "@/lib/ai-search/format";
import { AI_TOPIC_LABELS, type AiAgentSuccess, type AiCitation, type AiHybridSuccess, type AiResearchSuccess, type AiSearchErrorBody, type AiSearchSuccess, type MultiHorizonAnalyticsResult } from "@/types/ai-search";

const EXAMPLES = [
  "What is a Bitcoin ETF?",
  "How did BTC react to ETF outflows?",
  "How did ETH react to institutional purchases?",
  "How did SOL react to hacks?",
  "На які новини ETH найчастіше реагував зростанням?",
] as const;

type State =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "success"; data: AiResearchSuccess }
  | { kind: "refusal"; message: string }
  | { kind: "error"; message: string };

export function AiSearch() {
  const [question, setQuestion] = useState("");
  const [submittedQuestion, setSubmittedQuestion] = useState("");
  const [state, setState] = useState<State>({ kind: "idle" });
  const [examplesOpen, setExamplesOpen] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedQuestion = question.trim();
    setSubmittedQuestion(trimmedQuestion);
    setState({ kind: "loading" });
    try {
      const response = await fetch("/api/ai-search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });
      const body = await response.json() as AiResearchSuccess | AiSearchErrorBody;
      if (!response.ok || body.status !== "ok") {
        if (body.status !== "ok" && body.status === "refusal") {
          setState({ kind: "refusal", message: body.message });
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

  function handleQuestionKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    if (question.trim().length >= 3 && state.kind !== "loading") event.currentTarget.form?.requestSubmit();
  }

  return (
    <section aria-label="AI Research search" className="mt-6 min-w-0 max-w-full sm:mt-9">
      <div>
        <h2 className="text-base font-semibold tracking-tight text-white">Ask a question</h2>
        <p className="mt-1 text-sm leading-5 text-slate-500">English or Ukrainian.</p>
      </div>
      <form className="mt-3 rounded-2xl border border-white/10 bg-slate-900/45 p-2 focus-within:border-emerald-400/40 focus-within:ring-4 focus-within:ring-emerald-400/[0.05]" onSubmit={submit}>
        <label className="sr-only" htmlFor="ai-search-question">Crypto research question</label>
        <textarea className="block min-h-20 w-full min-w-0 resize-y bg-transparent px-3 py-2.5 text-base leading-6 text-white outline-none placeholder:text-slate-600 sm:min-h-16" id="ai-search-question" maxLength={500} onChange={(event) => setQuestion(event.target.value)} onKeyDown={handleQuestionKeyDown} placeholder="Ask about crypto concepts or historical BTC, ETH, and SOL reactions…" rows={2} value={question} />
        <div className="flex items-center justify-between gap-3 border-t border-white/8 px-2 pt-2">
          <span className="text-[11px] leading-4 text-slate-500">AI explanations · Reaction V2 history</span>
          <button className="min-h-10 shrink-0 rounded-xl bg-emerald-400 px-4 text-sm font-semibold text-slate-950 outline-none transition hover:bg-emerald-300 active:translate-y-px focus-visible:ring-2 focus-visible:ring-emerald-200 disabled:cursor-not-allowed disabled:opacity-45" disabled={state.kind === "loading" || question.trim().length < 3} type="submit">{state.kind === "loading" ? "Analyzing…" : "Analyze"}</button>
        </div>
      </form>
      {state.kind === "idle" && <ExampleQuestions expanded={examplesOpen} onSelect={setQuestion} onToggle={() => setExamplesOpen((open) => !open)} />}
      <div aria-live="polite" className={state.kind === "idle" ? "sr-only" : "mt-7 min-w-0 max-w-full"}>
        {state.kind !== "idle" && submittedQuestion && <div className="mb-7 min-w-0"><p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">Your question</p><p className="mt-1 break-words text-sm font-medium leading-6 text-slate-300 [overflow-wrap:anywhere]">{submittedQuestion}</p></div>}
        {state.kind === "loading" && <AiLoadingState />}
        {state.kind === "refusal" && <AiMessage kind="warning" label="Request not supported" message={state.message} />}
        {state.kind === "error" && <AiMessage kind="error" label="Unable to complete request" message={state.message} />}
        {state.kind === "success" && <AiResult data={state.data} />}
      </div>
    </section>
  );
}

export function ExampleQuestions({ expanded, onSelect, onToggle }: { expanded: boolean; onSelect: (question: string) => void; onToggle: () => void }) {
  return (
    <div className="mt-3">
      <button aria-controls="ai-example-questions" aria-expanded={expanded} className="inline-flex min-h-10 items-center gap-2 rounded-lg px-1 text-sm font-medium text-slate-500 outline-none transition hover:text-white focus-visible:ring-2 focus-visible:ring-emerald-300 motion-reduce:transition-none" onClick={onToggle} type="button">
        Example questions
        <span aria-hidden="true" className={`text-xs transition-transform duration-150 motion-reduce:transition-none ${expanded ? "rotate-180" : ""}`}>⌄</span>
      </button>
      <div aria-hidden={!expanded} className={`grid transition-[grid-template-rows,opacity] duration-150 motion-reduce:transition-none ${expanded ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0"}`} id="ai-example-questions">
        <div className="min-h-0 overflow-hidden"><div className="grid gap-x-6 pb-1 pt-1 sm:grid-cols-2">
          {EXAMPLES.map((example) => <button className="min-h-11 min-w-0 break-words border-b border-white/8 py-2.5 text-left text-xs leading-5 text-slate-500 outline-none transition hover:text-white focus-visible:rounded focus-visible:ring-2 focus-visible:ring-emerald-300 [overflow-wrap:anywhere]" key={example} onClick={() => onSelect(example)} tabIndex={expanded ? 0 : -1} type="button">{example}</button>)}
        </div></div>
      </div>
    </div>
  );
}

export function AiLoadingState() {
  return <div aria-label="AI Research is analyzing" className="py-1" role="status"><div className="flex items-center gap-3 text-sm text-slate-400"><span aria-hidden="true" className="size-2 animate-pulse rounded-full bg-emerald-400 motion-reduce:animate-none" />Analyzing…</div></div>;
}

export function AiMessage({ kind, label, message }: { kind: "warning" | "error"; label: string; message: string }) {
  return <div className={`py-1 text-sm leading-6 ${kind === "error" ? "text-rose-200" : "text-amber-100"}`} role={kind === "error" ? "alert" : "status"}><p className="font-semibold">{label}</p><p className="mt-1 opacity-80">{message}</p></div>;
}

export function AiResult({ data }: { data: AiResearchSuccess }) {
  if (data.mode === "agent") return <AgentResult data={data} />;
  if (data.mode === "general") return <article aria-label="AI explanation" className="mx-auto min-w-0 max-w-[760px]"><ResultEyebrow>AI explanation</ResultEyebrow><ProseAnswer text={data.answer} /><ResultDisclaimer>{compactDisclaimer(data.language)}</ResultDisclaimer></article>;
  return <DatabaseResult data={data} />;
}

function AgentResult({ data }: { data: AiAgentSuccess }) {
  const historicalData: AiSearchSuccess | null = data.historical ? {
    status: "ok", mode: "database", modeLabel: "Historical evidence — Reaction V2", language: data.language, basedOn: data.historical.basedOn, intent: data.historical.intent, answer: data.historical.answer, calculation: data.historical.calculation, result: data.historical.result, citations: data.historical.citations,
    disclaimer: data.language === "uk" ? "Лише історичний аналіз — не фінансова порада." : "Historical analysis only — not financial advice.",
  } : null;
  return <div className="min-w-0 max-w-full"><article aria-label="AI explanation" className="mx-auto min-w-0 max-w-[760px]"><ResultEyebrow>{data.modeLabel}</ResultEyebrow><ProseAnswer text={data.answer} />{data.historicalUnavailable && <p className="mt-6 text-sm text-slate-500">{data.historicalMessage ?? "Historical evidence is temporarily unavailable."}</p>}{!historicalData && <ResultDisclaimer>{compactDisclaimer(data.language)}</ResultDisclaimer>}</article>{historicalData && <div className="mt-9 border-t border-white/10 pt-8"><DatabaseResult data={historicalData} /></div>}</div>;
}

function ProseAnswer({ text }: { text: string }) {
  const paragraphs = text.split(/\n{2,}/u).filter(Boolean);
  return <div className="mt-3 min-w-0 space-y-4 break-words text-base leading-[1.65] text-white sm:text-[17px] sm:leading-[1.7] [overflow-wrap:anywhere]">{paragraphs.map((paragraph, index) => <p className="whitespace-pre-wrap" key={`${index}-${paragraph.slice(0, 24)}`}>{paragraph}</p>)}</div>;
}

function ResultEyebrow({ children }: { children: React.ReactNode }) { return <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">{children}</p>; }
function ResultDisclaimer({ children }: { children: React.ReactNode }) { return <p className="mt-6 text-xs leading-5 text-slate-500">{children}</p>; }
function compactDisclaimer(language: "en" | "uk"): string { return language === "uk" ? "Не фінансова порада." : "Not financial advice."; }

function DatabaseResult({ data }: { data: AiSearchSuccess | AiHybridSuccess }) {
  const context = [data.intent.asset, data.intent.topic ? AI_TOPIC_LABELS[data.intent.topic] : null, data.intent.horizon ?? "All horizons"].filter((item): item is string => Boolean(item));
  const sampleSize = data.result.kind === "search" ? data.result.matched : data.result.kind === "comparison" ? data.result.left.sampleSize + data.result.right.sampleSize : data.result.kind === "multi_horizon" ? Math.max(0, ...data.result.rows.map((row) => row.sampleSize)) : data.result.sampleSize;
  const requestedRow = data.result.kind === "multi_horizon" ? data.result.rows.find((row) => row.horizon === (data.intent.horizon ?? "24h")) : null;
  const observationSummary = data.result.topicFilter ? `${data.result.topicFilter.independentEventCount} independent events · ${data.result.topicFilter.matchedSampleSize} matched articles` : `${sampleSize} observations`;

  return (
    <section aria-label="Historical evidence" className="min-w-0 max-w-full">
      {data.mode === "hybrid" && <article aria-label="General explanation" className="mx-auto max-w-[760px] pb-8"><ResultEyebrow>General explanation</ResultEyebrow><ProseAnswer text={data.generalExplanation} /></article>}
      <div className={data.mode === "hybrid" ? "border-t border-white/10 pt-8" : undefined}>
        <div className="flex flex-wrap items-center gap-2"><h3 className="text-lg font-semibold tracking-tight text-white">Historical evidence</h3><span className="rounded-full bg-emerald-400/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-emerald-300">Reaction V2</span></div>
        <p className="mt-2 break-words text-sm leading-6 text-slate-500 [overflow-wrap:anywhere]">{observationSummary}{context.length > 0 ? ` · ${context.join(" · ")}` : ""}</p>
        <p className="mt-4 max-w-[760px] break-words text-base font-medium leading-7 text-white [overflow-wrap:anywhere]">{data.answer}</p>
        {data.answer === "No matching historical events found." && <p className="mt-1 text-sm text-slate-500">Try a broader topic or date range.</p>}
        {requestedRow && <dl className="mt-5 flex flex-wrap gap-x-7 gap-y-3 rounded-xl bg-white/[0.035] px-4 py-3.5 text-sm"><InlineMetric label={`Median ${requestedRow.horizon}`} value={formatPercent(requestedRow.median)} tone={reactionTone(requestedRow.median)} /><InlineMetric label="Positive" value={formatPercent(requestedRow.positivePercent, false, 2)} /><InlineMetric label="Sample" value={String(requestedRow.sampleSize)} /></dl>}
        {data.result.topicFilter?.entityConcentrationWarning && <p className="mt-4 text-xs leading-5 text-amber-100">One entity represents {data.result.topicFilter.largestEntityShare.toFixed(1)}% of independent events.</p>}
        {sampleSize > 0 && sampleSize < 10 && <p className="mt-4 text-xs leading-5 text-amber-100">{sampleSize < 5 ? "Very small sample; interpret cautiously." : "Small sample; interpret cautiously."}</p>}
        {data.result.kind === "multi_horizon" && sampleSize > 0 && <HistoricalTable rows={data.result.rows} />}
        {data.result.kind === "ranking" && data.result.items.length > 0 && <ol className="mt-5 divide-y divide-white/8 border-y border-white/8">{data.result.items.map((item, index) => <li className="grid min-w-0 gap-1 py-3 sm:grid-cols-[1fr_auto] sm:items-center sm:gap-5" key={item.eventId}><a className="min-w-0 break-words text-sm text-sky-200 outline-none hover:text-white focus-visible:rounded focus-visible:ring-2 focus-visible:ring-emerald-300 [overflow-wrap:anywhere]" href={item.href}>{index + 1}. {item.title}</a><span className={`font-mono text-sm font-semibold tabular-nums ${reactionTone(item.reaction)}`}>{formatPercent(item.reaction)}</span></li>)}</ol>}
        {data.citations.length > 0 && <CitationList citations={data.citations} />}
        <p className="mt-7 text-xs leading-5 text-slate-500">{data.disclaimer}</p>
      </div>
    </section>
  );
}

function InlineMetric({ label, tone = "text-white", value }: { label: string; tone?: string; value: string }) { return <div className="min-w-0"><dt className="text-[10px] font-semibold uppercase tracking-[0.1em] text-slate-600">{label}</dt><dd className={`mt-0.5 font-mono font-medium tabular-nums ${tone}`}>{value}</dd></div>; }

export function CitationList({ citations, initialExpanded = false }: { citations: AiCitation[]; initialExpanded?: boolean }) {
  const [expanded, setExpanded] = useState(initialExpanded);
  const visibleCitations = expanded ? citations : citations.slice(0, 5);
  const remaining = Math.max(0, citations.length - visibleCitations.length);
  return <section aria-labelledby="sources-heading" className="mt-8"><h4 className="text-sm font-semibold text-white" id="sources-heading">Sources</h4><ol className="mt-3 space-y-1">{visibleCitations.map((citation, index) => <li className="grid min-w-0 grid-cols-[1.5rem_1fr] gap-2 py-1.5 text-sm" key={citation.eventId}><span aria-hidden="true" className="font-mono text-xs leading-6 text-slate-600">{index + 1}</span><div className="min-w-0"><a className="inline-flex min-h-10 break-words py-1 leading-5 text-sky-200 outline-none hover:text-white focus-visible:rounded focus-visible:ring-2 focus-visible:ring-emerald-300 [overflow-wrap:anywhere]" href={citation.href}>{citation.title}</a>{citation.groupSize && citation.groupSize > 1 ? <p className="text-[11px] text-slate-500">{citation.groupSize} related articles</p> : null}</div></li>)}</ol>{citations.length > 5 && <button aria-expanded={expanded} className="mt-2 min-h-10 rounded-lg px-1 text-sm font-medium text-slate-500 outline-none transition hover:text-white focus-visible:ring-2 focus-visible:ring-emerald-300" onClick={() => setExpanded((open) => !open)} type="button">{expanded ? "Show less" : `Show ${remaining} more`}</button>}</section>;
}

function HistoricalTable({ rows }: { rows: MultiHorizonAnalyticsResult["rows"] }) {
  return <div className="mt-5 max-w-full overflow-x-auto overscroll-x-contain" data-testid="historical-table-scroll" tabIndex={0}><table className="w-full min-w-[460px] border-collapse text-sm"><caption className="sr-only">Historical Reaction V2 returns by horizon</caption><thead><tr className="border-b border-white/10 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500"><th className="py-2 pr-3 text-left" scope="col">Horizon</th><th className="px-3 py-2 text-right" scope="col">Mean</th><th className="px-3 py-2 text-right" scope="col">Median</th><th className="py-2 pl-3 text-right" scope="col">Positive</th></tr></thead><tbody>{rows.map((row) => <tr className="border-b border-white/8 last:border-b-0" key={row.horizon}><th className="py-3 pr-3 text-left font-medium text-slate-300" scope="row">{row.horizon}</th><td className={`px-3 py-3 text-right font-mono tabular-nums ${reactionTone(row.mean)}`}>{formatPercent(row.mean)}</td><td className={`px-3 py-3 text-right font-mono tabular-nums ${reactionTone(row.median)}`}>{formatPercent(row.median)}</td><td className="py-3 pl-3 text-right font-mono tabular-nums text-white">{formatPercent(row.positivePercent, false, 2)}</td></tr>)}</tbody></table></div>;
}

function reactionTone(value: number | null): string {
  if (value === null || value === 0) return "text-slate-400";
  return value > 0 ? "text-emerald-300" : "text-rose-200";
}
