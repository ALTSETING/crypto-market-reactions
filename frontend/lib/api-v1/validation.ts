import { AI_TOPICS, type AiTopic } from "@/types/ai-search";
import {
  ASSETS,
  EVENT_CATEGORIES,
  HORIZONS,
  SOURCE_TYPES,
  type Asset,
  type EventCategory,
  type Horizon,
  type SourceType,
} from "@/types/events";
import { ApiV1Error } from "@/lib/api-v1/errors";
import {
  API_DEFAULT_LIMIT,
  API_DIRECTIONS,
  API_MAX_LIMIT,
  type ApiDirection,
  type EventsApiQuery,
  type ReactionsApiQuery,
} from "@/lib/api-v1/types";

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/u;
const MAX_URL_LENGTH = 2_048;
const MAX_SEARCH_LENGTH = 160;
const MAX_DATE_SPAN_DAYS = 3_660;

function invalid(message: string): never {
  throw new ApiV1Error(400, "INVALID_PARAMETER", message);
}

function assertAllowedParams(params: URLSearchParams, allowed: readonly string[]): void {
  const allowlist = new Set(allowed);
  for (const key of params.keys()) {
    if (!allowlist.has(key)) invalid(`Unsupported parameter: ${key}.`);
    if (params.getAll(key).length !== 1) invalid(`Parameter ${key} must be supplied once.`);
  }
}

function optionalEnum<T extends string>(
  params: URLSearchParams,
  key: string,
  values: readonly T[],
): T | null {
  const value = params.get(key);
  if (value === null) return null;
  if (!values.includes(value as T)) invalid(`${key} is not supported.`);
  return value as T;
}

function parseDate(params: URLSearchParams, key: string): string | null {
  const value = params.get(key);
  if (value === null) return null;
  const date = ISO_DATE.test(value) ? new Date(`${value}T00:00:00.000Z`) : null;
  if (!date || Number.isNaN(date.valueOf()) || date.toISOString().slice(0, 10) !== value) {
    invalid(`${key} must be a valid ISO date (YYYY-MM-DD).`);
  }
  const year = date.getUTCFullYear();
  if (year < 2010 || year > 2100) invalid(`${key} is outside the supported historical date bounds.`);
  return value;
}

function validateDates(dateFrom: string | null, dateTo: string | null): void {
  if (dateFrom && dateTo) {
    if (dateFrom > dateTo) invalid("dateFrom must not be after dateTo.");
    const spanDays = (Date.parse(`${dateTo}T00:00:00.000Z`) - Date.parse(`${dateFrom}T00:00:00.000Z`)) / 86_400_000;
    if (spanDays > MAX_DATE_SPAN_DAYS) invalid("The requested date range is too large.");
  }
}

function requestUrl(request: Request): URL {
  if (request.url.length > MAX_URL_LENGTH) invalid("The request URL is too long.");
  try {
    return new URL(request.url);
  } catch {
    return invalid("The request URL is invalid.");
  }
}

export function parseEventsQuery(request: Request): EventsApiQuery {
  const params = requestUrl(request).searchParams;
  assertAllowedParams(params, ["asset", "topic", "category", "sourceClass", "dateFrom", "dateTo", "search", "limit", "cursor"]);
  const dateFrom = parseDate(params, "dateFrom");
  const dateTo = parseDate(params, "dateTo");
  validateDates(dateFrom, dateTo);

  const rawLimit = params.get("limit");
  const limit = rawLimit === null ? API_DEFAULT_LIMIT : Number(rawLimit);
  if (!Number.isInteger(limit) || limit < 1 || limit > API_MAX_LIMIT) {
    invalid(`limit must be an integer from 1 to ${API_MAX_LIMIT}.`);
  }

  const rawSearch = params.get("search") ?? "";
  const search = rawSearch.normalize("NFKC").trim();
  if (search.length > MAX_SEARCH_LENGTH || /[\u0000-\u001F\u007F]/u.test(search)) {
    invalid(`search must be at most ${MAX_SEARCH_LENGTH} printable characters.`);
  }

  const cursor = params.get("cursor");
  if (cursor !== null && (cursor.length < 16 || cursor.length > 512)) invalid("cursor is invalid.");
  return {
    asset: optionalEnum<Asset>(params, "asset", ASSETS),
    topic: optionalEnum<AiTopic>(params, "topic", AI_TOPICS),
    category: optionalEnum<EventCategory>(params, "category", EVENT_CATEGORIES),
    sourceClass: optionalEnum<SourceType>(params, "sourceClass", SOURCE_TYPES),
    dateFrom,
    dateTo,
    search,
    limit,
    cursor,
  };
}

export function assertNoQueryParameters(request: Request): void {
  const params = requestUrl(request).searchParams;
  if ([...params.keys()].length > 0) invalid("This endpoint does not accept query parameters.");
}

export function parseReactionsQuery(request: Request): ReactionsApiQuery {
  const params = requestUrl(request).searchParams;
  assertAllowedParams(params, ["asset", "topic", "horizon", "dateFrom", "dateTo", "direction"]);
  const asset = optionalEnum<Asset>(params, "asset", ASSETS);
  if (!asset) invalid("asset is required and must be BTC, ETH, or SOL.");
  const dateFrom = parseDate(params, "dateFrom");
  const dateTo = parseDate(params, "dateTo");
  validateDates(dateFrom, dateTo);
  return {
    asset,
    topic: optionalEnum<AiTopic>(params, "topic", AI_TOPICS),
    horizon: optionalEnum<Horizon>(params, "horizon", HORIZONS),
    dateFrom,
    dateTo,
    direction: optionalEnum<ApiDirection>(params, "direction", API_DIRECTIONS),
  };
}
