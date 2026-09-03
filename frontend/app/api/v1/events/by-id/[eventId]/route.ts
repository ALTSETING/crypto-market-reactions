import { getApiV1DataService } from "@/lib/api-v1/data";
import { ApiV1Error } from "@/lib/api-v1/errors";
import { apiSuccess, CACHE_HEADERS, withApiV1 } from "@/lib/api-v1/http";
import { assertNoQueryParameters, parseEventIdReference } from "@/lib/api-v1/validation";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

interface EventByIdRouteContext {
  params: Promise<{ eventId: string }>;
}

export function GET(request: Request, context: EventByIdRouteContext): Promise<Response> {
  return withApiV1(request, async () => {
    assertNoQueryParameters(request);
    const { eventId: rawEventId } = await context.params;
    const eventId = parseEventIdReference(rawEventId);
    const event = await getApiV1DataService().getEventById(eventId);
    if (!event) throw new ApiV1Error(404, "EVENT_NOT_FOUND", "Event not found.");
    return apiSuccess(event, CACHE_HEADERS.short);
  });
}
