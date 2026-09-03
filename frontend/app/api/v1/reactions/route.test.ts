import { beforeEach, describe, expect, it, vi } from "vitest";

import { HORIZONS } from "@/types/events";

const mocks = vi.hoisted(() => ({ query: vi.fn() }));

vi.mock("@/lib/api-v1/data", () => ({
  getApiV1ReactionService: () => mocks,
}));

import { GET } from "@/app/api/v1/reactions/route";

const API_KEY = "test-cmr-api-key-0123456789abcdef";
const rows = HORIZONS.map((horizon, index) => ({
  horizon,
  matchedArticles: 4,
  independentEvents: 3,
  mean: index === 0 ? null : index,
  median: index === 0 ? null : index,
  positivePercent: index === 0 ? null : 66.666667,
  negativePercent: index === 0 ? null : 33.333333,
  sampleSize: index === 0 ? 0 : 3,
}));

function request(query: string): Request {
  return new Request(`http://localhost/api/v1/reactions?${query}`, { headers: { authorization: `Bearer ${API_KEY}` } });
}

describe("GET /api/v1/reactions", () => {
  beforeEach(() => {
    process.env.CMR_API_KEY = API_KEY;
    mocks.query.mockReset().mockImplementation(async (query) => query.horizon ? rows.filter((row) => row.horizon === query.horizon) : rows);
  });

  it.each(["BTC", "ETH", "SOL"])("supports %s Reaction V2 analytics", async (asset) => {
    const response = await GET(request(`asset=${asset}&horizon=24h`));
    const body = await response.json();
    expect(response.status).toBe(200);
    expect(body).toMatchObject({ data: { asset, horizon: "24h", independentEvents: 3 }, basedOn: "Reaction V2" });
  });

  it("passes topic and direction filters to the deterministic service", async () => {
    const response = await GET(request("asset=BTC&topic=etf_outflow&horizon=1h&direction=negative"));
    expect(response.status).toBe(200);
    expect(mocks.query).toHaveBeenCalledWith(expect.objectContaining({ asset: "BTC", topic: "etf_outflow", horizon: "1h", direction: "negative" }));
  });

  it("returns all six horizons and preserves null statistics", async () => {
    const response = await GET(request("asset=SOL&topic=hack"));
    const body = await response.json();
    expect(body.data.rows.map((row: { horizon: string }) => row.horizon)).toEqual(HORIZONS);
    expect(body.data.rows[0]).toMatchObject({ mean: null, median: null, positivePercent: null, negativePercent: null, sampleSize: 0 });
  });

  it("rejects invalid assets, topics, and horizons", async () => {
    expect((await GET(request("asset=XRP"))).status).toBe(400);
    expect((await GET(request("asset=BTC&topic='OR%201=1"))).status).toBe(400);
    expect((await GET(request("asset=BTC&horizon=1d"))).status).toBe(400);
  });
});

