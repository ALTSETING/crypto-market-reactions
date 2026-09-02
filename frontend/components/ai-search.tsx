"use client";

import { FormEvent, KeyboardEvent, useState } from "react";

import { formatPercent } from "@/lib/ai-search/format";
import { AI_TOPIC_LABELS, type AiAgentSuccess, type AiHybridSuccess, type AiResearchSuccess, type AiSearchErrorBody, type AiSearchSuccess, type MultiHorizonAnalyticsResult } from "@/types/ai-search";
import { SOURCE_TYPE_LABELS } from "@/types/events";

const EXAMPLES = [
  "How does ETH react to large institutional purchases?",
  "How does ETH react to sales by large investors?",
  "How does BTC react to ETF inflows?",
  "How does SOL react to large purchases?",
  "What is a Bitcoin ETF?",
  "Why can ETF outflows affect Bitcoin?",
  "Why can ETF outflows hurt Bitcoin, and what happened historically?",
  "Що таке стейкінг?",
  "Що таке стейкінг і як ETH історично реагує на новини про стейкінг?",
] as const;
const QUICK_FILTERS = ["BTC", "ETH", "SOL", "ETF", "SEC", "Macro"] as const;

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
    <section aria-label="AI Research search" className="mt-8 min-w-0 max-w-full sm:mt-10">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 className="text-lg font-semibold tracking-tight text-white">Ask a question</h2>
          <p className="mt-1 max-w-2xl text-sm leading-6 text-slate-500">English or Ukrainian, with Reaction V2 evidence when relevant.</p>
        </div>
        <span className="w-fit text-xs font-medium text-emerald-300">Based on Reaction V2 + general explanations</span>
      </div>

      <form className="mt-4 rounded-2xl border border-white/10 bg-slate-900/45 p-2 shadow-[0_16px_50px_rgba(2,6,23,0.1)] focus-within:border-emerald-400/40 focus-within:ring-4 focus-within:ring-emerald-400/[0.06]" onSubmit={submit}>
        <label className="sr-only" htmlFor="ai-search-question">Crypto research question</label>
        <textarea
          className="block min-h-24 w-full min-w-0 resize-y bg-transparent px-3 py-3 text-base leading-6 text-white outline-none placeholder:text-slate-600 sm:min-h-16"
          id="ai-search-question"
          maxLength={500}
          onChange={(event) => setQuestion(event.target.value)}
          onKeyDown={handleQuestionKeyDown}
          placeholder="Ask about crypto concepts or historical BTC, ETH, and SOL reactions…"
          rows={2}
          value={question}
        />
        <div className="flex items-center justify-between gap-3 border-t border-white/8 px-2 pt-2">
          <span className="text-[11px] leading-4 text-slate-500">Enter to analyze · Shift + Enter for a new line</span>
          <button className="min-h-11 shrink-0 rounded-xl bg-emerald-400 px-4 text-sm font-bold text-slate-950 outline-none transition hover:bg-emerald-300 focus-visible:ring-2 focus-visible:ring-emerald-200 disabled:cursor-not-allowed disabled:opacity-45" disabled={state.kind === "loading" || question.trim().length < 3} type="submit">
            {state.kind === "loading" ? "Analyzing…" : "Analyze"}
          </button>
        </div>
      </form>

      {state.kind === "idle" && (
        <div className="mt-4">
          <div aria-label="Quick filters" className="flex flex-wrap gap-2">
            {QUICK_FILTERS.map((filter) => <button className="min-h-11 rounded-full border border-white/10 px-3 text-xs font-medium text-slate-400 outline-none transition hover:border-white/20 hover:text-white focus-visible:ring-2 focus-visible:ring-emerald-300" key={filter} onClick={() => setQuestion((value) => `${value}${value ? " " : ""}${filter}`)} type="button">{filter}</button>)}
          </div>
          <div aria-label="Example questions" className="mt-3 grid gap-x-6 sm:grid-cols-2">
            {EXAMPLES.map((example) => (
              <button className="min-h-11 min-w-0 break-words border-b border-white/8 py-2.5 text-left text-xs leading-5 text-slate-500 outline-none transition hover:text-white focus-visible:rounded focus-visible:ring-2 focus-visible:ring-emerald-300 [overflow-wrap:anywhere]" key={example} onClick={() => setQuestion(example)} type="button">{example}</button>
            ))}
          </div>
        </div>
      )}

      <div aria-live="polite" className="mt-7 min-w-0 max-w-full">
        {state.kind === "idle" && <p className="text-sm text-slate-500">Ask any crypto research question to begin.</p>}
        {state.kind !== "idle" && submittedQuestion && (
          <div className="mb-7 min-w-0 border-l-2 border-emerald-400/35 pl-4">
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">Your question</p>
            <p className="mt-1 break-words text-sm leading-6 text-slate-300 [overflow-wrap:anywhere]">{submittedQuestion}</p>
          </div>
        )}
        {state.kind === "loading" && <AiLoadingState />}
        {state.kind === "refusal" && <AiMessage kind="warning" label="Request not supported" message={state.message} />}
        {state.kind === "error" && <AiMessage kind="error" label="Unable to complete request" message={state.message} />}
        {state.kind === "success" && <AiResult data={state.data} />}
      </div>
    </section>
  );
}

