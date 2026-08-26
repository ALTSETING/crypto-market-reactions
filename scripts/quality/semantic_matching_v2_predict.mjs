#!/usr/bin/env node

// Offline bridge: execute the real server classifier on the immutable golden
// headlines and emit the narrow prediction contract consumed by the Python
// quality evaluator. Requires Node 22.6+ TypeScript stripping; no DB/network.

import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

import { classifySemanticEvent } from "../../frontend/lib/ai-search/semantic-matcher.ts";

const TOPICS = [
  "large_investment", "institutional_purchase", "institutional_selling",
  "etf", "sec", "hack",
];

const [goldenArg, outputArg] = process.argv.slice(2);
if (!goldenArg || (goldenArg !== "--production-stdin" && !outputArg)) {
  throw new Error("usage: node --experimental-strip-types semantic_matching_v2_predict.mjs GOLDEN.jsonl OUTPUT.jsonl");
}

const baseIntent = {
  intent: "search", asset: null, dateFrom: null, dateTo: null, category: null,
  topic: null, actorType: "unknown", action: null, direction: "unknown",
  magnitude: "unknown", amount: null, entity: null, assetRole: "primary",
  sourceClass: null, sentiment: null, reactionSign: null, importance: null,
  horizon: null, metric: "events", sort: "newest", groupBy: "none",
  comparison: null, limit: 10,
};

if (goldenArg === "--production-stdin") {
  const productionRows = readFileSync(0, "utf8").split(/\r?\n/u).filter(Boolean).map(JSON.parse);
  const topics = ["large_investment", "institutional_purchase", "institutional_selling"];
  const selected = [];
  for (const row of productionRows) {
    const event = {
      title: row.title, assets: row.related_assets, primaryAsset: row.primary_asset ?? null,
      category: row.category,
    };
    const matches = Object.fromEntries(topics.map((topic) => [
      topic,
      classifySemanticEvent(event, { ...baseIntent, asset: "ETH", topic, assetRole: "primary" }),
    ]));
    const matchedTopics = topics.filter((topic) => matches[topic].matched);
    if (matchedTopics.length) {
      selected.push({ event_id: row.event_id, matched_topics: matchedTopics, matches });
    }
  }
  process.stdout.write(JSON.stringify({ scanned: productionRows.length, selected }));
  process.exit(0);
}

const rows = readFileSync(resolve(goldenArg), "utf8").split(/\r?\n/u).filter(Boolean).map(JSON.parse);

function magnitudeClass(match) {
  const amount = match.amount?.normalizedUsd;
  if (typeof amount === "number") {
    if (amount >= 50_000_000) return "large";
    if (amount >= 10_000_000) return "medium";
    return "small";
  }
  return match.magnitude === "large" ? "major_unquantified" : "unknown";
}

const predictions = rows.map((row) => {
  // Inputs are raw immutable event features only. In particular, never feed
  // relevant/expected_topic/asset_relevance (golden oracle labels) back into
  // the classifier.
  const event = {
    title: row.title,
    assets: row.assets,
    primaryAsset: row.primary_asset ?? null,
    category: row.category,
  };
  const matches = TOPICS.map((topic) => [topic, classifySemanticEvent(event, { ...baseIntent, asset: row.asset, topic })]);
  const representative = matches.find(([, match]) => match.matched)?.[1]
    ?? classifySemanticEvent(event, { ...baseIntent, asset: row.asset, assetRole: "any" });
  return {
    id: row.id,
    topics: matches.filter(([, match]) => match.matched).map(([topic]) => topic),
    asset_relevance: representative.assetRole === "unknown" ? "none" : representative.assetRole,
    actor_type: representative.actorType,
    action: representative.action ?? "unknown",
    direction: representative.direction,
    magnitude_class: magnitudeClass(representative),
    confidence: Math.max(...matches.map(([, match]) => match.confidence)),
  };
});

writeFileSync(resolve(outputArg), `${predictions.map((row) => JSON.stringify(row)).join("\n")}\n`, "utf8");
process.stdout.write(`${JSON.stringify({ rows: rows.length, output: resolve(outputArg) })}\n`);
