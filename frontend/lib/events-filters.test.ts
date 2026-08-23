import { describe, expect, it } from "vitest";

import { applyFilterUpdates, applyQuickAction, clearAllEventFilters } from "./events-filters";
import { parseEventsQuery } from "./validation/events-query";

describe("event filter URL state", () => {
  it("resets reaction sorting when All events is selected", () => {
    const current = new URLSearchParams(
      "asset=BTC&sort=growth&horizon=average&marketDataOnly=true&page=3",
    );
    const next = applyFilterUpdates(current, { asset: null, page: null });
    expect(next.get("sort")).toBeNull();
    expect(next.get("marketDataOnly")).toBeNull();
    expect(parseEventsQuery(next).sort).toBe("newest");
  });

  it("configures Top gainers", () => {
    const next = applyQuickAction(new URLSearchParams("asset=ETH&page=4"), "gainers");
    expect(Object.fromEntries(next)).toMatchObject({
      asset: "ETH",
      sort: "growth",
      horizon: "average",
      marketDataOnly: "true",
    });
    expect(next.get("page")).toBeNull();
  });

  it("configures Top losers", () => {
    const next = applyQuickAction(new URLSearchParams("asset=SOL"), "losers");
    expect(next.get("sort")).toBe("decline");
    expect(next.get("horizon")).toBe("average");
    expect(next.get("marketDataOnly")).toBe("true");
  });

  it("round-trips all supported URL parameters", () => {
    const params = new URLSearchParams(
      "asset=BTC&sort=growth&horizon=1h&marketDataOnly=true&page=2&pageSize=50&q=bitcoin&source=SEC&from=2024-01-01&to=2025-01-01",
    );
    const parsed = parseEventsQuery(new URLSearchParams(params.toString()));
    expect(parsed).toMatchObject({
      asset: "BTC",
      sort: "growth",
      horizon: "1h",
      marketDataOnly: true,
      page: 2,
      pageSize: 50,
      query: "bitcoin",
      source: "SEC",
      from: "2024-01-01",
      to: "2025-01-01",
    });
  });

  it("clears every filter and restores parser defaults", () => {
    const parsed = parseEventsQuery(clearAllEventFilters());
    expect(parsed).toMatchObject({ asset: null, sort: "newest", page: 1, pageSize: 20 });
  });
});
