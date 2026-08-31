import { isSchemaBisectVariant, runSchemaBisectVariant } from "@/lib/ai-search/schema-bisect";

export const dynamic = "force-dynamic";

const MAX_BODY_BYTES = 128;
const LIMIT = 9;
const WINDOW_MS = 15 * 60_000;
const EXPIRES_AT = Date.parse("2026-08-31T16:30:00Z");
const calls = new Map<string, { count: number; resetAt: number }>();

function response(status: number, body: object) {
  return Response.json(body, { status, headers: { "Cache-Control": "private, no-store" } });
}

function consume(ip: string): boolean {
  const now = Date.now();
  const current = calls.get(ip);
  if (!current || current.resetAt <= now) {
    calls.set(ip, { count: 1, resetAt: now + WINDOW_MS });
    return true;
  }
  if (current.count >= LIMIT) return false;
  current.count += 1;
  return true;
}

export async function POST(request: Request) {
  if (Date.now() > EXPIRES_AT) return response(404, { status: "error", code: "NOT_FOUND" });
  if (request.headers.get("x-schema-bisect-run") !== "production-bisect-v1") {
    return response(404, { status: "error", code: "NOT_FOUND" });
  }
  if (!request.headers.get("content-type")?.toLowerCase().startsWith("application/json")) {
    return response(415, { status: "error", code: "JSON_REQUIRED" });
  }
  const contentLength = Number(request.headers.get("content-length") ?? "0");
  if (Number.isFinite(contentLength) && contentLength > MAX_BODY_BYTES) {
    return response(413, { status: "error", code: "REQUEST_TOO_LARGE" });
  }
  const ip = request.headers.get("x-forwarded-for")?.split(",")[0]?.trim() || "unknown";
  if (!consume(ip)) return response(429, { status: "error", code: "RATE_LIMITED" });

  let payload: unknown;
  try {
    const raw = await request.text();
    if (new TextEncoder().encode(raw).byteLength > MAX_BODY_BYTES) {
      return response(413, { status: "error", code: "REQUEST_TOO_LARGE" });
    }
    payload = JSON.parse(raw);
  } catch {
    return response(400, { status: "error", code: "INVALID_JSON" });
  }
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    return response(400, { status: "error", code: "INVALID_VARIANT" });
  }
  const value = payload as Record<string, unknown>;
  if (Object.keys(value).sort().join(",") !== "variant" || !isSchemaBisectVariant(value.variant)) {
    return response(400, { status: "error", code: "INVALID_VARIANT" });
  }
  const apiKey = process.env.OPENAI_API_KEY?.trim();
  if (!apiKey) return response(503, { status: "error", code: "DIAGNOSTIC_UNAVAILABLE" });

  const result = await runSchemaBisectVariant(value.variant, { apiKey });
  console.info("OpenAI schema bisect completed", result);
  return response(200, result);
}
