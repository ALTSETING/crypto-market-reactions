import { describe, expect, it } from "vitest";

import { decodeCursor, encodeCursor } from "@/lib/api-v1/cursor";
import { ApiV1Error } from "@/lib/api-v1/errors";

const SECRET = "cursor-test-key-0123456789abcdef";

describe("API V1 cursor", () => {
  it.each([
    "2025-01-02T03:04:05.000Z",
    "2026-07-01T00:00:00+00:00",
    "2026-07-01T00:00:00.123456+00:00",
  ])("round-trips a stable pagination position with timestamp %s", (publishedAt) => {
    const position = { publishedAt, id: "evt18-abc_123" };
    expect(decodeCursor(encodeCursor(position, SECRET), SECRET)).toEqual(position);
  });

  it("generates an ASCII URL-safe, unpadded, signed v1 payload", () => {
    const cursor = encodeCursor({ publishedAt: "2026-07-01T00:00:00+00:00", id: "evt18-abc_123" }, SECRET);
    const [payload] = cursor.split(".");
    expect(cursor).toMatch(/^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/u);
    expect(cursor).not.toContain("=");
    expect([...cursor].every((character) => character.charCodeAt(0) < 128)).toBe(true);
    expect(decodeURIComponent(encodeURIComponent(cursor))).toBe(cursor);
    expect(JSON.parse(Buffer.from(payload, "base64url").toString("utf8"))).toEqual({
      v: 1,
      p: "2026-07-01T00:00:00+00:00",
      i: "evt18-abc_123",
    });
  });

  it.each([
    "weird",
    "a".repeat(513),
    "e30.invalid-signature",
    "e30=.invalid-signature",
  ])("rejects malformed cursor %s with INVALID_CURSOR", (cursor) => {
    expectInvalidCursor(cursor);
  });

  it("rejects a tampered signed cursor with INVALID_CURSOR", () => {
    const cursor = encodeCursor({ publishedAt: "2026-07-01T00:00:00+00:00", id: "evt18-abc_123" }, SECRET);
    const [payload, suppliedSignature] = cursor.split(".");
    const replacement = suppliedSignature[0] === "A" ? "B" : "A";
    expectInvalidCursor(`${payload}.${replacement}${suppliedSignature.slice(1)}`);
  });

  it.each([
    "2025-02-29T00:00:00+00:00",
    "2025-01-02T03:04:60+00:00",
    "2025-01-02T03:04:05+02:00",
  ])("rejects a signed cursor with invalid timestamp %s", (publishedAt) => {
    expectInvalidCursor(encodeCursor({ publishedAt, id: "evt18-abc_123" }, SECRET));
  });
});

function expectInvalidCursor(cursor: string): void {
  try {
    decodeCursor(cursor, SECRET);
    expect.unreachable("cursor should have been rejected");
  } catch (error) {
    expect(error).toBeInstanceOf(ApiV1Error);
    expect(error).toMatchObject({ status: 400, code: "INVALID_CURSOR" });
  }
}
