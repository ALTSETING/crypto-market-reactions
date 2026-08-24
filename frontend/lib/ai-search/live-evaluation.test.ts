import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

import { loadEnvConfig } from "@next/env";
import { describe, expect, it } from "vitest";

import { ProductionAiSearchDataAdapter } from "@/lib/ai-search/adapter";
import { groundedAnswer } from "@/lib/ai-search/answer";
import { AI_SEARCH_EVALUATION } from "@/lib/ai-search/evaluation";
import { OpenAiIntentProvider, type ProviderUsage } from "@/lib/ai-search/provider";

loadEnvConfig(process.cwd());

const HARD_CALL_CAP = 20;
const PLANNED_CALLS = 20;
const PER_REQUEST_COST_CAP_USD = 0.01;

describe.skipIf(process.env.AI_LIVE_TESTS !== "1" || !process.env.OPENAI_API_KEY)("budgeted live gpt-5-mini evaluation", () => {
  it("passes supported, ambiguous, unsupported, and adversarial gates", async () => {
    const budget = Number(process.env.AI_LIVE_TEST_BUDGET_USD ?? "0");
    expect(Number.isFinite(budget) && budget > 0 && budget <= 0.05).toBe(true);
    const cases = [
      ...AI_SEARCH_EVALUATION.filter(({ kind }) => kind === "supported").slice(0, 10),
      ...AI_SEARCH_EVALUATION.filter(({ kind }) => kind === "ambiguous").slice(0, 3),
      ...AI_SEARCH_EVALUATION.filter(({ kind }) => kind === "unsupported").slice(0, 3),
      ...AI_SEARCH_EVALUATION.filter(({ kind }) => kind === "adversarial").slice(0, 4),
    ];
    expect(cases).toHaveLength(PLANNED_CALLS);
    const usage: ProviderUsage[] = [];
    const provider = new OpenAiIntentProvider({
      apiKey: process.env.OPENAI_API_KEY!,
      model: "gpt-5-mini",
      maxCostUsd: PER_REQUEST_COST_CAP_USD,
      timeoutMs: 10_000,
      onUsage: (item) => usage.push(item),
    });
    const adapter = new ProductionAiSearchDataAdapter(undefined, 20_000);
    let calls = 0;
    let estimatedCostUsd = 0;
    let supportedPassed = 0;
    let ambiguousPassed = 0;
    let rejectedPassed = 0;

    for (const evaluation of cases) {
      if (calls >= HARD_CALL_CAP || estimatedCostUsd + PER_REQUEST_COST_CAP_USD > budget) break;
      const resolution = await provider.resolve(evaluation.question);
      calls += 1;
      estimatedCostUsd = usage.reduce((sum, item) => sum + item.estimatedCostUsd, 0);
      expect(estimatedCostUsd).toBeLessThanOrEqual(budget);
      if (evaluation.kind === "supported") {
        expect(resolution.status, evaluation.id).toBe("ready");
        if (resolution.status !== "ready") continue;
        const result = await adapter.analyze(resolution.intent);
        const wording = groundedAnswer(result);
        const resultNumbers = new Set(JSON.stringify(result).match(/-?\d+(?:\.\d+)?/g) ?? []);
        const answerNumbers = `${wording.answer} ${wording.calculation}`.match(/-?\d+(?:\.\d+)?/g) ?? [];
        expect(answerNumbers.every((value) => resultNumbers.has(value)), evaluation.id).toBe(true);
        expect(result.citations.length, evaluation.id).toBeGreaterThan(0);
        expect(result.citations.length, evaluation.id).toBeLessThanOrEqual(50);
        supportedPassed += 1;
      } else if (evaluation.kind === "ambiguous") {
        expect(resolution.status, evaluation.id).toBe("clarification");
        ambiguousPassed += 1;
      } else {
        expect(resolution.status, evaluation.id).toBe("rejected");
        rejectedPassed += 1;
      }
    }

    expect(calls).toBe(PLANNED_CALLS);
    expect(supportedPassed).toBe(10);
    expect(ambiguousPassed).toBe(3);
    expect(rejectedPassed).toBe(7);
    const reportDir = path.resolve(".tools");
    mkdirSync(reportDir, { recursive: true });
    writeFileSync(path.join(reportDir, "ai-search-live-evaluation.json"), `${JSON.stringify({
      status: "PASS",
      model: "gpt-5-mini",
      calls,
      hardCallCap: HARD_CALL_CAP,
      budgetUsd: budget,
      estimatedCostUsd,
      inputTokens: usage.reduce((sum, item) => sum + item.inputTokens, 0),
      cachedInputTokens: usage.reduce((sum, item) => sum + item.cachedInputTokens, 0),
      outputTokens: usage.reduce((sum, item) => sum + item.outputTokens, 0),
      latencyMs: usage.map(({ latencyMs }) => latencyMs),
      supportedPassed,
      ambiguousPassed,
      rejectedPassed,
    }, null, 2)}\n`);
  }, 300_000);
});
