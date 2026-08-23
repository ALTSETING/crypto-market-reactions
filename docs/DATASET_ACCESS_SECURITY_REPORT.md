# Dataset access security report

Date: 2026-08-23

Status: **migration 005 and final Vercel production verification passed**.

The Supabase secret was configured without entering source control. All server
paths passed before migration 005, the migration was applied transactionally,
and all local production HTTP checks passed again after anon access was closed.
The current Vercel deployment now passes the same security, SEO, browser, and
bounded-access checks through the public production origin.

## 1. Previous architecture and access audit

The browser did not instantiate Supabase directly, but every server query still
used a publishable/anon key. Since `public.events` had unrestricted anon SELECT,
the same key could be used outside the website to read all 7,878 rows in batches.
A live pre-cutover REST probe returned HTTP 206 and `Content-Range: 0-0/7878`.

| File / function | Access | Runtime | Selected public columns |
|---|---|---|---|
| `components/events-explorer.tsx` | `fetch('/api/events')` | Browser | Receives bounded JSON only; no Supabase import |
| `app/api/events/route.ts` → `getEvents` | Search, filters, sort, count, range | Server | Event identity/classification plus six reaction horizons and stored average for BTC/ETH/SOL (30 explicit fields) |
| `app/events/[slug]/page.tsx` → `getEventBySlug` | Unique slug lookup | Server Component | List fields plus displayed source URL, sentiment score, methodology and reaction reference fields |
| `app/sitemap.ts` → `getSitemapEvents` | Batched sitemap lookup | Server | `slug,updated_at` only |
| CSV/export | Absent before this change | — | — |

No `.select('*')`, browser Supabase query, `/api/export-all`, generic column
selector, or unrestricted one-request dataset endpoint was found.

## 2. New architecture

```text
Browser
  ├─ bounded GET /api/events
  ├─ bounded GET /api/events/export
  └─ crawlable /events/<slug>
             ↓
Next.js server-only modules
             ↓
Supabase Data API with secret/service-role credential
             ↓
public.events (RLS enabled; no anon/authenticated grants or policies)
```

All database calls remain centralized in `frontend/lib/data/events.ts`, which
imports `server-only`. Search uses a Route Handler because the interactive
Client Component needs JSON; event pages and sitemap remain Server Components.

## 3. Client queries removed

There were no direct client-side Supabase calls to remove. The important change
is that the server client no longer accepts `SUPABASE_ANON_KEY`. The browser
module has no Supabase dependency, credential reference, or data-module import.

## 4. Server queries and allowed columns

- Search uses one explicit 30-field projection. All six horizons are necessary
  because the UI lets the user select any supported horizon; default cards use
  only 1h/24h. Internal ingestion, provenance, search-vector, body, and AI fields
  are not selected.
- Event lookup uses only fields rendered in HTML/metadata/reaction methodology.
- Sitemap reads only `slug,updated_at` in 1,000-row server batches.
- CSV reuses the bounded search query but serializes only 16 public columns:
  identity, title/date/source/classification and BTC/ETH/SOL 1h/24h reactions.

## 5. Search page size

Default page size is 25. The only UI choices are 25 and 50. `pageSize` and the
legacy `limit` alias are parsed as positive integers and hard-clamped to 50.
Values such as `1000`, `100000`, and `999999` cannot enlarge the response.

## 6. Pagination strategy

Page-number pagination uses a server-calculated PostgREST range and stable
ordering (`published_at`, then unique `event_id`). The response includes exact
total and total-pages metadata but only the current page rows. Invalid, zero,
negative, non-integer, and excessive page values return HTTP 400. An unsupported
`offset` parameter is ignored and therefore cannot change the bounded page.

## 7. CSV limits

`GET /api/events/export` exports the current filtered/sorted page only, with a
hard maximum of 50 data rows. It shares the search rate limiter, uses no-store,
sets attachment/nosniff headers, quotes every cell, and neutralizes spreadsheet
formula prefixes. There is no export-all route.

## 8. RLS state

Pre-cutover live state (recorded before migration 005):

- RLS enabled: yes;
- client grants: anon SELECT only; no anon INSERT/UPDATE/DELETE;
- public policies: `Public read access` and `events_public_read_only`, both anon
  SELECT with an unconditional predicate;
- direct anon read: currently allowed.

Migration `database/migrations/005_close_public_events_access.sql` was applied.
Post-cutover verification found RLS enabled, zero policies, zero table grants
for `PUBLIC`/`anon`/`authenticated`, and service-role access preserved. Direct
anon REST SELECT now returns HTTP 401.

## 9. Public policies after cutover

