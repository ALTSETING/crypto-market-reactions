import { describe, expect, it } from "vitest";

import { OPENAPI_V1_SCHEMA } from "@/lib/api-v1/openapi";

describe("API V1 OpenAPI schema", () => {
  it("documents every V1 endpoint and Bearer authentication", () => {
    expect(OPENAPI_V1_SCHEMA.openapi).toMatch(/^3\./u);
    expect(Object.keys(OPENAPI_V1_SCHEMA.paths).sort()).toEqual([
      "/api/v1/events",
      "/api/v1/events/by-id/{eventId}",
      "/api/v1/events/{slug}",
      "/api/v1/health",
      "/api/v1/meta",
      "/api/v1/openapi.json",
      "/api/v1/reactions",
    ]);
    expect(OPENAPI_V1_SCHEMA.components.securitySchemes.bearerAuth).toMatchObject({ type: "http", scheme: "bearer" });
  });

  it("documents the exact bounded event ID lookup and its error responses", () => {
    const endpoint = OPENAPI_V1_SCHEMA.paths["/api/v1/events/by-id/{eventId}"].get;
    expect(endpoint.operationId).toBe("getEventById");
    expect(endpoint.description).toMatch(/exact equality.*primary key/iu);
    expect(endpoint.parameters[0]).toMatchObject({
      name: "eventId",
      in: "path",
      required: true,
      schema: { type: "string", minLength: 1, maxLength: 96 },
    });
    expect(Object.keys(endpoint.responses).sort()).toEqual(["200", "400", "401", "404", "429", "500", "503"]);
    expect(endpoint.responses["200"].content["application/json"].schema.properties.data).toBeDefined();
  });
});
