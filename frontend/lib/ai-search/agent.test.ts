import { describe, expect, it, vi } from "vitest";

import {
  HISTORICAL_REACTIONS_TOOL,
  OpenAiResearchAgent,
  createHistoricalToolExecutor,
  resolveAgentLanguage,
  type HistoricalToolOutcome,
} from "@/lib/ai-search/agent";
import { FixtureAiSearchDataAdapter } from "@/lib/ai-search/adapter";

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

describe("AI Research Agent V2", () => {
  it("exposes one strict historical Reaction V2 tool without a response schema", async () => {
    let requestBody: Record<string, unknown> | undefined;
    const fetchImpl = vi.fn(async (_url: string | URL | Request, init?: RequestInit) => {
      requestBody = JSON.parse(String(init?.body));
      return response({ output_text: "A Bitcoin ETF is an exchange-traded fund.", output: [], usage: {} });
    }) as unknown as typeof fetch;
    const agent = new OpenAiResearchAgent({ apiKey: "test", model: "gpt-5-mini", fetchImpl });
    const result = await agent.run("What is a Bitcoin ETF?", vi.fn());

    expect(result.answer).toContain("Bitcoin ETF");
    expect(result.historical).toBeNull();
    expect(requestBody?.tools).toEqual([HISTORICAL_REACTIONS_TOOL]);
    expect(requestBody?.tool_choice).toBe("auto");
    expect(requestBody).not.toHaveProperty("response_format");
    expect(HISTORICAL_REACTIONS_TOOL.strict).toBe(true);
    expect(HISTORICAL_REACTIONS_TOOL.parameters.additionalProperties).toBe(false);
    expect(HISTORICAL_REACTIONS_TOOL.description).toContain("ranking across topics");
  });

  it("executes a valid tool call and returns a separate deterministic evidence block", async () => {
    const payloads: Array<Record<string, unknown>> = [];
    const responses = [response({
        output: [{ type: "function_call", name: "search_historical_reactions", call_id: "call_1", arguments: JSON.stringify({
          operation: "overview", asset: "BTC", topic: "etf_outflow", compareTopic: null,
          query: "BTC ETF outflows", horizon: "24h", direction: "outflow", dateFrom: null, dateTo: null,
          metric: "mean", limit: 5,
        }) }], usage: {},
      }), response({ output_text: "ETF outflows can affect demand. Historical evidence is shown below.", output: [], usage: {} })];
    const fetchImpl = vi.fn(async (_url: string | URL | Request, init?: RequestInit) => {
      payloads.push(JSON.parse(String(init?.body)));
      return responses.shift()!;
    }) as unknown as typeof fetch;
    const evidence = {
      basedOn: "Reaction V2" as const,
      operation: "overview" as const,
      intent: { asset: "BTC" }, answer: "deterministic", calculation: "deterministic",
      result: { kind: "count", value: 2, sampleSize: 2, citations: [] }, citations: [],
    } as HistoricalToolOutcome extends { ok: true; evidence: infer T } ? T : never;
    const executeTool = vi.fn(async (): Promise<HistoricalToolOutcome> => ({ ok: true, evidence }));
    const agent = new OpenAiResearchAgent({ apiKey: "test", model: "gpt-5-mini", fetchImpl });
    const result = await agent.run("Why do ETF outflows matter and how did BTC react historically?", executeTool);

    expect(executeTool).toHaveBeenCalledOnce();
    expect(result.historical).toBe(evidence);
    expect(result.answer).toContain("shown below");
    expect(payloads[1]?.input).toEqual(expect.arrayContaining([
      expect.objectContaining({ type: "function_call_output", call_id: "call_1" }),
    ]));
    const toolOutput = (payloads[1]?.input as Array<{ type?: string; output?: string }>).find(({ type }) => type === "function_call_output")?.output ?? "";
    expect(toolOutput).toContain('"resultKind":"count"');
    expect(toolOutput).not.toMatch(/"result"|"citations"|"sampleSize"|"value"/);
  });

  it("allows one invalid-argument repair and does not fail the whole answer", async () => {
    const toolArgs = { operation: "overview", asset: "ETH", topic: "institutional_purchase", compareTopic: null, query: "large ETH purchases", horizon: null, direction: "inflow", dateFrom: null, dateTo: null, metric: "mean", limit: 5 };
    const fetchImpl = vi.fn()
      .mockResolvedValueOnce(response({ output: [{ type: "function_call", name: "search_historical_reactions", call_id: "bad", arguments: "{" }], usage: {} }))
      .mockResolvedValueOnce(response({ output: [{ type: "function_call", name: "search_historical_reactions", call_id: "fixed", arguments: JSON.stringify(toolArgs) }], usage: {} }))
      .mockResolvedValueOnce(response({ output_text: "Large purchases can affect liquidity. Historical evidence is shown below.", output: [], usage: {} })) as unknown as typeof fetch;
    const executeTool = vi.fn()
      .mockResolvedValueOnce({ ok: false, code: "INVALID_TOOL_ARGUMENTS", message: "invalid" })
      .mockResolvedValueOnce({ ok: true, evidence: {
        basedOn: "Reaction V2", operation: "overview", intent: { asset: "ETH" }, answer: "grounded", calculation: "grounded",
        result: { kind: "count", value: 1, sampleSize: 1, citations: [] }, citations: [],
      } }) as unknown as Parameters<OpenAiResearchAgent["run"]>[1];
    const agent = new OpenAiResearchAgent({ apiKey: "test", model: "gpt-5-mini", fetchImpl });
    const result = await agent.run("Why can large purchases move ETH and what happened historically?", executeTool);

    expect(executeTool).toHaveBeenCalledTimes(2);
    expect(result.historical).not.toBeNull();
    expect(result.historicalUnavailable).toBe(false);
  });

  it("degrades to a general answer after the single repair also fails", async () => {
    const invalidCall = (callId: string) => response({
      output: [{ type: "function_call", name: "search_historical_reactions", call_id: callId, arguments: "{}" }], usage: {},
    });
    const fetchImpl = vi.fn()
      .mockResolvedValueOnce(invalidCall("first"))
      .mockResolvedValueOnce(invalidCall("repair"))
      .mockResolvedValueOnce(response({ output_text: "ETF outflows can reduce demand, but historical evidence is currently unavailable.", output: [], usage: {} })) as unknown as typeof fetch;
    const executeTool = vi.fn(async (): Promise<HistoricalToolOutcome> => ({
      ok: false, code: "INVALID_TOOL_ARGUMENTS", message: "Historical tool arguments were invalid.",
    }));
    const agent = new OpenAiResearchAgent({ apiKey: "test", model: "gpt-5-mini", fetchImpl });
    const result = await agent.run("Why do ETF outflows matter and what happened historically?", executeTool);

    expect(executeTool).toHaveBeenCalledTimes(2);
    expect(result.answer).toContain("unavailable");
    expect(result.historical).toBeNull();
    expect(result.historicalUnavailable).toBe(true);
  });

  it("keeps explicit direction and horizon when executing the tool", async () => {
    const execute = createHistoricalToolExecutor(
      "How did Bitcoin react 24 hours after major ETF outflows?",
      new FixtureAiSearchDataAdapter(),
    );
    const outcome = await execute({
      operation: "overview", asset: "BTC", topic: "etf_outflow", compareTopic: null,
      query: "major ETF outflows", horizon: "24h", direction: "outflow", dateFrom: null, dateTo: null,
      metric: "mean", limit: 5,
    });
    expect(outcome.ok).toBe(true);
    if (!outcome.ok) return;
    expect(outcome.evidence.intent).toMatchObject({ asset: "BTC", topic: "etf_outflow", direction: "outflow", horizon: "24h" });
    expect(outcome.evidence.basedOn).toBe("Reaction V2");
  });

  it("rejects contradictory tool direction without querying historical data", async () => {
    const adapter = new FixtureAiSearchDataAdapter();
    const analyze = vi.spyOn(adapter, "analyze");
    const execute = createHistoricalToolExecutor("How did BTC react to ETF outflows?", adapter);
    const outcome = await execute({
      operation: "overview", asset: "BTC", topic: "etf_outflow", compareTopic: null,
      query: "ETF outflows", horizon: "24h", direction: "inflow", dateFrom: null, dateTo: null,
      metric: "mean", limit: 5,
    });
    expect(outcome).toMatchObject({ ok: false, code: "INVALID_TOOL_ARGUMENTS" });
    expect(analyze).not.toHaveBeenCalled();
  });

  it("preserves educational terms such as Layer 2 and 24-hour while removing unsupported historical statistics", async () => {
    const toolCall = () => response({
      output: [{ type: "function_call", name: "search_historical_reactions", call_id: "call", arguments: JSON.stringify({
        operation: "overview", asset: "ETH", topic: "upgrade", compareTopic: null, query: "ETH upgrades",
        horizon: "24h", direction: "unknown", dateFrom: null, dateTo: null, metric: "mean", limit: 5,
      }) }], usage: {},
    });
    const evidence = {
      basedOn: "Reaction V2" as const, operation: "overview" as const,
      intent: { asset: "ETH", topic: "upgrade", horizon: "24h" }, answer: "grounded", calculation: "grounded",
      result: { kind: "count", value: 2, sampleSize: 2, citations: [] }, citations: [],
    } as HistoricalToolOutcome extends { ok: true; evidence: infer T } ? T : never;
    const executeTool = vi.fn(async (): Promise<HistoricalToolOutcome> => ({ ok: true, evidence }));

    const safeFetch = vi.fn()
      .mockResolvedValueOnce(toolCall())
      .mockResolvedValueOnce(response({ output_text: "Layer 2 upgrades can change execution behavior over a 24-hour observation window. Evidence is shown below.", output: [], usage: {} })) as unknown as typeof fetch;
    const safeResult = await new OpenAiResearchAgent({ apiKey: "test", model: "gpt-5-mini", fetchImpl: safeFetch }).run("How did ETH react to upgrades at 24h?", executeTool);
    expect(safeResult.answer).toContain("Layer 2");
    expect(safeResult.answer).toContain("24-hour");

    const blockedFetch = vi.fn()
      .mockResolvedValueOnce(toolCall())
      .mockResolvedValueOnce(response({ output_text: "The mean was 12.4% across 20 events, the strongest result.", output: [], usage: {} })) as unknown as typeof fetch;
    const blockedResult = await new OpenAiResearchAgent({ apiKey: "test", model: "gpt-5-mini", fetchImpl: blockedFetch }).run("How did ETH react to upgrades at 24h?", executeTool);
    expect(blockedResult.answer).toMatch(/Unsupported statistics|removed/);
    expect(blockedResult.answer).not.toContain("12.4%");
  });

  it("keeps deterministic evidence when the final explanation exceeds the total provider budget", async () => {
    const first = response({
      output: [{ type: "function_call", name: "search_historical_reactions", call_id: "call", arguments: "{}" }], usage: {},
    });
    const fetchImpl = vi.fn()
      .mockResolvedValueOnce(first)
      .mockImplementationOnce((_url: string | URL | Request, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => reject(new Error("aborted")), { once: true });
      })) as unknown as typeof fetch;
    const evidence = {
      basedOn: "Reaction V2" as const, operation: "overview" as const,
      intent: { asset: "BTC" }, answer: "grounded", calculation: "grounded",
      result: { kind: "count", value: 1, sampleSize: 1, citations: [] }, citations: [],
    } as HistoricalToolOutcome extends { ok: true; evidence: infer T } ? T : never;
    const result = await new OpenAiResearchAgent({ apiKey: "test", model: "gpt-5-mini", fetchImpl, timeoutMs: 10, totalBudgetMs: 1_600 }).run(
      "How did BTC react historically?",
      vi.fn(async (): Promise<HistoricalToolOutcome> => ({ ok: true, evidence })),
    );
    expect(result.historical).toBe(evidence);
    expect(result.historicalUnavailable).toBe(false);
    expect(result.answer).toMatch(/evidence|дані/i);
  });

  it("distinguishes Ukrainian, mixed Ukrainian, and unsupported Cyrillic/Latin languages", () => {
    expect(resolveAgentLanguage("Як eth реагує after ETF outflows?")).toEqual({ language: "uk", supported: true });
    expect(resolveAgentLanguage("шо було з соланою після хаків")).toEqual({ language: "uk", supported: true });
    expect(resolveAgentLanguage("Какова цена BTC сейчас?").supported).toBe(false);
    expect(resolveAgentLanguage("Jaka jest cena BTC teraz?").supported).toBe(false);
  });
});
