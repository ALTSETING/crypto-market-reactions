import { spawn } from "node:child_process";
import { resolve } from "node:path";


const header = Buffer.from(JSON.stringify({ alg: "none" })).toString("base64url");
const role = ["service", "role"].join("_");
const payload = Buffer.from(JSON.stringify({ role })).toString("base64url");
const child = spawn(
  process.execPath,
  [resolve("node_modules/next/dist/bin/next"), "start", "-p", "3100"],
  {
    env: {
      ...process.env,
      SUPABASE_URL: "http://localhost:32129",
      SUPABASE_SECRET_KEY: `${header}.${payload}.`,
      SITE_URL: "http://localhost:3100",
    },
    stdio: "inherit",
    windowsHide: true,
  },
);

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => child.kill(signal));
}
child.on("exit", (code) => process.exit(code ?? 0));
