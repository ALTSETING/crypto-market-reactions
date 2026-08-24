import { createServer } from "node:http";


const port = Number(process.env.DZ14_STUB_PORT ?? 54329);
const yearCounts = new Map([
  [2017, 206], [2018, 494], [2019, 745], [2020, 873], [2021, 1_532],
  [2022, 1_205], [2023, 1_126], [2024, 1_346], [2025, 351], [2026, 1_195],
]);

function event(index, sourceType = "news_media") {
  return {
    event_id: `stub-event-${index}`,
    slug: `dz14-stub-event-${index}-b1c2d3e4`,
    title: sourceType === "primary_document"
      ? `Primary filing test event ${index}`
      : `Historical market test event ${index}`,
    published_at: "2024-05-23T12:30:00.000Z",
    updated_at: "2026-08-24T00:00:00.000Z",
    source: sourceType === "primary_document" ? "sec" : "coindesk",
    source_url: sourceType === "primary_document"
      ? "https://www.sec.gov/Archives/edgar/data/example"
      : "https://www.coindesk.com/example",
    source_type: sourceType,
    primary_asset: "ETH",
    related_assets: ["ETH", "BTC"],
    category: "regulation",
    sentiment: "neutral",
    sentiment_score: 0,
    importance: 0.8,
    reaction_methodology: "reaction_v2_next_full_minute_open_to_open",
    reaction_value_unit: "percent",
    btc_1m: 0.01,
    btc_5m: 0.02,
    btc_15m: 0.03,
    btc_1h: 0.04,
    btc_4h: 0.05,
    btc_24h: 0.06,
    btc_average_reaction: 0.035,
    eth_1m: 0.11,
    eth_5m: 0.12,
    eth_15m: 0.13,
    eth_1h: 0.14,
    eth_4h: 0.15,
    eth_24h: 0.16,
    eth_average_reaction: 0.135,
    sol_1m: null,
    sol_5m: null,
    sol_15m: null,
    sol_1h: null,
    sol_4h: null,
    sol_24h: null,
    sol_average_reaction: null,
    btc_reaction_source: "Binance Vision official monthly 1m archive",
    btc_reference_time: "2024-05-23T12:31:00.000Z",
    btc_reference_latency_minutes: 0,
    eth_reaction_source: "Binance Vision official monthly 1m archive",
    eth_reference_time: "2024-05-23T12:31:00.000Z",
    eth_reference_latency_minutes: 0,
    sol_reaction_source: null,
    sol_reference_time: null,
    sol_reference_latency_minutes: null,
  };
}

function countFor(url) {
  if (url.searchParams.has("source_class_v2")) {
    const value = url.searchParams.get("source_class_v2")?.replace(/^eq\./, "");
    return { news_media: 8_046, primary_document: 736, official_announcement: 291, unknown: 0 }[value] ?? 0;
  }
  const lowerBound = url.searchParams.get("published_at") ?? "";
  const year = Number(lowerBound.match(/(20\d{2})/)?.[1]);
  if (yearCounts.has(year)) return yearCounts.get(year);
  if (url.searchParams.has("category")) return 611;
  return 9_073;
}

function send(response, status, body, headers = {}) {
  response.writeHead(status, {
    "Access-Control-Allow-Origin": "*",
    "Content-Type": "application/json",
    ...headers,
  });
  response.end(body === null ? undefined : JSON.stringify(body));
}

const server = createServer((request, response) => {
  const url = new URL(request.url ?? "/", `http://127.0.0.1:${port}`);
  if (request.method === "POST" && url.pathname.endsWith("/rpc/consume_events_rate_limit")) {
    send(response, 200, {
      allowed: true,
      limit: 60,
      remaining: 59,
      reset_at_epoch_ms: Date.now() + 60_000,
    });
    return;
  }
  if (url.pathname !== "/rest/v1/events") {
    send(response, 404, { error: "not found" });
    return;
  }

  const count = countFor(url);
  const contentRange = `0-${Math.max(0, Math.min(24, count - 1))}/${count}`;
  if (request.method === "HEAD") {
    send(response, 200, null, { "Content-Range": contentRange });
    return;
  }
  const accept = request.headers.accept ?? "";
  const slugLookup = url.searchParams.has("slug");
  const sourceType = url.searchParams.get("source_class_v2")?.replace(/^eq\./, "")
    ?? (slugLookup ? "primary_document" : "news_media");
  const select = url.searchParams.get("select") ?? "";
  if (select === "published_at" && url.searchParams.get("limit") === "1") {
    const oldest = (url.searchParams.get("order") ?? "").includes("asc");
    send(
      response,
      200,
      [{ published_at: oldest ? "2017-01-01T00:00:00.000Z" : "2026-08-01T00:00:00.000Z" }],
      { "Content-Range": `0-0/${count}` },
    );
    return;
  }
  if (accept.includes("application/vnd.pgrst.object+json") || slugLookup) {
    if (select === "published_at") {
      const oldest = (url.searchParams.get("order") ?? "").includes("asc");
      send(response, 200, { published_at: oldest ? "2017-01-01T00:00:00.000Z" : "2026-08-01T00:00:00.000Z" }, { "Content-Range": `0-0/${count}` });
    } else {
      send(response, 200, event(1, sourceType), { "Content-Range": `0-0/${count}` });
    }
    return;
  }
  const items = count === 0 ? [] : [event(1, sourceType), event(2, sourceType)];
  send(response, 200, items, { "Content-Range": contentRange });
});

server.listen(port, () => {
  console.log(`DZ14 Supabase stub ready on ${port}`);
});
