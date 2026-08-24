import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

function source(path: string): string {
  return readFileSync(resolve(process.cwd(), path), "utf8");
}

describe("Supabase server/client boundary", () => {
  it("guards credential and data modules as server-only", () => {
    expect(source("lib/env.ts")).toMatch(/^import "server-only";/);
    expect(source("lib/supabase/server.ts")).toMatch(/^import "server-only";/);
    expect(source("lib/data/events.ts")).toMatch(/^import "server-only";/);
  });

  it("does not expose Supabase credentials or clients from the browser module", () => {
    const client = source("components/events-explorer.tsx");
    expect(client).not.toContain("@supabase/supabase-js");
    expect(client).not.toContain("SUPABASE_");
    expect(client).not.toContain("@/lib/data/events");
    expect(source(".env.example")).not.toContain("NEXT_PUBLIC_SUPABASE");
    expect(source(".env.example")).not.toContain("SUPABASE_ANON_KEY=");
  });

  it("applies the allowlisted source type through a parameterized Supabase filter", () => {
    const dataModule = source("lib/data/events.ts");
    expect(dataModule).toContain('request.eq("source_class_v2", params.sourceType)');
    expect(dataModule).toContain('"source_type:source_class_v2"');
    expect(dataModule).toContain('request.eq("category", params.category)');
    expect(dataModule).not.toContain("source_type = ${");
    expect(dataModule).not.toContain('request.eq("source_type", params.sourceType)');
  });

  it("labels production reactions without presenting candidate research as live data", () => {
    const eventPage = source("app/events/[slug]/page.tsx");
    expect(eventPage).toContain("Reaction V2");
    expect(eventPage).toContain("do not establish causality");
    expect(eventPage).toContain("Alternative research alignments are not displayed");
  });
});
