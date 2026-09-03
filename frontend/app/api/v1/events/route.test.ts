import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PublicEvent } from "@/lib/api-v1/types";

const mocks = vi.hoisted(() => ({
  listEvents: vi.fn(),
  getEventById: vi.fn(),
  getEventBySlug: vi.fn(),
}));

vi.mock("@/lib/api-v1/data", () => ({
  getApiV1DataService: () => mocks,
}));

import { GET as getEvents } from "@/app/api/v1/events/route";
import { GET as getEvent } from "@/app/api/v1/events/[slug]/route";
import { GET as getEventById } from "@/app/api/v1/events/by-id/[eventId]/route";

const API_KEY = "test-cmr-api-key-0123456789abcdef";
const EVENT: PublicEvent = {
  id: "evt18-api-test",
  slug: "api-test-event",
  title: "API test event",
  publishedAt: "2025-05-01T12:00:00+00:00",
  source: "test-source",
  sourceUrl: "https://example.com/event",
  primaryAsset: "BTC",
  relatedAssets: ["BTC"],
  category: "etf",
  sourceClass: "news_media",
  reactionV2: {
    BTC: { "1m": 0.1, "5m": 0.2, "15m": null, "1h": 0.4, "4h": 0.5, "24h": 0.6 },
    ETH: { "1m": null, "5m": null, "15m": null, "1h": null, "4h": null, "24h": null },
    SOL: { "1m": null, "5m": null, "15m": null, "1h": null, "4h": null, "24h": null },
  },
};

function request(path: string, key = API_KEY): Request {
  return new Request(`http://localhost${path}`, { headers: { authorization: `Bearer ${key}` } });
}

describe("GET /api/v1/events", () => {
  beforeEach(() => {
    process.env.CMR_API_KEY = API_KEY;
    mocks.listEvents.mockReset().mockResolvedValue({ items: [EVENT], hasMore: false });
    mocks.getEventById.mockReset().mockResolvedValue(EVENT);
    mocks.getEventBySlug.mockReset().mockResolvedValue(EVENT);
  });

  it("returns only the public contract and preserves Reaction V2 nulls", async () => {
    const response = await getEvents(request("/api/v1/events?asset=BTC&limit=1"));
    const body = await response.json();
    expect(response.status).toBe(200);
    expect(body.data[0]).toEqual(EVENT);
    expect(body.data[0].reactionV2.BTC["15m"]).toBeNull();
    expect(JSON.stringify(body)).not.toMatch(/service_role|confidence|archive_|prompt|stack/i);
    expect(mocks.listEvents).toHaveBeenCalledWith(expect.objectContaining({ asset: "BTC", limit: 1 }));
  });

  it("accepts its Supabase-format cursor with the same filters and without filters", async () => {
    mocks.listEvents.mockResolvedValueOnce({ items: [EVENT], hasMore: true });
    const first = await getEvents(request("/api/v1/events?asset=BTC&category=etf&search=API&limit=1"));
    const cursor = (await first.json()).pagination.nextCursor;
    expect(cursor).toEqual(expect.any(String));
    mocks.listEvents.mockResolvedValueOnce({ items: [], hasMore: false });
    const second = await getEvents(request(`/api/v1/events?asset=BTC&category=etf&search=API&limit=1&cursor=${encodeURIComponent(cursor)}`));
    expect(second.status).toBe(200);
    expect(mocks.listEvents).toHaveBeenLastCalledWith(expect.objectContaining({
      asset: "BTC",
      category: "etf",
      search: "API",
      cursor: { id: EVENT.id, publishedAt: EVENT.publishedAt },
    }));

    mocks.listEvents.mockResolvedValueOnce({ items: [], hasMore: false });
    const cursorOnly = await getEvents(request(`/api/v1/events?cursor=${encodeURIComponent(cursor)}`));
    expect(cursorOnly.status).toBe(200);
    expect(mocks.listEvents).toHaveBeenLastCalledWith(expect.objectContaining({
      asset: null,
      category: null,
      search: "",
      cursor: { id: EVENT.id, publishedAt: EVENT.publishedAt },
    }));
  });

  it("rejects invalid filters, forged cursors, and oversized requests", async () => {
    expect((await getEvents(request("/api/v1/events?limit=101"))).status).toBe(400);
    expect((await getEvents(request("/api/v1/events?cursor=forged-cursor-value"))).status).toBe(400);
    expect((await getEvents(request(`/api/v1/events?search=${"x".repeat(2_100)}`))).status).toBe(400);
  });

  it("treats SQL injection syntax as inert text search input", async () => {
    const value = "'; DROP TABLE events; --";
    const response = await getEvents(request(`/api/v1/events?search=${encodeURIComponent(value)}`));
    expect(response.status).toBe(200);
    expect(mocks.listEvents).toHaveBeenCalledWith(expect.objectContaining({ search: value }));
  });
});