export function AiLoadingState() {
  return (
    <div aria-label="AI Research is analyzing" className="py-2" role="status">
      <div className="flex items-center gap-3 text-sm text-slate-400">
        <span aria-hidden="true" className="size-2 animate-pulse rounded-full bg-emerald-400" />
        Reviewing the question…
      </div>
      <div aria-hidden="true" className="mt-5 grid gap-3">
        <span className="h-2.5 w-11/12 animate-pulse rounded-full bg-white/5" />
        <span className="h-2.5 w-4/5 animate-pulse rounded-full bg-white/5" />
        <span className="h-2.5 w-2/3 animate-pulse rounded-full bg-white/5" />
      </div>
    </div>
  );
}

export function AiMessage({ kind, label, message }: { kind: "warning" | "error"; label: string; message: string }) {
  return (
    <div className={`border-l-2 py-1 pl-4 text-sm leading-6 ${kind === "error" ? "border-rose-400/60 text-rose-200" : "border-amber-300/60 text-amber-100"}`} role={kind === "error" ? "alert" : "status"}>
      <p className="font-semibold">{label}</p>
      <p className="mt-1 opacity-80">{message}</p>
    </div>
  );
}

export function AiResult({ data }: { data: AiResearchSuccess }) {
  if (data.mode === "agent") return <AgentResult data={data} />;
  if (data.mode === "general") {
    return (
      <article aria-label="AI explanation" className="mx-auto min-w-0 max-w-[800px]">
        <ResultEyebrow>{data.modeLabel}</ResultEyebrow>
        <ProseAnswer text={data.answer} />
        <ResultDisclaimer>{data.disclaimer}</ResultDisclaimer>
      </article>
    );
  }
  return <DatabaseResult data={data} />;
}

function AgentResult({ data }: { data: AiAgentSuccess }) {
  const historicalData: AiSearchSuccess | null = data.historical ? {
    status: "ok",
    mode: "database",
    modeLabel: "Historical evidence — Reaction V2",
    language: data.language,
    basedOn: data.historical.basedOn,
    intent: data.historical.intent,
    answer: data.historical.answer,
    calculation: data.historical.calculation,
    result: data.historical.result,
    citations: data.historical.citations,
    disclaimer: data.language === "uk" ? "Лише історичний аналіз — не фінансова порада." : "Historical analysis only — not financial advice.",
  } : null;

  return (
    <div className="min-w-0 max-w-full">
      <article aria-label="AI explanation" className="mx-auto min-w-0 max-w-[800px]">
        <ResultEyebrow>{data.modeLabel}</ResultEyebrow>
        <ProseAnswer text={data.answer} />
        {data.historicalUnavailable && <div className="mt-5"><AiMessage kind="warning" label="Historical evidence unavailable" message={data.historicalMessage ?? "Historical evidence is temporarily unavailable."} /></div>}
        <ResultDisclaimer>{data.disclaimer}</ResultDisclaimer>
      </article>
      {historicalData && <div className="mt-8 border-t border-white/10 pt-8"><DatabaseResult data={historicalData} /></div>}
    </div>
  );
}

