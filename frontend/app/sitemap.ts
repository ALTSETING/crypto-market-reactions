import type { MetadataRoute } from "next";
import { unstable_cache } from "next/cache";

import { getSitemapEvents } from "@/lib/data/events";
import { siteUrl } from "@/lib/seo";

export const dynamic = "force-dynamic";

const getCachedSitemapEvents = unstable_cache(getSitemapEvents, ["public-events-sitemap"], {
  revalidate: 3_600,
  tags: ["public-events-sitemap"],
});

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const events = await getCachedSitemapEvents();
  return [
    { url: siteUrl("/") },
    ...events.map((event) => ({
      url: siteUrl(`/events/${event.slug}`),
      lastModified: event.updated_at,
    })),
  ];
}
