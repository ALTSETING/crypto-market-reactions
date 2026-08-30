import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

import { loadEnvConfig } from "@next/env";
import { createClient } from "@supabase/supabase-js";
import { describe, expect, it } from "vitest";

import { ProductionAiSearchDataAdapter } from "@/lib/ai-search/adapter";
import { MockAiIntentProvider } from "@/lib/ai-search/provider";
import { classifySemanticEvent } from "@/lib/ai-search/semantic-matcher";
import { executeAiSearch } from "@/lib/ai-search/service";

loadEnvConfig(process.cwd());

const CASES = [
  "How did ETH react to SEC filings in 2024 after 24h?",
  "How did ETH react to ETF news?",
  "How did SOL react to hack news?",
  "Як ETH реагує на великі фінансові інвестиції?",
  "How many positive ETH reactions were there in 2023?",
] as const;

describe.skipIf(process.env.AI_PRODUCTION_PARITY !== "1")("production topic relevance", () => {
  it("returns only relevant public citations for mandatory topic queries", async () => {
    const url = process.env.SUPABASE_URL;
    const key = process.env.SUPABASE_SECRET_KEY || process.env.SUPABASE_SERVICE_ROLE_KEY;
    expect(url && key).toBeTruthy();
    expect(new URL(url!).hostname.split(".")[0]).toBe("ickflwksigaotygtdyko");
    const client = createClient(url!, key!, { auth: { persistSession: false, autoRefreshToken: false } });
    const adapter = new ProductionAiSearchDataAdapter(client, 20_000);
    const provider = new MockAiIntentProvider();
    const report: unknown[] = [];

    for (const question of CASES) {
      const response = await executeAiSearch(question, provider, adapter);
      expect(response.statusCode).toBe(200);
      if (response.statusCode !== 200) throw new Error("Expected production analytics result");
      if (response.body.intent.topic) {
        const matched = response.body.result.topicFilter?.matchedSampleSize ?? 0;
        if (matched === 0) {
          expect(response.body.answer).toBe("No matching historical events found.");
          expect(response.body.citations).toHaveLength(0);
        } else {
          expect(response.body.citations.length).toBeGreaterThan(0);
          expect(response.body.citations.every((citation) => classifySemanticEvent({
            title: citation.title,
            assets: response.body.intent.asset ? [response.body.intent.asset] : [],
            category: "news",
            primaryAsset: response.body.intent.asset,
          }, response.body.intent).matched)).toBe(true);
        }
      }
      report.push({
        questionId: CASES.indexOf(question) + 1,
        intent: {
          asset: response.body.intent.asset,
          topic: response.body.intent.topic,
          category: response.body.intent.category,
          horizon: response.body.intent.horizon,
          metric: response.body.intent.metric,
          reactionSign: response.body.intent.reactionSign,
        },
        topicFilter: response.body.result.topicFilter ?? null,
        result: response.body.result.kind === "multi_horizon" ? response.body.result.rows : response.body.result,
        firstFiveCitations: response.body.citations.slice(0, 5),
      });
    }

    const reportDir = path.resolve(".tools");
    mkdirSync(reportDir, { recursive: true });
    writeFileSync(path.join(reportDir, "ai-topic-relevance.json"), `${JSON.stringify(report, null, 2)}\n`);
  }, 120_000);
});
