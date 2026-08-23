# SEO MVP report

Date: 2026-08-23

## 1. Event route architecture

One Next.js App Router route, `frontend/app/events/[slug]/page.tsx`, serves every
public event. It resolves the unique database `slug` with a server-side,
single-row Supabase query. No event pages are maintained manually.

## 2. SSR and caching strategy

Event content is rendered in the initial server response, so crawlers receive
the title, publication date, source, classification, assets, and available
market reactions without client-side fetching. Event lookups use React request
memoization plus a one-hour Next.js cross-request cache/revalidation window.
Pages are rendered on demand; the deploy does not issue 7,878 per-page build
queries. The sitemap lookup is separately cached for one hour.

## 3. Metadata generation

`generateMetadata` uses the resolved event record. SEO titles are deterministic,
readable, limited to 65 characters, and disambiguated from the slug when a long
title must be shortened. The full visible event heading is never shortened.
Descriptions are deterministic, based only on real event fields and reaction
horizons, and target 140-170 characters. No LLM or external generation API is
used.

An offline full-dataset audit found 7,878 unique generated titles. Descriptions
were 140-169 characters; 7,759 were unique, with 52 duplicate groups where the
underlying event wording/classification is substantially the same.

## 4. Canonical strategy

`frontend/lib/seo.ts` is the only site-origin resolver. It prefers `SITE_URL`,
falls back to Vercel's stable `VERCEL_PROJECT_PRODUCTION_URL`, and uses
`http://localhost:3000` only outside a configured deployment. Event canonicals
are always `/events/<slug>`. Query-state event URLs canonicalize to the clean
event URL and are marked `noindex,follow`.

## 5. Open Graph and Twitter

Every valid event exposes `og:title`, `og:description`, `og:url`, `og:type` set
to `article`, `og:site_name`, publication time, and a basic Twitter summary
card with title and description. No fabricated event image is declared.

## 6. Sitemap implementation

`frontend/app/sitemap.ts` generates `/sitemap.xml` from Supabase in batches of
1,000 rows. It contains the homepage and every public event, uses `updated_at`
for event `lastmod`, rejects missing/duplicate slugs, and excludes query URLs,
API routes, and invalid slugs. The sitemap fetch is isolated so it can be split
with a sitemap index later if the collection approaches 50,000 URLs.

## 7. Robots implementation

`frontend/app/robots.ts` generates `/robots.txt`. It allows `/`, disallows
`/api/`, does not block `/events/`, and publishes the central sitemap URL.

## 8. Structured data

Each event emits minimal schema.org `Article` JSON-LD with only real values:
`headline`, `datePublished`, canonical `url`, and source as the publisher name.
No author, logo, or image is invented.

## 9. Search and noindex strategy

The clean homepage is indexable and canonical to `/`. Any homepage search,
filter, sorting, pagination, or other query state is `noindex,follow` and
canonical to the clean homepage. Event URLs with query parameters follow the
same rule and canonicalize to their query-free event URL.

## 10. 404 handling

An unknown or invalid slug calls Next.js `notFound()` and returns HTTP 404; it
does not return a synthetic event with HTTP 200. Missing-event metadata is also
marked noindex.

## 11. Internal linking and original source

Event pages link back to all events, to filtered searches for the primary and
related assets, and to the source filter. A separate original-source link opens
the real external URL with `target="_blank"` and `rel="noopener noreferrer"`.
The source article body is not copied.

## 12. Production build result

`npm run build` passed with Next.js 16.3.2. The relevant build routes are:

```text
ƒ /
ƒ /events/[slug]
ƒ /sitemap.xml
○ /robots.txt
```

The event route and sitemap are server-rendered on demand; robots is static.
ESLint, TypeScript, all 29 unit tests, and the 25-file client-bundle credential
scan also passed.

## 13. Sitemap URL count

The production-build HTTP audit found 7,879 unique URLs: one homepage and
exactly 7,878 event URLs. It found no duplicates, malformed URLs, query strings,
or fragments. All 7,878 event entries have a parseable real `lastmod` value.

## 14. Smoke-test result

`npm run smoke:seo` passed against `next start`:

- 100 seeded-random slugs returned HTTP 200 without redirects, self-canonicalized,
  rendered the matching event headline/JSON-LD, and had 100 unique SEO titles;
- 20 event pages passed detailed HTML, metadata, canonical, Open Graph, Twitter,
  JSON-LD, source-link, reaction-data, and indexability checks;
- five nonexistent slugs returned HTTP 404;
- filtered homepage and query-state event pages returned `noindex,follow` with
  clean canonicals;
- robots and sitemap output passed HTTP/content validation.

`npm run smoke:browser` also passed all eight UI checks, including mobile
overflow, reaction sorting, filters, and search only on Enter/Search rather
than after each typed letter.

## 15. Known SEO and deployment limitations

- `SITE_URL` is not present in the local environment, so local verification
  correctly used `http://localhost:3000`. Set the production origin in Vercel
  before the next production deployment and repeat the smoke test against it.
- No event-specific or shared social image is currently declared.
- Some deterministic descriptions repeat for near-identical underlying events;
  titles and canonical URLs remain unique.
- The sitemap is one file while the collection remains below 50,000 URLs.
- Crawl discovery and indexing depend on deployment, Search Console submission,
  Google crawl scheduling, and content-quality assessment; code cannot guarantee
  indexing.
- Database verification confirmed 7,878 unique event IDs/slugs, RLS, expected
  indexes, FTS, and unchanged classifications. The later dataset-access
  security cutover removed all anon/authenticated table grants and policies;
  crawlable pages now read through the Next.js server secret.

The protected website Parquet remained unchanged at SHA-256
`78cc72f91bbd3cfba595ff843486d2e8b82e4ea10a31f68666ce613c6d8ec833`.

## 16. Google Search Console after deployment

1. Set `SITE_URL=https://<stable-production-domain>` in Vercel. Keep it free of
   paths, query strings, credentials, and a trailing deployment-specific URL.
2. Redeploy and verify the production HTML, `/robots.txt`, and `/sitemap.xml`.
   Run `SMOKE_BASE_URL=https://<stable-production-domain> npm run smoke:seo`.
3. Add and verify a Domain property (preferred) or URL-prefix property in Google
   Search Console.
4. Submit `https://<stable-production-domain>/sitemap.xml`.
5. Inspect the homepage and several representative event URLs, test the live
   URL, and request indexing.
6. Monitor sitemap processing, Page indexing, crawl statistics, canonical
   selection, and structured-data reports. Investigate only persistent errors;
   initial discovery/indexing is not immediate.

No production deployment, Search Console action, database mutation, or Git push
was performed by this task.
