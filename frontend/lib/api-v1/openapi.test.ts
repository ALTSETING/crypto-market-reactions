import { describe, expect, it } from "vitest";

import { OPENAPI_V1_SCHEMA } from "@/lib/api-v1/openapi";

describe("API V1 OpenAPI schema", () => {
  it("documents every V1 endpoint and Bearer authentication", () => {
    expect(OPENAPI_V1_SCHEMA.openapi).toMatch(/^3\./u);
    expect(Object.keys(OPENAPI_V1_SCHEMA.paths).sort()).toEqual([
      "/api/v1/events",
      "/api/v1/events/{slug}",
      "/api/v1/health",
      "/api/v1/meta",
      "/api/v1/openapi.json",
      "/api/v1/reactions",
    ]);
    expect(OPENAPI_V1_SCHEMA.components.securitySchemes.bearerAuth).toMatchObject({ type: "http", scheme: "bearer" });
  });
});

