import { describe, expect, it } from "vitest";

import {
  buildEventSeoDescription,
  buildEventSeoTitle,
  resolveSiteUrl,
  siteUrl,
  type SeoEventData,
} from "./seo";

const event: SeoEventData = {
  slug: "sec-delays-ethereum-etf-decision-2024-a1b2c3d4",
  title: "SEC Delays Ethereum ETF Decision After Reviewing the Latest Public Filings",
  published_at: "2024-05-23T12:30:00.000Z",
  source: "SEC",
  primary_asset: "ETH",
  related_assets: ["ETH"],
};

describe("SEO helpers", () => {
  it("builds a readable bounded event title without changing the source title", () => {
    const title = buildEventSeoTitle(event);
    expect(title.length).toBeLessThanOrEqual(65);
    expect(title).toContain("ETH Price Reaction");
    expect(title).toContain("2024-05-23");
    expect(title).toContain("a1b2c3d4");
    expect(event.title).toContain("Latest Public Filings");
  });

  it("builds a deterministic, data-based description", () => {
    const description = buildEventSeoDescription(event);
    expect(description.length).toBeGreaterThanOrEqual(140);
    expect(description.length).toBeLessThanOrEqual(170);
    expect(description).toContain("Ethereum");
    expect(description).toContain("SEC");
    expect(description).toContain("24h");
    expect(buildEventSeoDescription(event)).toBe(description);
  });

  it("prefers SITE_URL and normalizes its trailing slash", () => {
    expect(resolveSiteUrl({ SITE_URL: "https://crypto.example/", VERCEL_PROJECT_PRODUCTION_URL: "ignored.vercel.app" }).toString()).toBe("https://crypto.example/");
    expect(siteUrl("/events/example", { SITE_URL: "https://crypto.example", VERCEL_PROJECT_PRODUCTION_URL: undefined })).toBe("https://crypto.example/events/example");
  });

  it("uses the stable Vercel production domain, never a preview URL", () => {
    expect(resolveSiteUrl({ SITE_URL: undefined, VERCEL_PROJECT_PRODUCTION_URL: "market.example" }).toString()).toBe("https://market.example/");
  });

  it("rejects unsafe site URL configuration", () => {
    expect(() => resolveSiteUrl({ SITE_URL: "javascript:alert(1)", VERCEL_PROJECT_PRODUCTION_URL: undefined })).toThrow();
    expect(() => resolveSiteUrl({ SITE_URL: "https://user:pass@example.com", VERCEL_PROJECT_PRODUCTION_URL: undefined })).toThrow();
  });
});
