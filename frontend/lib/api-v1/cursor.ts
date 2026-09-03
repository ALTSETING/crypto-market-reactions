import { createHmac, timingSafeEqual } from "node:crypto";

import { ApiV1Error } from "@/lib/api-v1/errors";
import type { ApiCursor } from "@/lib/api-v1/types";

const MAX_CURSOR_LENGTH = 512;
const EVENT_ID = /^[A-Za-z0-9_-]{1,96}$/u;

function signature(payload: string, secret: string): Buffer {
  return createHmac("sha256", secret).update(`cmr-api-v1-cursor:${payload}`, "utf8").digest();
}

function validTimestamp(value: unknown): value is string {
  if (typeof value !== "string" || value.length < 20 || value.length > 32) return false;
  const parsed = new Date(value);
  return !Number.isNaN(parsed.valueOf()) && parsed.toISOString() === value;
}

export function encodeCursor(cursor: ApiCursor, secret: string): string {
  const payload = Buffer.from(JSON.stringify({ v: 1, p: cursor.publishedAt, i: cursor.id }), "utf8").toString("base64url");
  return `${payload}.${signature(payload, secret).toString("base64url")}`;
}

export function decodeCursor(value: string | null, secret: string): ApiCursor | null {
  if (value === null) return null;
  try {
    if (value.length < 16 || value.length > MAX_CURSOR_LENGTH) throw new Error("invalid length");
    const parts = value.split(".");
    if (parts.length !== 2 || !parts[0] || !parts[1]) throw new Error("invalid shape");
    const supplied = Buffer.from(parts[1], "base64url");
    const expected = signature(parts[0], secret);
    if (supplied.length !== expected.length || !timingSafeEqual(supplied, expected)) throw new Error("invalid signature");
    const decoded = JSON.parse(Buffer.from(parts[0], "base64url").toString("utf8")) as Record<string, unknown>;
    if (Object.keys(decoded).sort().join(",") !== "i,p,v" || decoded.v !== 1) throw new Error("invalid payload");
    if (!validTimestamp(decoded.p) || typeof decoded.i !== "string" || !EVENT_ID.test(decoded.i)) throw new Error("invalid values");
    return { publishedAt: decoded.p, id: decoded.i };
  } catch {
    throw new ApiV1Error(400, "INVALID_CURSOR", "cursor is invalid or has expired.");
  }
}

