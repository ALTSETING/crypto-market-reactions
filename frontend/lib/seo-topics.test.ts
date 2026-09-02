import { describe, expect, it } from "vitest";

import { getSeoTopicLanding, SEO_TOPIC_LANDINGS } from "./seo-topics";

describe("SEO topic landing allowlist", () => {
  it("contains only the eight evidence-backed topic pages", () => {
    expect(SEO_TOPIC_LANDINGS.map(({ slug }) => slug)).toEqual([
      "bitcoin-etf", "ethereum-etf", "sec-enforcement", "crypto-hacks",
      "institutional-buying", "etf-inflows", "etf-outflows", "fed-rate-decisions",
    ]);
  });

  it("uses unique, bounded metadata and stable slugs", () => {
    const titles = SEO_TOPIC_LANDINGS.map(({ seoTitle }) => seoTitle);
    const descriptions = SEO_TOPIC_LANDINGS.map(({ description }) => description);
    expect(new Set(titles).size).toBe(titles.length);
    expect(new Set(descriptions).size).toBe(descriptions.length);
    for (const topic of SEO_TOPIC_LANDINGS) {
      expect(topic.slug).toMatch(/^[a-z0-9]+(?:-[a-z0-9]+)*$/);
      expect(topic.seoTitle.length).toBeLessThanOrEqual(65);
      expect(topic.description.length).toBeGreaterThanOrEqual(100);
      expect(topic.description.length).toBeLessThanOrEqual(170);
    }
  });

  it("does not generate arbitrary or combinatorial topic routes", () => {
    expect(getSeoTopicLanding("bitcoin-etf")).toMatchObject({ asset: "BTC", topic: "etf" });
    expect(getSeoTopicLanding("dogecoin-etf")).toBeNull();
    expect(getSeoTopicLanding("bitcoin-etf-2026")).toBeNull();
  });
});