describe("GET /api/v1/events/{slug}", () => {
  beforeEach(() => {
    process.env.CMR_API_KEY = API_KEY;
    mocks.getEventBySlug.mockReset().mockResolvedValue(EVENT);
  });

  it("returns a single event", async () => {
    const response = await getEvent(request("/api/v1/events/api-test-event"), { params: Promise.resolve({ slug: "api-test-event" }) });
    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toEqual({ data: EVENT });
  });

  it("returns a real 404 for an unknown or malformed slug", async () => {
    mocks.getEventBySlug.mockResolvedValueOnce(null);
    const missing = await getEvent(request("/api/v1/events/missing-event"), { params: Promise.resolve({ slug: "missing-event" }) });
    const malformed = await getEvent(request("/api/v1/events/bad"), { params: Promise.resolve({ slug: "../bad" }) });
    expect(missing.status).toBe(404);
    expect(malformed.status).toBe(404);
    await expect(missing.json()).resolves.toMatchObject({ error: { code: "EVENT_NOT_FOUND" } });
  });
});

describe("GET /api/v1/events/by-id/{eventId}", () => {
  beforeEach(() => {
    process.env.CMR_API_KEY = API_KEY;
    mocks.getEventById.mockReset().mockResolvedValue(EVENT);
    mocks.getEventBySlug.mockReset().mockResolvedValue(EVENT);
  });

  it("returns the same serialized event as the existing slug lookup", async () => {
    const byId = await getEventById(request(`/api/v1/events/by-id/${EVENT.id}`), {
      params: Promise.resolve({ eventId: EVENT.id }),
    });
    const bySlug = await getEvent(request(`/api/v1/events/${EVENT.slug}`), {
      params: Promise.resolve({ slug: EVENT.slug }),
    });
    const idBody = await byId.json();
    const slugBody = await bySlug.json();

    expect(byId.status).toBe(200);
    expect(bySlug.status).toBe(200);
    expect(idBody.data).toEqual(slugBody.data);
    expect(idBody.data).toMatchObject({ id: EVENT.id, slug: EVENT.slug, reactionV2: EVENT.reactionV2 });
    expect(mocks.getEventById).toHaveBeenCalledWith(EVENT.id);
  });

  it("returns 404 for an unknown structurally valid event ID", async () => {
    mocks.getEventById.mockResolvedValueOnce(null);
    const eventId = "evt18-00000000000000000000";
    const response = await getEventById(request(`/api/v1/events/by-id/${eventId}`), {
      params: Promise.resolve({ eventId }),
    });
    expect(response.status).toBe(404);
    await expect(response.json()).resolves.toMatchObject({ error: { code: "EVENT_NOT_FOUND" } });
  });

  it.each(["../bad", "event id", "x".repeat(97)])("returns 400 for invalid event ID %s", async (eventId) => {
    const response = await getEventById(request(`/api/v1/events/by-id/${encodeURIComponent(eventId)}`), {
      params: Promise.resolve({ eventId }),
    });
    expect(response.status).toBe(400);
    await expect(response.json()).resolves.toMatchObject({ error: { code: "INVALID_PARAMETER" } });
    expect(mocks.getEventById).not.toHaveBeenCalled();
  });

  it("rejects query parameters instead of turning the lookup into search", async () => {
    const response = await getEventById(request(`/api/v1/events/by-id/${EVENT.id}?search=ETF`), {
      params: Promise.resolve({ eventId: EVENT.id }),
    });
    expect(response.status).toBe(400);
    expect(mocks.getEventById).not.toHaveBeenCalled();
  });
});
