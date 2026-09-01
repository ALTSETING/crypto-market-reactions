# Local AI Search MVP

AI Research keeps conversational interpretation separate from data access and arithmetic:

`question -> deterministic safety -> AI agent -> optional search_historical_reactions tool -> final answer`

Local development defaults to the `mock` provider and fixture adapter. Production has no mock/fixture fallback: `AI_SEARCH_ENABLED=true` requires `AI_SEARCH_PROVIDER=openai`, `AI_SEARCH_DATA_ADAPTER=production`, `OPENAI_API_KEY`, `OPENAI_AI_SEARCH_MODEL=gpt-5-mini`, and `AI_SEARCH_USE_DISTRIBUTED_RATE_LIMITER=true`. Missing configuration produces a controlled `503`.

The key is read only by modules marked `server-only`. Ordinary questions go directly to the Responses API agent; there is no mandatory router JSON or database intent. The model may call one strict server-side `search_historical_reactions` function. Its compact allowlisted arguments contain asset, topic/query, horizon, direction, and date constraints. Explicit asset, horizon, direction, date, and topic wording is merged deterministically before the existing Reaction V2 pipeline runs. General and hybrid answers therefore use one conversational response, while unchanged historical statistics and citations are rendered directly from the tool result.

OpenAI receives the bounded question and only public, deterministic tool output, never Supabase credentials or private columns. The agent uses the Responses API with `store: false`, a bounded timeout/output/cost ceiling, and strict function calling. Invalid tool arguments get one repair opportunity; failure degrades to an honest conversational answer instead of an invalid-structured-response error. A real provider outage still returns a controlled `503`, and production has no mock fallback. Logs contain only attempt, model, token usage, latency, outcome, status, and estimated cost—never question text, rows, or credentials.

The production adapter uses only the Supabase query builder and an exact public-column allowlist. Asset/horizon columns come from a static map. Count and ranking use bounded database queries; mean, median, sign share, and comparison scan only the filtered non-null Reaction V2 values and reject matches above 10,000 rows. A normalized-key cache stores completed public analytics results for 30 seconds. Null reactions remain null.

AI Search uses two existing migration-008 limiter instances: a conservative per-IP minute namespace and a global daily namespace. Both hash identifiers under the existing server-key design and use bounded process-local fallback only when the distributed adapter call itself fails. Production configuration that does not enable the distributed limiter fails closed.

The fixture adapter is intentionally local. Analytics use only `reactionV2`, exclude null values, retain sample sizes, cap citations at 50, round deterministically to six decimal places, and use stable event-ID tie breaks.

## Production adapter contract

`ProductionAiSearchDataAdapter` implements the read-only server contract. Independent production parity covers 30 intents across every asset and horizon, all source classes, and count/mean/median/share/ranking/comparison. No new RPC or migration is used.

Paid evaluation is separately authorized by `AI_LIVE_TESTS=1` and `AI_LIVE_TEST_BUDGET_USD`. The harness hard-stops at 20 calls or the configured cumulative budget and writes only an ignored aggregate usage summary.

Agent V2 release verification covers a 50-query usefulness/tool-use matrix, AI Intent Reliability, Topic Matching V2, API safety, client-bundle secret scanning, and production conversational smoke checks.
