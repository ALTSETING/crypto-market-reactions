import { getApiV1DataService } from "@/lib/api-v1/data";
import { ApiV1Error } from "@/lib/api-v1/errors";
import { apiSuccess, CACHE_HEADERS, withApiV1 } from "@/lib/api-v1/http";
import { isValidEventSlug } from "@/lib/validation/events-query";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

interface EventRouteContext {
  params: Promise<{ slug: string }>;
}

export function GET(request: Request, context: EventRouteContext): Promise<Response> {
  return withApiV1(request, async () => {
    const { slug } = await context.params;
    if (!isValidEventSlug(slug)) {
      throw new ApiV1Error(404, "EVENT_NOT_FOUND", "Event not found.");
    }
    const event = await getApiV1DataService().getEventBySlug(slug);
    if (!event) throw new ApiV1Error(404, "EVENT_NOT_FOUND", "Event not found.");
    return apiSuccess(event, CACHE_HEADERS.short);
  });
}

