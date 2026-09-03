const baseUrl = (process.env.CMR_API_BASE_URL || "https://crypto-market-reactions.com").replace(/\/$/u, "");
const apiKey = process.env.CMR_API_KEY;

if (!apiKey) {
  console.error("CMR_API_KEY is required for the API V1 smoke test.");
  process.exit(2);
}

const timings = [];
const results = [];

async function check(name, path, expectedStatus = 200, key = apiKey, validate = () => true) {
  const started = performance.now();
  try {
    const response = await fetch(`${baseUrl}${path}`, {
      headers: { Authorization: `Bearer ${key}` },
      redirect: "error",
    });
    const latencyMs = performance.now() - started;
    if (expectedStatus === 200) timings.push(latencyMs);
    const body = await response.json();
    const passed = response.status === expectedStatus && validate(body);
    results.push({ name, passed, status: response.status, latencyMs: Math.round(latencyMs) });
    return body;
  } catch (error) {
    results.push({ name, passed: false, status: 0, latencyMs: Math.round(performance.now() - started), error: error instanceof Error ? error.name : "UnknownError" });
    return null;
  }
}

await check("health", "/api/v1/health", 200, apiKey, (body) => body.status === "ok" && body.apiVersion === "v1");
await check("meta", "/api/v1/meta", 200, apiKey, (body) => body.data?.assets?.length === 3 && body.data?.horizons?.length === 6);
const firstPage = await check("events-default", "/api/v1/events?limit=1", 200, apiKey, (body) => Array.isArray(body.data) && body.data.length <= 1);
await check("events-btc", "/api/v1/events?asset=BTC&limit=2", 200);
await check("events-eth-date", "/api/v1/events?asset=ETH&dateFrom=2024-01-01&limit=2", 200);
await check("events-sol", "/api/v1/events?asset=SOL&limit=2", 200);
await check("events-search", "/api/v1/events?search=ETF&limit=2", 200);
const slug = firstPage?.data?.[0]?.slug;
await check("event-detail", slug ? `/api/v1/events/${encodeURIComponent(slug)}` : "/api/v1/events/smoke-missing-slug", slug ? 200 : 404);
await check("reaction-btc-24h", "/api/v1/reactions?asset=BTC&horizon=24h", 200, apiKey, (body) => body.basedOn === "Reaction V2");
await check("reaction-eth-topic", "/api/v1/reactions?asset=ETH&topic=institutional_purchase&horizon=24h", 200);
await check("reaction-sol-multi", "/api/v1/reactions?asset=SOL", 200, apiKey, (body) => body.data?.rows?.length === 6);
await check("reaction-btc-etf", "/api/v1/reactions?asset=BTC&topic=etf_outflow&horizon=24h", 200);
await check("reaction-eth-positive", "/api/v1/reactions?asset=ETH&horizon=1h&direction=positive", 200);
await check("invalid-key", "/api/v1/health", 401, `${apiKey}-invalid`, (body) => body.error?.code === "UNAUTHORIZED");
await check("invalid-parameter", "/api/v1/events?limit=101", 400, apiKey, (body) => body.error?.code === "INVALID_PARAMETER");

const sorted = [...timings].sort((a, b) => a - b);
const percentile = (fraction) => sorted.length === 0 ? null : Math.round(sorted[Math.min(sorted.length - 1, Math.ceil(sorted.length * fraction) - 1)]);
const passed = results.filter((result) => result.passed).length;
console.log(JSON.stringify({
  status: passed === 15 ? "PASS" : "FAIL",
  passed,
  total: 15,
  performanceMs: { p50: percentile(0.5), p95: percentile(0.95) },
  results,
}, null, 2));
process.exitCode = passed === 15 ? 0 : 1;

