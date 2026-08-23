import {
  ASSETS,
  EVENT_SORTS,
  REACTION_HORIZONS,
  type Asset,
  type EventSort,
  type EventsQuery,
  type ReactionHorizon,
} from "@/types/events";

const MAX_QUERY_LENGTH = 120;
const MAX_SOURCE_LENGTH = 80;
const MAX_PAGE = 10_000;
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
const CONTROL_CHARACTERS = /[\u0000-\u001f\u007f]/;

export class QueryValidationError extends Error {
  readonly code = "INVALID_QUERY";

  constructor(message: string) {
    super(message);
    this.name = "QueryValidationError";
  }
}

function parsePositiveInteger(value: string | null, fallback: number, field: string): number {
  if (value === null || value === "") return fallback;
  if (!/^\d+$/.test(value)) {
    throw new QueryValidationError(`${field} must be a positive integer.`);
  }
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed < 1) {
    throw new QueryValidationError(`${field} must be a positive integer.`);
  }
  return parsed;
}

function parseDate(value: string | null, field: string): string | null {
  if (!value) return null;
  if (!DATE_PATTERN.test(value)) {
    throw new QueryValidationError(`${field} must use YYYY-MM-DD.`);
  }
  const parsed = new Date(`${value}T00:00:00.000Z`);
  if (Number.isNaN(parsed.valueOf()) || parsed.toISOString().slice(0, 10) !== value) {
    throw new QueryValidationError(`${field} is not a valid calendar date.`);
  }
  return value;
}

export function parseEventsQuery(params: URLSearchParams): EventsQuery {
  const query = (params.get("q") ?? "").trim();
  const source = (params.get("source") ?? "").trim();
  if (query.length > MAX_QUERY_LENGTH || CONTROL_CHARACTERS.test(query)) {
    throw new QueryValidationError(`q must contain at most ${MAX_QUERY_LENGTH} safe characters.`);
  }
  if (source.length > MAX_SOURCE_LENGTH || CONTROL_CHARACTERS.test(source)) {
    throw new QueryValidationError(
      `source must contain at most ${MAX_SOURCE_LENGTH} safe characters.`,
    );
  }

  const rawAsset = params.get("asset")?.trim().toUpperCase() ?? "";
  if (rawAsset && !ASSETS.includes(rawAsset as Asset)) {
    throw new QueryValidationError("asset must be BTC, ETH, or SOL.");
  }

  const rawSort = params.get("sort")?.trim().toLowerCase() ?? "newest";
  if (!EVENT_SORTS.includes(rawSort as EventSort)) {
    throw new QueryValidationError("sort must be newest, oldest, growth, or decline.");
  }
  const sort = rawSort as EventSort;

  const rawHorizon = params.get("horizon")?.trim().toLowerCase() ?? "average";
  if (!REACTION_HORIZONS.includes(rawHorizon as ReactionHorizon)) {
    throw new QueryValidationError(
      "horizon must be 1m, 5m, 15m, 1h, 4h, 24h, or average.",
    );
  }
  const horizon = rawHorizon as ReactionHorizon;

  const rawMarketDataOnly = params.get("marketDataOnly")?.trim().toLowerCase() ?? "false";
  if (rawMarketDataOnly !== "true" && rawMarketDataOnly !== "false") {
    throw new QueryValidationError("marketDataOnly must be true or false.");
  }
  const marketDataOnly = rawMarketDataOnly === "true";
  if (!rawAsset && (sort === "growth" || sort === "decline")) {
    throw new QueryValidationError("Select BTC, ETH, or SOL to sort by market reaction.");
  }
  if (!rawAsset && marketDataOnly) {
    throw new QueryValidationError("Select BTC, ETH, or SOL to require market data.");
  }

  const page = parsePositiveInteger(params.get("page"), 1, "page");
  if (page > MAX_PAGE) throw new QueryValidationError(`page must not exceed ${MAX_PAGE}.`);

  const pageSizeParam = params.get("pageSize") ?? params.get("limit");
  const requestedPageSize = parsePositiveInteger(pageSizeParam, 25, "pageSize");
  const pageSize = Math.min(requestedPageSize, 50);
  const from = parseDate(params.get("from"), "from");
  const to = parseDate(params.get("to"), "to");
  if (from && to && from > to) {
    throw new QueryValidationError("from must be earlier than or equal to to.");
  }

  return {
    query,
    asset: rawAsset ? (rawAsset as Asset) : null,
    source,
    from,
    to,
    sort,
    horizon,
    marketDataOnly,
    page,
    pageSize,
  };
}

export function isValidEventSlug(slug: string): boolean {
  return slug.length >= 8 && slug.length <= 180 && /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(slug);
}

export function nextUtcDate(date: string): string {
  const value = new Date(`${date}T00:00:00.000Z`);
  value.setUTCDate(value.getUTCDate() + 1);
  return value.toISOString();
}
