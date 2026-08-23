import { readdir, readFile, stat } from "node:fs/promises";
import path from "node:path";

const staticRoot = path.resolve(".next/static");
const forbidden = [
  "DATABASE_URL",
  "SUPABASE_SERVICE_ROLE",
  "service_role",
  "postgresql://",
  "postgres://",
  "sb_secret_",
];

async function filesBelow(directory) {
  const entries = await readdir(directory);
  const files = [];
  for (const entry of entries) {
    const target = path.join(directory, entry);
    if ((await stat(target)).isDirectory()) files.push(...(await filesBelow(target)));
    else files.push(target);
  }
  return files;
}

const files = await filesBelow(staticRoot);
const findings = [];
for (const file of files) {
  const body = await readFile(file, "utf8");
  for (const token of forbidden) {
    if (body.includes(token)) findings.push({ file: path.relative(staticRoot, file), token });
  }
}

if (findings.length > 0) {
  console.error("Forbidden server credential markers found in client output:", findings);
  process.exit(1);
}
console.log(`Client bundle security scan passed (${files.length} static files checked).`);
