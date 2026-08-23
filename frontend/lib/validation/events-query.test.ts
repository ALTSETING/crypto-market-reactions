import { describe, expect, it } from "vitest";

import { isValidEventSlug, nextUtcDate, parseEventsQuery, QueryValidationError } from "./events-query";

describe("parseEventsQuery", () => {
  it("trims search and applies safe defaults", () => {
    expect(parseEventsQuery(new URLSearchParams("q=%20ethereum%20etf%20"))).toMatchObject({
      query: "ethereum etf",
      asset: null,
      sort: "newest",
      horizon: "average",
      marketDataOnly: false,
      page: 1,
      pageSize: 25,
    });
  });

  it("caps pageSize=1000 at 50", () => {
    expect(parseEventsQuery(new URLSearchParams("pageSize=1000")).pageSize).toBe(50);
    expect(parseEventsQuery(new URLSearchParams("limit=100000")).pageSize).toBe(50);
    expect(parseEventsQuery(new URLSearchParams("pageSize=999999")).pageSize).toBe(50);
  });

  it("accepts combined filters", () => {
    expect(
      parseEventsQuery(
        new URLSearchParams("q=ethereum+etf&asset=eth&from=2023-01-01&to=2025-12-31"),
      ),
    ).toMatchObject({ asset: "ETH", from: "2023-01-01", to: "2025-12-31" });
  });

  it("rejects malformed and excessive values", () => {
    expect(() => parseEventsQuery(new URLSearchParams("page=-1"))).toThrow(QueryValidationError);
    expect(() => parseEventsQuery(new URLSearchParams("page=0"))).toThrow(QueryValidationError);
    expect(() => parseEventsQuery(new URLSearchParams("page=invalid"))).toThrow(
      QueryValidationError,
    );
    expect(() => parseEventsQuery(new URLSearchParams("limit=-1"))).toThrow(QueryValidationError);
    expect(() => parseEventsQuery(new URLSearchParams("asset=XRP"))).toThrow(QueryValidationError);
    expect(() => parseEventsQuery(new URLSearchParams("from=2025-02-30"))).toThrow(
      QueryValidationError,
    );
  });

  it("validates sort against its allowlist", () => {
    expect(parseEventsQuery(new URLSearchParams("sort=oldest")).sort).toBe("oldest");
    expect(() => parseEventsQuery(new URLSearchParams("sort=drop-table"))).toThrow(
      QueryValidationError,
    );
  });

  it("validates all reaction horizons", () => {
    expect(parseEventsQuery(new URLSearchParams("horizon=15m")).horizon).toBe("15m");
    expect(() => parseEventsQuery(new URLSearchParams("horizon=2d"))).toThrow(
      QueryValidationError,
    );
  });

  it("rejects reaction sorting without an asset", () => {
    expect(() => parseEventsQuery(new URLSearchParams("sort=growth"))).toThrow(
      "Select BTC, ETH, or SOL",
    );
  });

  it("accepts market-data filtering with a selected asset", () => {
    expect(
      parseEventsQuery(new URLSearchParams("asset=SOL&horizon=4h&marketDataOnly=true")),
    ).toMatchObject({ asset: "SOL", horizon: "4h", marketDataOnly: true });
    expect(() => parseEventsQuery(new URLSearchParams("marketDataOnly=true"))).toThrow(
      QueryValidationError,
    );
  });
});

describe("event helpers", () => {
  it("validates canonical slugs", () => {
    expect(isValidEventSlug("ethereum-etf-approved-2024-a1b2c3d4")).toBe(true);
    expect(isValidEventSlug("../unsafe")).toBe(false);
  });

  it("creates an exclusive UTC upper date bound", () => {
    expect(nextUtcDate("2024-02-29")).toBe("2024-03-01T00:00:00.000Z");
  });
});
