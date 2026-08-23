# Crypto Market Reaction Database — frontend MVP

Responsive read-only Next.js frontend for the 7,878-event Supabase dataset.
The browser calls same-origin, bounded Next.js routes; only server code calls
the Supabase Data API. Elevated Supabase credentials are isolated in modules
guarded by `server-only` and are never returned to the browser.

## Stack

- Next.js 16 App Router and React 19;
- TypeScript (strict mode);
- Tailwind CSS 4;
- `@supabase/supabase-js` using a server-only Supabase secret key;
- ESLint and Vitest;
- npm with a committed `package-lock.json`.

## Local environment

Use Node.js 20.9 or newer. Copy the example and enter the project URL and a
dedicated **secret** key from Supabase Dashboard → Project Settings → API Keys.

```powershell
Copy-Item .env.example .env.local
```

Required server-only variables:

```text
SUPABASE_URL=https://your-project-ref.supabase.co
SUPABASE_SECRET_KEY=your-sb-secret-key
SITE_URL=https://your-stable-production-domain.example
```

The legacy `SUPABASE_SERVICE_ROLE_KEY` is accepted as a fallback, but a scoped,
rotatable `sb_secret_...` key is preferred. Never add `NEXT_PUBLIC_` prefixes,
log either key, commit `.env.local`, or pass these values to Client Components.
The environment guard rejects anon/publishable keys for dataset access.

## Install and run

```powershell
cd frontend
npm ci
npm run dev
```

Open `http://localhost:3000`. Production mode:

```powershell
npm run build
npm run start
```

## Checks

```powershell
npm run lint
npm run typecheck
npm run test
npm run build
npm run security:bundle
```

With a production server running locally, the Windows Chrome smoke test is:

```powershell
npm run smoke:browser
npm run smoke:seo
```

## SEO architecture

- `/events/[slug]` is a crawlable server-rendered page with deterministic
  metadata, self-canonical, Open Graph/Twitter tags, Article JSON-LD, internal
  links, original-source link, and a real 404 for unknown slugs.
- `/sitemap.xml` contains the homepage and all live event slugs from Supabase;
  `/robots.txt` allows event pages and excludes `/api/`.
- Search/filter/query URLs are `noindex,follow` and canonicalize to their clean
  page, preventing filter combinations from becoming duplicate indexed pages.
- `SITE_URL` is the preferred central production origin. If absent on Vercel,
  the server uses `VERCEL_PROJECT_PRODUCTION_URL`; localhost is only the final
  development fallback.
- Event and sitemap data use one-hour server cache/revalidation windows, so the
  build does not pre-render or query all 7,878 event pages.

See `../docs/SEO_MVP_REPORT.md` for the verified URL counts, tests, limitations,
and post-deployment Google Search Console checklist.

## Query architecture

- `/api/events` accepts `q`, `asset`, `sort`, `horizon`, `marketDataOnly`,
  `source`, `from`, `to`, `page`, and `pageSize`. Legacy `limit` remains a
  compatibility alias for `pageSize`.
- Search uses Supabase `.textSearch()` against the generated PostgreSQL
  `search_vector`; it never downloads the full dataset for browser filtering.
- Asset filtering uses `related_assets @>` through Supabase `.contains()`.
- Date bounds use the indexed `published_at`; source uses the indexed `source`.
- Newest/oldest ordering uses `published_at` plus the unique `event_id`
  tie-breaker. Reaction ordering uses the allowlisted selected asset/horizon in
  Supabase before pagination, with `NULLS LAST`, then the same stable tie-breaker.
- Default page size is 25. UI options are 25 and 50. Every requested page size
  above 50 is capped at 50 by server-side validation.
- Search runs only after the user presses Enter or selects Search. Filters,
  pagination, and page size also remain in the URL across reloads.
- Average reaction is a stored generated database value for one selected asset,
  ignores NULL horizons, counts zero, and requires at least three of six values.
- `/events/[slug]` performs an indexed, single-row server lookup and returns the
  Next.js 404 page for invalid or missing slugs.

Only columns required by each view are selected. Full article bodies and
internal archive/AI metadata are not requested.

`/api/events/export` applies the same allowlisted query and pagination rules and
downloads only the current page, never more than 50 rows. CSV cells are quoted
and formula-like values are neutralized.

## Rate limiting

The list/search and CSV endpoints share a limit of 60 requests per 60-second
window per forwarded IP and respond with HTTP 429 plus `Retry-After` and
`RateLimit-*` headers.

The current limiter is intentionally in-memory. It works for one long-lived
Node process but is not globally consistent across multiple serverless
instances and resets on restart. For production, replace the `RateLimiter`
implementation in `lib/rate-limit.ts` with Upstash/Redis, or enforce the same
policy at Cloudflare/Vercel. The API/data layer does not need to be rewritten.

## Deployment notes

1. Configure `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, and `SITE_URL` in Vercel.
2. Verify Search, event pages, sitemap, and CSV with the server key, then apply
   `database/migrations/005_close_public_events_access.sql` and verify direct
   anon SELECT returns no rows or HTTP 401/403.
3. Run all five checks above in CI.
4. Add a distributed rate limiter and platform-level request controls before
   scaling to multiple instances.
5. Configure a response/page cap at the platform layer as defense in depth.

## MVP limitations

- Search is lexical English PostgreSQL FTS, not semantic/AI search.
- The in-memory rate limiter is single-instance only.
- There is no authentication, payment, or unrestricted bulk download endpoint.
- Public SEO pages remain individually crawlable, so a determined distributed
  scraper can still collect public fields over many throttled requests.
- Counts use Supabase exact count, which is appropriate for 7,878 rows but
  should be revisited if the dataset grows by orders of magnitude.
