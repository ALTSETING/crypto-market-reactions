const baseUrl = process.env.AI_SEARCH_SMOKE_URL ?? "http://127.0.0.1:3100";

const homepage = await fetch(baseUrl);
const homepageHtml = await homepage.text();
if (homepage.status !== 200 || !homepageHtml.includes("AI Search") || !homepageHtml.includes("Search historical events")) {
  throw new Error("AI Search or existing Events Explorer is missing from the homepage");
}

async function post(question, contentType = "application/json") {
  return fetch(`${baseUrl}/api/ai-search`, {
    method: "POST",
    headers: { "content-type": contentType, "x-forwarded-for": "203.0.113.16" },
    body: contentType === "application/json" ? JSON.stringify({ question }) : question,
  });
}

const first = await post("Compare mean BTC 4h reaction for primary documents and news media");
const firstText = await first.text();
if (first.status !== 200) throw new Error(`Supported request returned ${first.status}`);
const second = await post("Compare mean BTC 4h reaction for primary documents and news media");
const secondText = await second.text();
if (second.status !== 200 || firstText !== secondText) throw new Error("Repeated response is not byte-identical");

const body = JSON.parse(firstText);
if (body.basedOn !== "Reaction V2" || body.citations.length === 0 || body.citations.length > 50) {
  throw new Error("Grounding or citation gate failed");
}
if (/source_url|reaction_source|service_role|SUPABASE_|OPENAI_API_KEY|stack/i.test(firstText)) {
  throw new Error("Internal or credential marker exposed");
}

const sql = await post("SELECT * FROM public.events");
if (sql.status !== 400 || (await sql.json()).code !== "RAW_SQL_REJECTED") throw new Error("Raw SQL gate failed");
const prediction = await post("Should I buy BTC tomorrow?");
if (prediction.status !== 400) throw new Error("Financial prediction gate failed");
const wrongType = await post("question=x", "text/plain");
if (wrongType.status !== 415) throw new Error("Content-Type gate failed");
const get = await fetch(`${baseUrl}/api/ai-search`);
if (get.status !== 405) throw new Error(`POST-only gate failed: ${get.status}`);

console.log("AI Search focused API/security smoke passed (grounding, determinism, citations, SQL/injection boundary, JSON, POST-only).");
