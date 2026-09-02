import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/cache", () => ({ unstable_cache: (callback: unknown) => callback }));
vi.mock("@/lib/data/events", () => ({
  getSitemapEvents: vi.fn(async () => [
    { slug: "first-event-2024-a1b2c3d4", updated_at: "2024-01-02T00:00:00.000Z" },
    { slug: "second-event-2025-b2c3d4e5", updated_at: "2025-02-03T00:00:00.000Z" },
  ]),
}));

describe("sitemap", () => {
  beforeEach(() => {
    process.env.SITE_URL = "https://crypto.example";
  });

  it("lists core, allowlisted topic and event URLs without query parameters", async () => {
    const { default: sitemap } = await import("./sitemap");
    const rows = await sitemap();
    const urls = rows.map(({ url }) => url);
    expect(urls).toHaveLength(13);
    expect(urls.slice(0, 3)).toEqual([
      "https://crypto.example/",
      "https://crypto.example/events",
      "https://crypto.example/ai",
    ]);
    expect(urls.filter((url) => url.includes("/topics/"))).toHaveLength(8);
    expect(urls.filter((url) => url.includes("/events/")).length).toBe(2);
    expect(urls.every((url) => !url.includes("?") && !url.includes("#"))).toBe(true);
    expect(new Set(urls).size).toBe(urls.length);
  });
});
