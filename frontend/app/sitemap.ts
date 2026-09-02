import type { MetadataRoute } from "next";
import { unstable_cache } from "next/cache";

import { getSitemapEvents } from "@/lib/data/events";
import { siteUrl } from "@/lib/seo";
import { SEO_TOPIC_LANDINGS } from "@/lib/seo-topics";

export const dynamic = "force-dynamic";

const getCachedSitemapEvents = unstable_cache(getSitemapEvents, ["public-events-sitemap-v9073"], {
  revalidate: 3_600,
  tags: ["public-events-sitemap"],
});

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const events = await getCachedSitemapEvents();
  return [
    { url: siteUrl("/"), changeFrequency: "weekly", priority: 1 },
    { url: siteUrl("/events"), changeFrequency: "daily", priority: 0.9 },
    { url: siteUrl("/ai"), changeFrequency: "monthly", priority: 0.7 },
    ...SEO_TOPIC_LANDINGS.map((topic) => ({
      url: siteUrl(`/topics/${topic.slug}`),
      changeFrequency: "weekly" as const,
      priority: 0.8,
    })),
    ...events.map((event) => ({
      url: siteUrl(`/events/${event.slug}`),
      lastModified: event.updated_at,
      changeFrequency: "monthly" as const,
      priority: 0.6,
    })),
  ];
}
