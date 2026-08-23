# Crypto Market Reaction Database — frontend MVP

Responsive read-only Next.js frontend for the 7,878-event Supabase dataset.
The browser calls the local `/api/events` route; only server code calls the
Supabase Data API. No PostgreSQL connection string or service-role credential
is accepted by this application.

## Stack

- Next.js 16 App Router and React 19;
- TypeScript (strict mode);
- Tailwind CSS 4;
- `@supabase/supabase-js` using the anonymous/publishable read-only role;
- ESLint and Vitest;
- npm with a committed `package-lock.json`.

## Local environment

Use Node.js 20.9 or newer. Copy the example and enter the project URL and the
**anon/publishable** key from Supabase Dashboard → Project Settings → API.

```powershell
Copy-Item .env.example .env.local
```

Required server-only variables:

```text
SUPABASE_URL=https://your-project-ref.supabase.co
SUPABASE_ANON_KEY=your-anon-or-publishable-key
```

Do not add `NEXT_PUBLIC_` prefixes. Do not put `DATABASE_URL`, a database
password, a pooler URL, `service_role`, or `sb_secret_...` in this directory.
The environment guard rejects recognizable service-role/secret keys.

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
```

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
- Default page size is 20. UI options are 20 and 50. Every requested page size
  above 50 is capped at 50 by server-side validation.
- Search runs only after the user presses Enter or selects Search. Filters,
  pagination, and page size also remain in the URL across reloads.
- Average reaction is a stored generated database value for one selected asset,
  ignores NULL horizons, counts zero, and requires at least three of six values.
- `/events/[slug]` performs an indexed, single-row server lookup and returns the
  Next.js 404 page for invalid or missing slugs.

Only columns required by each view are selected. Full article bodies and
internal archive/AI metadata are not requested.

## Rate limiting

The list/search endpoint allows 60 requests per 60-second window per forwarded
IP and responds with HTTP 429 plus `Retry-After` and `RateLimit-*` headers.

The current limiter is intentionally in-memory. It works for one long-lived
Node process but is not globally consistent across multiple serverless
instances and resets on restart. For production, replace the `RateLimiter`
implementation in `lib/rate-limit.ts` with Upstash/Redis, or enforce the same
policy at Cloudflare/Vercel. The API/data layer does not need to be rewritten.

## Deployment notes

1. Configure only `SUPABASE_URL` and `SUPABASE_ANON_KEY` in server environment
   settings.
2. Keep the existing Supabase anon SELECT-only RLS policy; never add public
   write policies.
3. Run all five checks above in CI.
4. Add a distributed rate limiter and platform-level request controls before
   scaling to multiple instances.
5. Configure a response/page cap at the platform layer as defense in depth.

## MVP limitations

- Search is lexical English PostgreSQL FTS, not semantic/AI search.
- The in-memory rate limiter is single-instance only.
- There is no authentication, payment, CSV export, or unrestricted bulk
  download endpoint.
- Counts use Supabase exact count, which is appropriate for 7,878 rows but
  should be revisited if the dataset grows by orders of magnitude.
