import { describe, expect, it } from "vitest";

import { decodeCursor, encodeCursor } from "@/lib/api-v1/cursor";
import { ApiV1Error } from "@/lib/api-v1/errors";

const SECRET = "cursor-test-key-0123456789abcdef";

describe("API V1 cursor", () => {
  it("round-trips a stable pagination position", () => {
    const position = { publishedAt: "2025-01-02T03:04:05.000Z", id: "evt18-abc_123" };
    expect(decodeCursor(encodeCursor(position, SECRET), SECRET)).toEqual(position);
  });

  it.each(["weird", "a".repeat(513), "e30.invalid-signature"])("rejects malformed or forged cursor %s", (cursor) => {
    expect(() => decodeCursor(cursor, SECRET)).toThrowError(ApiV1Error);
  });
});