Final state for `public.events`: no policies for anon/authenticated and no table
privileges for those roles. `service_role` reads through the backend and
bypasses RLS. INSERT/UPDATE/DELETE remain unavailable to browser roles.

## 10. Server credential strategy

Preferred variables:

```text
SUPABASE_URL=
SUPABASE_SECRET_KEY=
SITE_URL=
```

The current Supabase `sb_secret_...` key is preferred. The legacy
`SUPABASE_SERVICE_ROLE_KEY` JWT is supported only as a fallback. Neither name
uses `NEXT_PUBLIC_`; credential and data modules are guarded by `server-only`;
auth session persistence and token refresh are disabled. Actual values remain
in ignored local/Vercel environment settings and must never be logged or
committed.

## 11. Bulk extraction tests

Automated unit validation covers:

- default 25 and maximum 50 rows;
- `limit=1000`, `limit=100000`, `pageSize=999999` clamping;
- negative/zero/invalid page and negative limit rejection;
- stable page propagation;
- CSV hard cap of 50 and formula-injection escaping;
- static server/client boundary checks.

`npm run smoke:security` additionally exercises these rules through production
HTTP and confirms list/CSV responses omit detail/internal fields. It passed
both immediately before and after the live RLS cutover.

## 12. Client bundle secret audit

The post-build scanner checks both forbidden credential markers and the exact
configured secret/database values when present. The current production build
passed: 26 client static files checked, zero findings. The source-boundary tests
also confirm that the Client Component contains no Supabase import or env name.

## 13. Production verification

Completed locally against the production build after migration 005:

- 33/33 unit tests;
- TypeScript and ESLint;
- Next.js 16.3.2 production build;
- exact-value client-bundle security scan (26 static files, zero findings);
- Search, filters, pagination and current-page CSV abuse smoke;
- browser interaction smoke;
- sitemap with 7,878 event URLs plus homepage;
- 100 random event identity checks, 20 detailed SEO pages and five real 404s;
- direct anon SELECT blocked with HTTP 401;
- database count unchanged at 7,878 rows, event IDs and slugs.

Direct smoke of `https://crypto-market-reactions-nu.vercel.app` on 2026-08-23:

| Check | Result |
|---|---|
| Homepage | PASS — HTTP 200 |
| Search API | PASS — HTTP 200, default 25, maximum 50 rows |
| Pagination | PASS — page 2 HTTP 200 with bounded rows |
| Current-page CSV | PASS — HTTP 200, `text/csv`, maximum 50 rows |
| Event pages | PASS — 100 random identities and 20 detailed pages |
| `/sitemap.xml` | PASS — HTTP 200, 7,879 unique URLs total |
| `/robots.txt` | PASS — HTTP 200, events allowed and API disallowed |
| Canonical/query noindex | PASS — clean self-canonicals and query noindex |
| Invalid event slug | PASS — five tested slugs returned HTTP 404 |
| Direct anon Supabase SELECT | PASS — HTTP 401, still blocked |
| Server-side secret access | PASS — Search, CSV, events and sitemap read successfully |
| Mobile browser | PASS — 390px homepage/event page without horizontal overflow |
| Theme/filter interactions | PASS — light default, persistent dark, collapsible filters |

Oversized `limit=1000`, `limit=100000`, and `pageSize=999999` requests were
clamped to 50. Invalid pagination was rejected, unsupported negative offset was
safely ignored, and list/CSV responses did not expose event-detail or internal
fields. Production canonical origin is
`https://crypto-market-reactions-nu.vercel.app`.

Migration 005 must remain applied. Restoring anon SELECT would re-enable direct
bulk extraction and is not required for any verified website or SEO route.

## 14. Known limitations

- The 60 requests/minute/IP limiter is process-local. On Vercel it resets on
  cold starts and is not globally coordinated across instances. It is useful
  best-effort abuse friction, not a strong commercial anti-scraping boundary.
- Public event pages and sitemap necessarily reveal crawlable event URLs. A
  determined scraper can collect public page fields over many requests; the
  change prevents unrestricted Supabase access and one-request bulk export, not
  all possible scraping.
- Exact totals are public. They do not include event rows.
- The old publishable key may remain in an ignored local env file for the anon
  denial test, but application code no longer reads or accepts it.

## 15. Paid dataset access later

Paid access should introduce authenticated principals, entitlement records,
separate rate/volume quotas, auditable export jobs, expiring download URLs, and
per-customer credentials. Replace the in-memory limiter with a distributed
store or platform/WAF limit. Keep free Search and SEO projections separate from
paid export projections, and never turn the current endpoint into an export-all
API by only increasing its page limit.

No historical data, reaction calculation, AI pipeline, authentication, or
payment flow was changed. The only live database change was the reviewed access
cutover in migration 005.