function ProseAnswer({ text }: { text: string }) {
  const paragraphs = text.split(/\n{2,}/u).filter(Boolean);
  return (
    <div className="mt-4 min-w-0 space-y-4 break-words text-base leading-7 text-white sm:text-[17px] sm:leading-8 [overflow-wrap:anywhere]">
      {paragraphs.map((paragraph, index) => <p className="whitespace-pre-wrap" key={`${index}-${paragraph.slice(0, 24)}`}>{paragraph}</p>)}
    </div>
  );
}

function ResultEyebrow({ children }: { children: React.ReactNode }) {
  return <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-emerald-300">{children}</p>;
}

function ResultDisclaimer({ children }: { children: React.ReactNode }) {
  return <p className="mt-6 border-t border-white/8 pt-3 text-xs leading-5 text-slate-500">{children}</p>;
}

function DatabaseResult({ data }: { data: AiSearchSuccess | AiHybridSuccess }) {
  const metricLabel = data.result.kind === "count" ? "Count"
    : data.result.kind === "ranking" ? "Reaction ranking"
      : data.result.kind === "topic_ranking" ? "Topic ranking"
        : data.result.kind === "topic_comparison" ? "Topic comparison"
          : data.result.kind === "multi_horizon" ? "Reaction overview"
            : data.intent.metric === "mean" ? "Average reaction" : data.intent.metric === "median" ? "Median reaction" : "Historical events";
  const chips = [
    data.intent.asset,
    data.intent.horizon,
    data.intent.topic ? AI_TOPIC_LABELS[data.intent.topic] : null,
    data.intent.direction !== "unknown" ? data.intent.direction === "inflow" ? "Capital inflow" : data.intent.direction === "outflow" ? "Capital outflow" : "Neutral direction" : null,
    data.intent.magnitude === "large" ? "Large transactions (≥ $50M)" : null,
    data.intent.assetRole === "primary" ? "Primary asset only" : data.intent.assetRole === "secondary" ? "Secondary context" : null,
    data.intent.sourceClass ? SOURCE_TYPE_LABELS[data.intent.sourceClass] : null,
    data.intent.category ? data.intent.category.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase()) : null,
  ].filter((chip): chip is string => Boolean(chip));
  const sampleSize = data.result.kind === "search"
    ? data.result.matched
    : data.result.kind === "comparison"
      ? data.result.left.sampleSize + data.result.right.sampleSize
      : data.result.kind === "topic_comparison"
        ? data.result.left.independentSampleSize + data.result.right.independentSampleSize
        : data.result.kind === "topic_ranking"
          ? Math.max(0, ...data.result.items.map((item) => item.independentSampleSize))
          : data.result.kind === "multi_horizon"
            ? Math.max(0, ...data.result.rows.map((row) => row.sampleSize))
            : data.result.sampleSize;
  const requestedRow = data.result.kind === "multi_horizon"
    ? data.result.rows.find((row) => row.horizon === (data.intent.horizon ?? "24h"))
    : null;
  const summaryMetrics = [
    ...(data.result.topicFilter
      ? [
          { label: "Independent events", value: String(data.result.topicFilter.independentEventCount) },
          { label: "Matched articles", value: String(data.result.topicFilter.matchedSampleSize) },
        ]
      : [
          { label: "Asset", value: data.intent.asset ?? "All" },
          { label: "Horizon", value: data.intent.horizon ?? "All horizons" },
        ]),
    ...(requestedRow
      ? [
          { label: `Median ${requestedRow.horizon}`, value: formatPercent(requestedRow.median) },
          { label: `Positive share ${requestedRow.horizon}`, value: formatPercent(requestedRow.positivePercent, false, 2) },
        ]
      : [
          { label: "Metric", value: metricLabel },
          { label: "Sample", value: String(sampleSize) },
        ]),
  ];

  return (
    <section aria-label="Historical evidence" className="min-w-0 max-w-full rounded-2xl bg-white/[0.035] px-4 py-5 sm:px-6 sm:py-6">
      {data.mode === "hybrid" && (
        <article aria-label="General explanation" className="mx-auto max-w-[800px] pb-7">
          <ResultEyebrow>General explanation</ResultEyebrow>
          <ProseAnswer text={data.generalExplanation} />
        </article>
      )}
      <div className={data.mode === "hybrid" ? "border-t border-white/10 pt-7" : undefined}>
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-lg font-semibold tracking-tight text-white">Historical evidence</h3>
          <span className="rounded-full bg-emerald-400/10 px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.14em] text-emerald-300">Reaction V2</span>
        </div>
        <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-500">
          {chips.map((chip) => <span className="max-w-full break-words [overflow-wrap:anywhere]" key={chip}>{chip}</span>)}
        </div>

        <p className="mt-5 max-w-[800px] break-words text-base font-medium leading-7 text-white [overflow-wrap:anywhere]">{data.answer}</p>
        {data.answer === "No matching historical events found." && <p className="mt-1 text-sm text-slate-500">Try a broader topic or date range.</p>}

        <dl className="mt-5 grid grid-cols-2 gap-x-4 gap-y-4 border-y border-white/8 py-4 text-sm sm:grid-cols-4">
          {summaryMetrics.map((metric) => <Metric key={metric.label} {...metric} />)}
        </dl>

        {data.result.topicFilter && (
          <div className="mt-4 text-xs leading-5 text-slate-500">
            <p>
              Candidate pool <strong className="font-semibold text-slate-300">{data.result.topicFilter.broadSampleSize}</strong>
              {" · Duplicate groups "}<strong className="font-semibold text-slate-300">{data.result.topicFilter.duplicateGroupCount}</strong>
              {data.result.topicFilter.heuristicMatches > 0 ? ` · ${data.result.topicFilter.heuristicMatches} lower-confidence phrase matches` : ""}
            </p>
            {data.result.topicFilter.entityConcentrationWarning && <div className="mt-3"><AiMessage kind="warning" label="Entity concentration" message={`${data.result.topicFilter.largestEntity ?? "One entity"} represents ${data.result.topicFilter.largestEntityShare.toFixed(1)}% of independent events.`} /></div>}
          </div>
        )}
        {sampleSize > 0 && sampleSize < 10 && <div className="mt-4"><AiMessage kind="warning" label={sampleSize < 5 ? "Very small sample" : "Small sample"} message={sampleSize < 5 ? "Statistical reliability is low." : "Interpret the result cautiously."} /></div>}
        {data.result.kind === "scalar" && data.result.sampleSize > 0 && (
          <p className="mt-3 text-xs text-slate-500">5% trimmed mean: {formatPercent(data.result.trimmedMean5Percent)}{data.result.standardDeviation !== null ? ` · SD ${formatPercent(data.result.standardDeviation, false)} · SE ${formatPercent(data.result.standardError, false)}` : ""}</p>
        )}
        {data.result.kind === "share" && data.result.positive95Ci && <p className="mt-3 text-xs text-slate-500">Positive-share 95% CI: {formatPercent(data.result.positive95Ci.low, false)}–{formatPercent(data.result.positive95Ci.high, false)}</p>}
        {data.calculation && data.calculation !== data.answer && <p className="mt-3 max-w-[800px] text-xs leading-5 text-slate-500">{data.calculation}</p>}

        {data.result.kind === "multi_horizon" && sampleSize > 0 && <HistoricalTable rows={data.result.rows} />}
        {data.result.kind === "ranking" && data.result.items.length > 0 && (
          <ol className="mt-5 divide-y divide-white/8 border-y border-white/8">
            {data.result.items.map((item, index) => (
              <li className="grid min-w-0 gap-1 py-3 sm:grid-cols-[1fr_auto] sm:items-center sm:gap-5" key={item.eventId}>
                <a className="min-w-0 break-words text-sm text-sky-200 outline-none hover:text-white focus-visible:rounded focus-visible:ring-2 focus-visible:ring-emerald-300 [overflow-wrap:anywhere]" href={item.href}>{index + 1}. {item.title}</a>
                <span className={`font-mono text-sm font-semibold tabular-nums ${reactionTone(item.reaction)}`}>{formatPercent(item.reaction)}</span>
              </li>
            ))}
          </ol>
        )}
        {data.result.kind === "topic_ranking" && data.result.items.length > 0 && (
          <ol className="mt-5 divide-y divide-white/8 border-y border-white/8">
            {data.result.items.map((item, index) => (
              <li className="grid min-w-0 gap-1 py-3 sm:grid-cols-[1fr_auto] sm:items-center sm:gap-5" key={item.topic}>
                <p className="break-words text-sm font-medium text-slate-300 [overflow-wrap:anywhere]">{index + 1}. {AI_TOPIC_LABELS[item.topic]}</p>
                <p className="break-words font-mono text-xs tabular-nums text-white">{formatPercent(item.value, false)} · independent N {item.independentSampleSize} · {data.intent.horizon}</p>
              </li>
            ))}
          </ol>
        )}
        {data.result.kind === "topic_comparison" && (
          <div className="mt-5 grid min-w-0 divide-y divide-white/8 border-y border-white/8 sm:grid-cols-2 sm:divide-x sm:divide-y-0">
            {[data.result.left, data.result.right].map((side) => (
              <div className="min-w-0 py-4 first:sm:pr-5 last:sm:pl-5" key={side.topic}>
                <p className="break-words text-xs text-slate-500 [overflow-wrap:anywhere]">{AI_TOPIC_LABELS[side.topic]}</p>
                <p className="mt-1 break-words font-mono text-sm font-semibold text-white">{formatPercent(side.value, false)} · independent N {side.independentSampleSize}</p>
              </div>
            ))}
          </div>
        )}

        {data.citations.length > 0 && (
          <section aria-labelledby="sources-heading" className="mt-7">
            <h4 className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500" id="sources-heading">Sources · {data.citations.length}</h4>
            <ol className="mt-2 divide-y divide-white/8 border-t border-white/8">
              {data.citations.map((citation, index) => (
                <li className="grid min-w-0 grid-cols-[1.5rem_1fr] gap-2 py-2.5 text-sm" key={citation.eventId}>
                  <span aria-hidden="true" className="font-mono text-xs leading-5 text-slate-600">{index + 1}</span>
                  <div className="min-w-0">
                    <a className="inline-flex min-h-11 break-words py-1 leading-5 text-sky-200 outline-none hover:text-white focus-visible:rounded focus-visible:ring-2 focus-visible:ring-emerald-300 [overflow-wrap:anywhere]" href={citation.href}>{citation.title}</a>
                    {citation.groupSize && citation.groupSize > 1 ? <p className="mt-0.5 text-[11px] text-slate-500">Grouped event · {citation.groupSize} articles</p> : null}
                  </div>
                </li>
              ))}
            </ol>
          </section>
        )}
        <p className="mt-5 text-xs leading-5 text-slate-500">{data.basedOn}. {data.disclaimer}</p>
      </div>
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="min-w-0"><dt className="text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-600">{label}</dt><dd className="mt-1 break-words font-medium text-slate-300 [overflow-wrap:anywhere]">{value}</dd></div>;
}

