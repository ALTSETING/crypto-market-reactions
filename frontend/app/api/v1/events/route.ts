import { decodeCursor, encodeCursor } from "@/lib/api-v1/cursor";
import { getApiV1DataService } from "@/lib/api-v1/data";
import { apiDocument, CACHE_HEADERS, withApiV1 } from "@/lib/api-v1/http";
import { parseEventsQuery } from "@/lib/api-v1/validation";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export const maxDuration = 15;

export function GET(request: Request): Promise<Response> {
  return withApiV1(request, async ({ apiKey }) => {
    const query = parseEventsQuery(request);
    const cursor = decodeCursor(query.cursor, apiKey);
    const result = await getApiV1DataService().listEvents({ ...query, cursor });
    const last = result.items.at(-1);
    const nextCursor = result.hasMore && last
      ? encodeCursor({ publishedAt: last.publishedAt, id: last.id }, apiKey)
      : null;
    return apiDocument({
      data: result.items,
      pagination: { nextCursor, hasMore: result.hasMore },
    }, CACHE_HEADERS.short);
  });
}

