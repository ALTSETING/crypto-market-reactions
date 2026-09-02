import { describe, expect, it } from "vitest";

import {
  buildEventSeoDescription,
  buildEventSeoTitle,
  buildWebPageStructuredData,
  buildWebsiteStructuredData,
  HOME_DESCRIPTION,
  HOME_TITLE,
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
    expect(title).toContain("ETH Reaction to");
    expect(title).toContain("2024-05-23");
    expect(title.endsWith("| Crypto Market Reactions")).toBe(true);
    expect(event.title).toContain("Latest Public Filings");
  });

  it("builds a deterministic, data-based description", () => {
    const description = buildEventSeoDescription(event);
    expect(description.length).toBeGreaterThanOrEqual(140);
    expect(description.length).toBeLessThanOrEqual(170);
    expect(description).toContain("Ethereum");
    expect(description).toContain("SEC");
    expect(description).toContain("2024-05-23");
    expect(description).toContain("24h");
    expect(buildEventSeoDescription(event)).toBe(description);
  });

  it("uses the approved homepage title and description", () => {
    expect(HOME_TITLE).toBe("Crypto Market Reactions — Historical BTC, ETH & SOL Event Analysis");
    expect(HOME_DESCRIPTION).toBe("See how Bitcoin, Ethereum and Solana reacted after ETFs, SEC actions, hacks, institutional flows and other crypto events using historical Reaction V2 data.");
  });

  it("builds WebSite, WebPage and breadcrumb schema without claiming an article", () => {
    const website = buildWebsiteStructuredData();
    const page = buildWebPageStructuredData({
      name: event.title,
      description: buildEventSeoDescription(event),
      path: `/events/${event.slug}`,
      breadcrumbs: [{ name: "Home", path: "/" }, { name: "Events", path: "/events" }],
      citation: "https://example.com/source",
    });
    expect(website["@type"]).toBe("WebSite");
    expect(page["@graph"].map((node) => node["@type"])).toEqual(["WebPage", "BreadcrumbList"]);
    expect(JSON.stringify(page)).not.toContain("NewsArticle");
    expect(JSON.stringify(page)).not.toContain('"@type":"Article"');
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
