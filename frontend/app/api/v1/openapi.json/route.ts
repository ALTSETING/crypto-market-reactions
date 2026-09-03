import { apiDocument, CACHE_HEADERS, withApiV1 } from "@/lib/api-v1/http";
import { OPENAPI_V1_SCHEMA } from "@/lib/api-v1/openapi";
import { assertNoQueryParameters } from "@/lib/api-v1/validation";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export function GET(request: Request): Promise<Response> {
  return withApiV1(request, () => {
    assertNoQueryParameters(request);
    return apiDocument(OPENAPI_V1_SCHEMA, CACHE_HEADERS.metadata);
  });
}
