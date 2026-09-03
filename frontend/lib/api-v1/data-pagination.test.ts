import { describe, expect, it } from "vitest";

import type { SupabaseClient } from "@supabase/supabase-js";

import { ApiV1DataService, type EventsDataParams } from "@/lib/api-v1/data";
import { ASSETS, HORIZONS } from "@/types/events";

interface Row {
  event_id: string;
  slug: string;
  title: string;
  published_at: string;
  source: string;
  source_url: string;
  primary_asset: "ETH";
  related_assets: ["ETH"];
  category: "news";
  source_class_v2: "news_media";
  [key: string]: unknown;
}

interface QueryResult {
  data: Row[];
  error: null;
}

function row(id: string, publishedAt: string): Row {
  return {
    event_id: id,
    slug: id,
    title: `Event ${id}`,
    published_at: publishedAt,
    source: "test-source",
    source_url: "https://example.com/event",
    primary_asset: "ETH",
    related_assets: ["ETH"],
    category: "news",
    source_class_v2: "news_media",
    ...Object.fromEntries(ASSETS.flatMap((asset) => HORIZONS.map((horizon) => [`${asset.toLowerCase()}_${horizon}`, null]))),
  };
}

function fakeClient(sourceRows: Row[]): SupabaseClient {
  return {
    from: () => ({
      select: () => {
        let rows = [...sourceRows];
        let maximum = Number.POSITIVE_INFINITY;
        const order: Array<{ column: string; ascending: boolean }> = [];
        const builder = {
          contains(column: string, value: unknown) {
            if (column === "related_assets" && Array.isArray(value)) {
              rows = rows.filter((item) => value.every((asset) => item.related_assets.includes(asset as "ETH")));
            }
            return builder;
          },
          eq(column: string, value: unknown) {
            rows = rows.filter((item) => item[column] === value);
            return builder;
          },
          gte(column: string, value: unknown) {
            rows = rows.filter((item) => String(item[column]) >= String(value));
            return builder;
          },
          lte(column: string, value: unknown) {
            rows = rows.filter((item) => String(item[column]) <= String(value));
            return builder;
          },
          textSearch(_column: string, query: string) {
            rows = rows.filter((item) => item.title.toLowerCase().includes(query.toLowerCase()));
            return builder;
          },
          or(filters: string) {
            const equalMarker = ",and(published_at.eq.";
            const idMarker = ",event_id.gt.";
            const equalStart = filters.indexOf(equalMarker);
            const idStart = filters.indexOf(idMarker, equalStart + equalMarker.length);
            const olderThan = filters.slice("published_at.lt.".length, equalStart);
            const equalTo = filters.slice(equalStart + equalMarker.length, idStart);
            const greaterThanId = filters.slice(idStart + idMarker.length, -1);
            rows = rows.filter((item) => item.published_at < olderThan
              || (item.published_at === equalTo && item.event_id > greaterThanId));
            return builder;
          },
          order(column: string, options: { ascending: boolean }) {
            order.push({ column, ascending: options.ascending });
            return builder;
          },
          limit(count: number) {
            maximum = count;
            return builder;
          },
          then<TResult1 = QueryResult, TResult2 = never>(
            onfulfilled?: ((value: QueryResult) => TResult1 | PromiseLike<TResult1>) | null,
            onrejected?: ((reason: unknown) => TResult2 | PromiseLike<TResult2>) | null,
          ): Promise<TResult1 | TResult2> {
            const sorted = [...rows].sort((left, right) => {
              for (const field of order) {
                const leftValue = String(left[field.column]);
                const rightValue = String(right[field.column]);
                if (leftValue === rightValue) continue;
                const comparison = leftValue < rightValue ? -1 : 1;
                return field.ascending ? comparison : -comparison;
              }
              return 0;
            });
            return Promise.resolve({ data: sorted.slice(0, maximum), error: null }).then(onfulfilled, onrejected);
          },
        };
        return builder;
      },
    }),
  } as unknown as SupabaseClient;
}

const params: EventsDataParams = {
  asset: "ETH",
  topic: null,
  category: null,
  sourceClass: null,
  dateFrom: null,
  dateTo: null,
  search: "",
  limit: 2,
  cursor: null,
};

describe("API V1 event cursor boundary", () => {
  it("uses published_at DESC plus event_id ASC without duplicating or skipping the boundary", async () => {
    const timestamp = "2026-07-01T00:00:00+00:00";
    const service = new ApiV1DataService(fakeClient([
      row("event-d", "2026-06-30T23:59:59+00:00"),
      row("event-c", timestamp),
      row("event-a", timestamp),
      row("event-b", timestamp),
    ]));

    const first = await service.listEvents(params);
    expect(first.items.map((item) => item.id)).toEqual(["event-a", "event-b"]);
    expect(first.hasMore).toBe(true);

    const boundary = first.items.at(-1)!;
    const second = await service.listEvents({
      ...params,
      cursor: { publishedAt: boundary.publishedAt, id: boundary.id },
    });
    expect(second.items.map((item) => item.id)).toEqual(["event-c", "event-d"]);
    expect(second.hasMore).toBe(false);
    expect([...first.items, ...second.items].map((item) => item.id)).toEqual([
      "event-a", "event-b", "event-c", "event-d",
    ]);
  });
});
