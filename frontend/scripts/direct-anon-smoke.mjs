import { readFile } from "node:fs/promises";

const env = Object.fromEntries(
  (await readFile(new URL("../.env.local", import.meta.url), "utf8"))
    .split(/\r?\n/)
    .filter((line) => line && !line.startsWith("#") && line.includes("="))
    .map((line) => {
      const separator = line.indexOf("=");
      return [line.slice(0, separator), line.slice(separator + 1).replace(/^['"]|['"]$/g, "")];
    }),
);
const url = env.NEXT_PUBLIC_SUPABASE_URL ?? env.SUPABASE_URL;
const key = env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? env.SUPABASE_ANON_KEY;
if (!url || !key) throw new Error("Supabase anon configuration is unavailable");
const response = await fetch(`${url}/rest/v1/events?select=event_id&limit=1`, {
  headers: { apikey: key, Authorization: `Bearer ${key}` },
});
const body = await response.text();
const blocked = response.status === 401 || response.status === 403 || (response.ok && body === "[]");
console.log(JSON.stringify({ status: response.status, blocked, rows_exposed: response.ok && body !== "[]" }, null, 2));
if (!blocked) process.exitCode = 1;