function HistoricalTable({ rows }: { rows: MultiHorizonAnalyticsResult["rows"] }) {
  return (
    <div className="mt-5 max-w-full overflow-x-auto overscroll-x-contain" data-testid="historical-table-scroll" tabIndex={0}>
      <table className="w-full min-w-[540px] border-collapse text-sm">
        <caption className="sr-only">Historical Reaction V2 returns by horizon</caption>
        <thead>
          <tr className="border-b border-white/10 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate-500">
            <th className="py-2 pr-3 text-left" scope="col">Horizon</th>
            <th className="px-3 py-2 text-right" scope="col">Mean</th>
            <th className="px-3 py-2 text-right" scope="col">Median</th>
            <th className="px-3 py-2 text-right" scope="col">Positive</th>
            <th className="py-2 pl-3 text-right" scope="col">Sample</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr className="border-b border-white/8 last:border-b-0" key={row.horizon}>
              <th className="py-3 pr-3 text-left font-medium text-slate-300" scope="row">{row.horizon}</th>
              <td className={`px-3 py-3 text-right font-mono tabular-nums ${reactionTone(row.mean)}`}>{formatPercent(row.mean)}</td>
              <td className={`px-3 py-3 text-right font-mono tabular-nums ${reactionTone(row.median)}`}>{formatPercent(row.median)}</td>
              <td className="px-3 py-3 text-right font-mono tabular-nums text-white">{formatPercent(row.positivePercent, false, 2)}</td>
              <td className="py-3 pl-3 text-right font-mono tabular-nums text-slate-500">{row.sampleSize}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function reactionTone(value: number | null): string {
  if (value === null || value === 0) return "text-slate-400";
  return value > 0 ? "text-emerald-300" : "text-rose-200";
}
