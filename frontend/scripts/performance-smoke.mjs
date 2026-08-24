import { writeFile } from "node:fs/promises";
import { resolve } from "node:path";

const mode = process.argv[2];
if (!new Set(["before", "after"]).has(mode)) throw new Error("Usage: node performance-smoke.mjs before|after");
const baseUrl = (process.env.SMOKE_BASE_URL ?? "https://crypto-market-reactions-nu.vercel.app").replace(/\/$/, "");
const first = await fetch(`${baseUrl}/api/events?limit=1`).then((response) => response.json());
const slug = first.items?.[0]?.slug;
if (!slug) throw new Error("Could not resolve an event slug for performance smoke");
const endpoints = {
  homepage: "/",
  search: "/api/events?search=bitcoin&limit=25",
  event_page: `/events/${encodeURIComponent(slug)}`,
  sitemap: "/sitemap.xml",
};
const measurements = {};
for (const [name, path] of Object.entries(endpoints)) {
  const runs = [];
  for (let index = 0; index < 5; index += 1) {
    const started = performance.now();
    const response = await fetch(`${baseUrl}${path}`, { cache: "no-store" });
    await response.arrayBuffer();
    if (!response.ok) throw new Error(`${name} returned ${response.status}`);
    runs.push(Number((performance.now() - started).toFixed(1)));
  }
  const sorted = [...runs].sort((a, b) => a - b);
  measurements[name] = { runs_ms: runs, median_ms: sorted[2], max_ms: sorted[4] };
}
const output = { mode, measured_at: new Date().toISOString(), base_url: baseUrl, measurements };
await writeFile(resolve("../reports", `REACTION_V2_PERFORMANCE_${mode.toUpperCase()}.json`), `${JSON.stringify(output, null, 2)}\n`);
console.log(JSON.stringify(output, null, 2));
