import { describe, expect, it, vi } from "vitest";

import type { SupabaseClient } from "@supabase/supabase-js";

import { ApiV1DataService } from "@/lib/api-v1/data";
import { ASSETS, HORIZONS } from "@/types/events";

const EVENT_ID = "evt18-f8f02c2fa52c8b617f08";
const DATABASE_ROW = {
  event_id: EVENT_ID,
  slug: "exact-id-lookup-event",
  title: "Exact ID lookup event",
  published_at: "2026-07-01T00:00:00+00:00",
  source: "test-source",
  source_url: "https://example.com/event",
  primary_asset: "ETH",
  related_assets: ["ETH"],
  category: "news",
  source_class_v2: "news_media",
  ...Object.fromEntries(ASSETS.flatMap((asset) => HORIZONS.map((horizon) => [
    `${asset.toLowerCase()}_${horizon}`,
    asset === "ETH" && horizon === "1h" ? 0.5 : null,
  ]))),
};

describe("API V1 event ID data lookup", () => {
  it("uses one exact primary-key equality query and the shared public serializer", async () => {
    const maybeSingle = vi.fn().mockResolvedValue({ data: DATABASE_ROW, error: null });
    const limit = vi.fn().mockReturnValue({ maybeSingle });
    const eq = vi.fn().mockReturnValue({ limit });
    const select = vi.fn().mockReturnValue({ eq });
    const from = vi.fn().mockReturnValue({ select });
    const service = new ApiV1DataService({ from } as unknown as SupabaseClient);

    const event = await service.getEventById(EVENT_ID);

    expect(from).toHaveBeenCalledOnce();
    expect(from).toHaveBeenCalledWith("events");
    expect(eq).toHaveBeenCalledOnce();
    expect(eq).toHaveBeenCalledWith("event_id", EVENT_ID);
    expect(limit).toHaveBeenCalledOnce();
    expect(limit).toHaveBeenCalledWith(1);
    expect(maybeSingle).toHaveBeenCalledOnce();
    expect(event).toMatchObject({
      id: EVENT_ID,
      slug: DATABASE_ROW.slug,
      source: DATABASE_ROW.source,
      sourceUrl: DATABASE_ROW.source_url,
      reactionV2: { ETH: { "1h": 0.5 } },
    });
    expect(event).not.toHaveProperty("event_id");
  });
});
