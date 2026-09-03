import { describe, expect, it } from "vitest";

import { assertNoQueryParameters, parseEventIdReference, parseEventsQuery, parseReactionsQuery } from "@/lib/api-v1/validation";
import { ApiV1Error } from "@/lib/api-v1/errors";

const request = (path: string) => new Request(`http://localhost${path}`);

describe("API V1 query validation", () => {
  it("applies bounded events defaults", () => {
    expect(parseEventsQuery(request("/api/v1/events"))).toMatchObject({ limit: 50, search: "", asset: null, cursor: null });
  });

  it.each([
    "/api/v1/events?limit=101",
    "/api/v1/events?limit=1&limit=2",
    "/api/v1/events?asset=DROP%20TABLE%20events",
    "/api/v1/events?unknown=events",
    "/api/v1/events?dateFrom=2025-02-30",
    "/api/v1/events?dateFrom=2010-01-01&dateTo=2025-01-01",
  ])("rejects invalid events query %s", (path) => {
    expect(() => parseEventsQuery(request(path))).toThrowError(ApiV1Error);
  });

  it("accepts SQL-like text only as a bounded search string", () => {
    const query = parseEventsQuery(request("/api/v1/events?search=SELECT%20*%20FROM%20events%3B--"));
    expect(query.search).toBe("SELECT * FROM events;--");
  });

  it("requires an allowlisted reaction asset and validates all filters", () => {
    expect(() => parseReactionsQuery(request("/api/v1/reactions"))).toThrowError(ApiV1Error);
    expect(() => parseReactionsQuery(request("/api/v1/reactions?asset=BTC&horizon=2h"))).toThrowError(ApiV1Error);
    expect(parseReactionsQuery(request("/api/v1/reactions?asset=SOL&topic=hack&direction=negative"))).toMatchObject({
      asset: "SOL", topic: "hack", direction: "negative", horizon: null,
    });
  });

  it("rejects parameters on fixed metadata endpoints", () => {
    expect(() => assertNoQueryParameters(request("/api/v1/meta?fields=secrets"))).toThrowError(ApiV1Error);
    expect(() => assertNoQueryParameters(request("/api/v1/meta"))).not.toThrow();
  });

  it.each(["evt18-f8f02c2fa52c8b617f08", "bf3-1e87e26fd5d94c022992"])("accepts production event ID format %s", (eventId) => {
    expect(parseEventIdReference(eventId)).toBe(eventId);
  });

  it.each(["", "../event", "event id", "event.id", "évent", "x".repeat(97)])("rejects malformed event ID reference %s", (eventId) => {
    expect(() => parseEventIdReference(eventId)).toThrowError(ApiV1Error);
  });
});
