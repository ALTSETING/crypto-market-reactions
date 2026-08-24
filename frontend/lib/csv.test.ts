import { describe, expect, it } from "vitest";

import { CSV_MAX_ROWS, serializeCurrentPageCsv } from "./csv";
import type { EventListItem } from "@/types/events";

function event(index: number): EventListItem {
  return {
    event_id: `event-${index}`,
    slug: `event-${index}-a1b2c3d4`,
    title: index === 0 ? '=HYPERLINK("unsafe")' : `Event ${index}`,
    published_at: "2026-01-01T00:00:00Z",
    source: "source",
    source_type: "news_media",
    primary_asset: "BTC",
    related_assets: ["BTC", "ETH"],
    category: "market",
    sentiment: null,
    importance: null,
    btc_1m: null,
    btc_5m: null,
    btc_15m: null,
    btc_1h: 1,
    btc_4h: null,
    btc_24h: 2,
    btc_average_reaction: null,
    eth_1m: null,
    eth_5m: null,
    eth_15m: null,
    eth_1h: 3,
    eth_4h: null,
    eth_24h: 4,
    eth_average_reaction: null,
    sol_1m: null,
    sol_5m: null,
    sol_15m: null,
    sol_1h: null,
    sol_4h: null,
    sol_24h: null,
    sol_average_reaction: null,
  };
}

describe("current-page CSV", () => {
  it("never serializes more than the bounded current page", () => {
    const csv = serializeCurrentPageCsv(
      Array.from({ length: CSV_MAX_ROWS + 25 }, (_, index) => event(index)),
    );
    expect(csv.trimEnd().split("\r\n")).toHaveLength(CSV_MAX_ROWS + 1);
    expect(csv).not.toContain(`event-${CSV_MAX_ROWS + 1}`);
  });

  it("escapes spreadsheet formulas and preserves selected reactions", () => {
    const csv = serializeCurrentPageCsv([event(0)]);
    expect(csv).toContain(`"'=HYPERLINK(""unsafe"")"`);
    expect(csv).toContain('"BTC|ETH"');
    expect(csv).toContain('"News media"');
    expect(csv).toContain('"1","2","3","4"');
  });
});
