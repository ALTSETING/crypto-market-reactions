# Crypto Market Reactions API V1

The V1 API is a server-to-server, read-only interface to historical Crypto Market Reactions data. It never calls an AI provider and does not expose database, ingestion, debugging, confidence, or service-role fields.

## Base URL and authentication

Production base URL:

```text
https://crypto-market-reactions.com/api/v1
```

Every endpoint uses the canonical Bearer header:

```http
Authorization: Bearer <API_KEY>
```

Do not put an API key in a URL, browser bundle, client-side JavaScript, or logs. `X-API-Key` is not supported. The owner key is configured only as the server-side `CMR_API_KEY` environment variable.

## Endpoints

### `GET /api/v1/health`

```json
{
  "status": "ok",
  "apiVersion": "v1"
}
```

The response deliberately contains no provider, model, database URL, or environment details.

### `GET /api/v1/meta`

Returns the supported `assets`, `horizons`, `topics`, `categories`, and `apiVersion` inside `data`. Clients should use this endpoint rather than hardcoding values.

### `GET /api/v1/events`

Supported query parameters:

| Parameter | Values / limit |
| --- | --- |
| `asset` | `BTC`, `ETH`, `SOL` |
| `topic` | One topic returned by `/meta` |
| `category` | One category returned by `/meta` |
| `sourceClass` | `news_media`, `primary_document`, `official_announcement`, `unknown` |
| `dateFrom`, `dateTo` | Valid inclusive ISO dates (`YYYY-MM-DD`), maximum combined range 3,660 days |
| `search` | Bounded web text search, maximum 160 printable characters |
| `limit` | Default `50`, minimum `1`, maximum `100` |
| `cursor` | Opaque signed cursor from the preceding response |

Example:

```http
GET /api/v1/events?asset=ETH&topic=institutional_purchase&dateFrom=2025-01-01&limit=50
Authorization: Bearer <API_KEY>
```

Response:

```json
{
  "data": [
    {
      "id": "evt18-example",
      "slug": "example-event",
      "title": "Example historical event",
      "publishedAt": "2025-01-02T12:00:00.000Z",
      "source": "example",
      "sourceUrl": "https://example.com/article",
      "primaryAsset": "ETH",
      "relatedAssets": ["ETH"],
      "category": "institutional",
      "sourceClass": "news_media",
      "topic": "institutional_purchase",
      "reactionV2": {
        "BTC": { "1m": null, "5m": null, "15m": null, "1h": null, "4h": null, "24h": null },
        "ETH": { "1m": 0.1, "5m": 0.2, "15m": 0.3, "1h": 0.4, "4h": 0.5, "24h": 0.6 },
        "SOL": { "1m": null, "5m": null, "15m": null, "1h": null, "4h": null, "24h": null }
      }
    }
  ],
  "pagination": {
    "nextCursor": "opaque-token-or-null",
    "hasMore": true
  }
}
```

`topic` is included on list items when a topic filter has been evaluated. `sourceUrl` is omitted when the stored URL is not a public HTTP(S) URL. Reaction V2 missing values remain JSON `null`.

### `GET /api/v1/events/{slug}`

Returns one event as `{ "data": { ... } }`. An unknown or malformed slug returns a real HTTP `404`, not a soft 404.

### `GET /api/v1/events/by-id/{eventId}`

Returns the same `{ "data": { ... } }` event representation using exact equality on the internal `event_id` primary key. Use the `id` returned by `GET /api/v1/events`; this endpoint does not accept search or pagination parameters and returns at most one row. IDs are opaque ASCII references, not UUIDs. A malformed reference returns `400`; a structurally valid unknown ID returns `404`.

### `GET /api/v1/reactions`

This endpoint reads stored Reaction V2 values and invokes the existing deterministic `Topic Matching V2 → Dedup V3 → Reaction V2` analytics pipeline. It does not recalculate reactions and does not call OpenAI.

Parameters:

| Parameter | Values / meaning |
| --- | --- |
| `asset` | Required: `BTC`, `ETH`, or `SOL` |
| `topic` | Optional topic from `/meta` |
| `horizon` | Optional: `1m`, `5m`, `15m`, `1h`, `4h`, `24h` |
| `dateFrom`, `dateTo` | Optional inclusive ISO dates; maximum combined range 3,660 days |
| `direction` | Optional Reaction V2 sign filter: `positive` or `negative` |

Single-horizon example:

```http
GET /api/v1/reactions?asset=BTC&topic=etf_outflow&horizon=24h
```

```json
{
  "data": {
    "asset": "BTC",
    "topic": "etf_outflow",
    "direction": null,
    "horizon": "24h",
    "matchedArticles": 30,
    "independentEvents": 30,
    "mean": 0.0,
    "median": 0.0,
    "positivePercent": 0.0,
    "negativePercent": 0.0,
    "sampleSize": 30
  },
  "basedOn": "Reaction V2"
}
```

When `horizon` is omitted, `data.rows` contains all six horizons in canonical order. `sampleSize` and `independentEvents` are the deduplicated observations with a non-null Reaction V2 value for that row. `matchedArticles` is the pre-dedup topic match count when a topic is present. All unavailable statistics remain `null`.

### `GET /api/v1/openapi.json`

Returns the authenticated OpenAPI 3.1 schema. V1 intentionally has no Swagger UI.

## Supported values

Assets: `BTC`, `ETH`, `SOL`.

Horizons: `1m`, `5m`, `15m`, `1h`, `4h`, `24h`.

Topics: `sec`, `sec_filings`, `regulatory_approval`, `regulatory_enforcement`, `etf`, `etf_approval`, `etf_rejection`, `etf_delay`, `hack`, `listing`, `lawsuit`, `macro`, `fed`, `fed_rate_hike`, `fed_rate_cut`, `cpi`, `upgrade`, `staking`, `large_investment`, `institutional_purchase`, `institutional_selling`, `capital_inflow`, `capital_outflow`, `funding`, `acquisition`, `liquidation`, `etf_inflow`, `etf_outflow`.

Categories are returned by `/meta` and currently include: `defi`, `etf`, `exchange`, `fees`, `hack`, `institutional`, `institutional_adoption`, `layer2`, `legal`, `legal_action`, `macro`, `market_commentary`, `network_activity`, `news`, `nft`, `official_decision`, `other`, `partnership`, `policy_statement`, `product_launch`, `protocol_update`, `protocol_upgrade`, `regulation`, `security`, `security_event`, `stablecoins`, `staking`, `tokenomics`.

## Responses, errors, and limits

Successful resource responses use `data`; the events collection also has a top-level `pagination` object. The health endpoint uses its minimal fixed contract.

Errors never contain stack traces:

```json
{
  "error": {
    "code": "INVALID_PARAMETER",
    "message": "limit must be an integer from 1 to 100."
  }
}
```

HTTP statuses: `200` success, `400` invalid input or cursor, `401` missing/invalid key, `404` unknown event, `429` rate limit, and `503` unavailable server/data provider.

The owner-key defaults are 60 requests per minute and 10,000 requests per day per running API instance. Responses include `RateLimit-*` and `X-Daily-*` headers. A `429` also includes `Retry-After`. Authentication and all error responses are `private, no-store`; historical success responses use short private cache headers and normalized server-side caches. No endpoint enables wildcard CORS.
