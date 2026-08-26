const baseUrl = process.env.AI_SEARCH_SMOKE_URL ?? "http://127.0.0.1:3100";

const cases = [
  ["Як ETH реагує на великі інвестиції?", { asset: "ETH", topic: "large_investment", action: "invest", direction: "inflow", magnitude: "large" }],
  ["Як ETH реагує на великі інституційні покупки?", { asset: "ETH", topic: "institutional_purchase", action: "buy", direction: "inflow", magnitude: "large" }],
  ["Як ETH реагує на продажі великими інвесторами?", { asset: "ETH", topic: "institutional_selling", action: "sell", direction: "outflow" }],
  ["How does BTC react to institutional buying?", { asset: "BTC", topic: "institutional_purchase", action: "buy", direction: "inflow" }],
  ["How does BTC react to institutional selling?", { asset: "BTC", topic: "institutional_selling", action: "sell", direction: "outflow" }],
  ["How does ETH react to ETF inflows?", { asset: "ETH", topic: "etf_inflow", action: "deposit", direction: "inflow" }],
  ["How does ETH react to ETF outflows?", { asset: "ETH", topic: "etf_outflow", action: "withdraw", direction: "outflow" }],
  ["How does ETH react to funding rounds?", { asset: "ETH", topic: "funding", action: "raise", direction: "inflow" }],
  ["How does ETH react to acquisitions?", { asset: "ETH", topic: "acquisition", action: "acquire", direction: "neutral" }],
  ["How does SOL react to large purchases?", { asset: "SOL", topic: "large_investment", action: "buy", direction: "inflow", magnitude: "large" }],
];

const summary = [];
for (const [question, expected] of cases) {
  const response = await fetch(`${baseUrl}/api/ai-search`, {
    method: "POST",
    headers: { "content-type": "application/json", "x-forwarded-for": "203.0.113.23" },
    body: JSON.stringify({ question }),
  });
  const body = await response.json();
  if (response.status !== 200 || body.status !== "ok") {
    throw new Error(`${question}: HTTP ${response.status} ${JSON.stringify(body)}`);
  }
  for (const [field, value] of Object.entries(expected)) {
    if (body.intent[field] !== value) throw new Error(`${question}: ${field}=${body.intent[field]}, expected ${value}`);
  }
  if (body.basedOn !== "Reaction V2" || !body.result.topicFilter) {
    throw new Error(`${question}: missing Reaction V2 grounding or semantic topic summary`);
  }
  const sampleSize = body.result.kind === "multi_horizon"
    ? Math.max(...body.result.rows.map((row) => row.sampleSize))
    : body.result.sampleSize ?? body.result.matched ?? 0;
  summary.push({ question, topic: body.intent.topic, sampleSize });
}

console.log(JSON.stringify({ status: "PASS", cases: summary }, null, 2));
