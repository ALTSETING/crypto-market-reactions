# Local AI Search MVP

The MVP keeps language interpretation separate from data access and arithmetic:

`question -> safety gate -> deterministic constraints -> AI router -> strict validation -> database/general/hybrid route -> grounded response`

Local development defaults to the `mock` provider and fixture adapter. Production has no mock/fixture fallback: `AI_SEARCH_ENABLED=true` requires `AI_SEARCH_PROVIDER=openai`, `AI_SEARCH_DATA_ADAPTER=production`, `OPENAI_API_KEY`, `OPENAI_AI_SEARCH_MODEL=gpt-5-mini`, and `AI_SEARCH_USE_DISTRIBUTED_RATE_LIMITER=true`. Missing configuration produces a controlled `503`.

The key is read only by modules marked `server-only`. The strict router chooses `database`, `general`, `hybrid`, `clarification`, `refusal`, or `live_unsupported`. Deterministic asset, horizon, direction, date, and topic constraints outrank router and base-intent output. Database mode retains the existing Reaction V2 pipeline. General mode produces a timeless explanation with an explicit no-live-sources label. Hybrid mode renders that explanation separately from unchanged deterministic historical statistics and citations.

OpenAI receives the bounded question and strict allowlisted metadata, never event rows or Supabase credentials. Router, intent, and general providers use the Responses API with `store: false`, timeouts, bounded output, at most one retry, and configurable per-request cost ceilings. General-provider failures return a controlled `503`; production has no mock fallback. Logs contain only model, token usage, latency, and estimated cost—never question text, rows, or credentials.

The production adapter uses only the Supabase query builder and an exact public-column allowlist. Asset/horizon columns come from a static map. Count and ranking use bounded database queries; mean, median, sign share, and comparison scan only the filtered non-null Reaction V2 values and reject matches above 10,000 rows. A normalized-key cache stores completed public analytics results for 30 seconds. Null reactions remain null.

AI Search uses two existing migration-008 limiter instances: a conservative per-IP minute namespace and a global daily namespace. Both hash identifiers under the existing server-key design and use bounded process-local fallback only when the distributed adapter call itself fails. Production configuration that does not enable the distributed limiter fails closed.

The fixture adapter is intentionally local. Analytics use only `reactionV2`, exclude null values, retain sample sizes, cap citations at 50, round deterministically to six decimal places, and use stable event-ID tie breaks.

## Production adapter contract

`ProductionAiSearchDataAdapter` implements the read-only server contract. Independent production parity covers 30 intents across every asset and horizon, all source classes, and count/mean/median/share/ranking/comparison. No new RPC or migration is used.

Paid evaluation is separately authorized by `AI_LIVE_TESTS=1` and `AI_LIVE_TEST_BUDGET_USD`. The harness hard-stops at 20 calls or the configured cumulative budget and writes only an ignored aggregate usage summary.
