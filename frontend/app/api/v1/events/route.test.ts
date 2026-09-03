import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PublicEvent } from "@/lib/api-v1/types";

const mocks = vi.hoisted(() => ({
  listEvents: vi.fn(),
  getEventBySlug: vi.fn(),
}));

vi.mock("@/lib/api-v1/data", () => ({
  getApiV1DataService: () => mocks,
}));

import { GET as getEvents } from "@/app/api/v1/events/route";
import { GET as getEvent } from "@/app/api/v1/events/[slug]/route";

const API_KEY = "test-cmr-api-key-0123456789abcdef";
const EVENT: PublicEvent = {
  id: "evt18-api-test",
  slug: "api-test-event",
  title: "API test event",
  publishedAt: "2025-05-01T12:00:00.000Z",
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

  it("emits and verifies a bounded cursor", async () => {
    mocks.listEvents.mockResolvedValueOnce({ items: [EVENT], hasMore: true });
    const first = await getEvents(request("/api/v1/events?limit=1"));
    const cursor = (await first.json()).pagination.nextCursor;
    expect(cursor).toEqual(expect.any(String));
    mocks.listEvents.mockResolvedValueOnce({ items: [], hasMore: false });
    const second = await getEvents(request(`/api/v1/events?limit=1&cursor=${encodeURIComponent(cursor)}`));
    expect(second.status).toBe(200);
    expect(mocks.listEvents).toHaveBeenLastCalledWith(expect.objectContaining({
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

