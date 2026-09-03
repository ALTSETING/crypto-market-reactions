import { AI_TOPICS } from "@/types/ai-search";
import { ASSETS, EVENT_CATEGORIES, HORIZONS } from "@/types/events";
import { apiSuccess, CACHE_HEADERS, withApiV1 } from "@/lib/api-v1/http";
import { API_VERSION } from "@/lib/api-v1/types";
import { assertNoQueryParameters } from "@/lib/api-v1/validation";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export function GET(request: Request): Promise<Response> {
  return withApiV1(request, () => {
    assertNoQueryParameters(request);
    return apiSuccess({
      assets: ASSETS,
      horizons: HORIZONS,
      topics: AI_TOPICS,
      categories: EVENT_CATEGORIES,
      apiVersion: API_VERSION,
    }, CACHE_HEADERS.metadata);
  });
}
