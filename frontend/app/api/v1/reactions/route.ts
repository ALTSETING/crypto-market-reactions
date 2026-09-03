import { getApiV1ReactionService } from "@/lib/api-v1/data";
import { ApiV1Error } from "@/lib/api-v1/errors";
import { apiSuccess, CACHE_HEADERS, withApiV1 } from "@/lib/api-v1/http";
import { parseReactionsQuery } from "@/lib/api-v1/validation";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export const maxDuration = 15;

export function GET(request: Request): Promise<Response> {
  return withApiV1(request, async () => {
    const query = parseReactionsQuery(request);
    const rows = await getApiV1ReactionService().query(query);
    if (query.horizon) {
      const row = rows[0];
      if (!row) throw new ApiV1Error(503, "SERVICE_UNAVAILABLE", "Historical analytics are temporarily unavailable.");
      return apiSuccess({
        asset: query.asset,
        topic: query.topic,
        direction: query.direction,
        ...row,
      }, CACHE_HEADERS.analytics, { basedOn: "Reaction V2" });
    }
    return apiSuccess({
      asset: query.asset,
      topic: query.topic,
      direction: query.direction,
      rows,
    }, CACHE_HEADERS.analytics, { basedOn: "Reaction V2" });
  });
}
