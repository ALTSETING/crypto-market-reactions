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
});
