import { API_VERSION } from "@/lib/api-v1/types";
import { apiDocument, CACHE_HEADERS, withApiV1 } from "@/lib/api-v1/http";
import { assertNoQueryParameters } from "@/lib/api-v1/validation";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

export function GET(request: Request): Promise<Response> {
  return withApiV1(request, () => {
    assertNoQueryParameters(request);
    return apiDocument({ status: "ok", apiVersion: API_VERSION }, CACHE_HEADERS.short);
  });
}
