const baseUrl = (process.env.SMOKE_BASE_URL ?? "http://localhost:3000").replace(/\/$/, "");
const expectedSiteUrl = (process.env.SITE_URL ?? baseUrl).replace(/\/$/, "");
let expectedEventCount = Number(process.env.EXPECTED_EVENT_COUNT ?? "");
const topicPaths = ["bitcoin-etf", "ethereum-etf", "sec-enforcement", "crypto-hacks", "etf-inflows", "etf-outflows", "fed-rate-decisions"].map((slug) => `/topics/${slug}`);
const corePaths = ["/", "/events", "/ai", ...topicPaths];
const googlebot = { headers: { "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)" } };

function assert(condition, message) { if (!condition) throw new Error(message); }
function matches(html, pattern, label) { assert(pattern.test(html), `Missing ${label}`); }
async function read(url, options = {}) {
  const response = await fetch(url, { ...googlebot, ...options });
  return { response, body: await response.text() };
}
function decodeXml(value) { return value.replaceAll("&amp;", "&").replaceAll("&lt;", "<").replaceAll("&gt;", ">").replaceAll("&quot;", '"').replaceAll("&apos;", "'"); }
function decodeHtml(value) {
  return decodeXml(value).replaceAll("&nbsp;", " ").replace(/&#x([0-9a-f]+);/gi, (_, code) => String.fromCodePoint(Number.parseInt(code, 16))).replace(/&#(\d+);/g, (_, code) => String.fromCodePoint(Number(code))).replace(/<[^>]+>/g, "").replace(/\s+/g, " ").trim();
}
function seededSample(values, count) {
  let state = 0x5e0c2026;
  const selected = new Set();
  while (selected.size < Math.min(count, values.length)) { state = (Math.imul(state, 1664525) + 1013904223) >>> 0; selected.add(state % values.length); }
  return [...selected].map((index) => values[index]);
}
function tagContent(html, pattern) { return decodeHtml(html.match(pattern)?.[1] ?? ""); }
function jsonLdTypes(html) {
  const types = [];
  for (const match of html.matchAll(/<script[^>]+type="application\/ld\+json"[^>]*>(.*?)<\/script>/gs)) {
    const visit = (value) => {
      if (Array.isArray(value)) return value.forEach(visit);
      if (!value || typeof value !== "object") return;
      if (typeof value["@type"] === "string") types.push(value["@type"]);
      if (Array.isArray(value["@graph"])) value["@graph"].forEach(visit);
    };
    visit(JSON.parse(match[1]));
  }
  return types;
}
function internalPaths(html) {
  return [...html.matchAll(/<a[^>]+href="([^"]+)"/g)].map((match) => decodeXml(match[1])).filter((href) => href.startsWith("/") && !href.startsWith("//"));
}

const sitemapResponse = await read(`${baseUrl}/sitemap.xml`);
if (!Number.isInteger(expectedEventCount) || expectedEventCount <= 0) {
  const apiResponse = await fetch(`${baseUrl}/api/events?pageSize=1`);
  assert(apiResponse.status === 200, "Could not derive the event count from the public API");
  expectedEventCount = Number((await apiResponse.json()).total);
}
assert(sitemapResponse.response.status === 200, "sitemap.xml did not return HTTP 200");
matches(sitemapResponse.body, /^<\?xml[^>]*>/, "XML declaration");
matches(sitemapResponse.body, /<urlset[^>]*xmlns="http:\/\/www\.sitemaps\.org\/schemas\/sitemap\/0\.9"/, "sitemap namespace");
const sitemapUrls = [...sitemapResponse.body.matchAll(/<loc>(.*?)<\/loc>/g)].map((match) => decodeXml(match[1]));
const eventUrls = sitemapUrls.filter((url) => /^\/events\/[a-z0-9]+(?:-+[a-z0-9]+)*$/.test(new URL(url).pathname));
const lastModifiedValues = [...sitemapResponse.body.matchAll(/<lastmod>(.*?)<\/lastmod>/g)].map((match) => decodeXml(match[1]));
assert(eventUrls.length === expectedEventCount, `Expected ${expectedEventCount} event URLs, received ${eventUrls.length}`);
assert(sitemapUrls.length === expectedEventCount + corePaths.length, `Expected ${expectedEventCount + corePaths.length} total URLs, received ${sitemapUrls.length}`);
assert(new Set(sitemapUrls).size === sitemapUrls.length, "Sitemap contains duplicate URLs");
assert(lastModifiedValues.length === expectedEventCount, "Every event entry must have lastmod and static entries must not invent one");
assert(lastModifiedValues.every((value) => !Number.isNaN(Date.parse(value))), "Sitemap contains an invalid lastmod");
for (const path of corePaths) assert(sitemapUrls.includes(`${expectedSiteUrl}${path === "/" ? "/" : path}`), `Sitemap omits ${path}`);
for (const url of sitemapUrls) {
  const parsed = new URL(url);
  assert(parsed.origin === expectedSiteUrl, `Unexpected sitemap origin: ${parsed.origin}`);
  assert(!parsed.search && !parsed.hash, `Sitemap URL contains search state: ${url}`);
  assert(parsed.pathname === "/" || parsed.pathname === "/events" || parsed.pathname === "/ai" || /^\/topics\/[a-z0-9-]+$/.test(parsed.pathname) || /^\/events\/[a-z0-9]+(?:-+[a-z0-9]+)*$/.test(parsed.pathname), `Malformed sitemap URL: ${url}`);
}

const auditedBodies = [];
for (const path of corePaths) {
  const { response, body } = await read(`${baseUrl}${path}`);
  assert(response.status === 200, `${path} returned HTTP ${response.status}`);
  auditedBodies.push(body);
  const expectedCanonical = `${expectedSiteUrl}${path === "/" ? "" : path}`;
  const title = tagContent(body, /<title>(.*?)<\/title>/s);
  const description = body.match(/<meta[^>]+name="description"[^>]+content="([^"]+)"/)?.[1] ?? "";
  const heading = tagContent(body, /<h1[^>]*>(.*?)<\/h1>/s);
  assert(title.length >= 30 && title.length <= 70, `${path} title length is ${title.length}`);
  assert(description.length >= 100 && description.length <= 170, `${path} description length is ${description.length}`);
  assert(heading.length > 5, `${path} has no useful H1`);
  matches(body, new RegExp(`<link[^>]+rel="canonical"[^>]+href="${expectedCanonical.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}"`), `${path} canonical`);
  assert(!/<meta[^>]+name="robots"[^>]+content="[^"]*noindex/i.test(body), `${path} is unexpectedly noindex`);
  matches(body, /<meta[^>]+property="og:type"[^>]+content="website"/, `${path} website OG type`);
  const types = jsonLdTypes(body);
  assert(types.includes("WebPage"), `${path} lacks WebPage JSON-LD`);
  assert(types.includes("BreadcrumbList"), `${path} lacks BreadcrumbList JSON-LD`);
  assert(!types.includes("Article") && !types.includes("NewsArticle"), `${path} makes an article claim`);
}
const home = auditedBodies[0];
assert(tagContent(home, /<title>(.*?)<\/title>/s) === "Crypto Market Reactions — Historical BTC, ETH & SOL Event Analysis", "Homepage title differs from approved copy");
assert((home.match(/<meta[^>]+name="description"[^>]+content="([^"]+)"/)?.[1] ?? "") === "See how Bitcoin, Ethereum and Solana reacted after ETFs, SEC actions, hacks, institutional flows and other crypto events using historical Reaction V2 data.", "Homepage description differs from approved copy");
assert(jsonLdTypes(home).includes("WebSite"), "Homepage lacks WebSite JSON-LD");

const sampleUrls = seededSample(eventUrls, 10);
const sampledTitles = new Set();
for (const canonical of sampleUrls) {
  const localUrl = `${baseUrl}${new URL(canonical).pathname}`;
  const { response, body } = await read(localUrl);
  assert(response.status === 200, `${localUrl} returned HTTP ${response.status}`);
  auditedBodies.push(body);
  const title = tagContent(body, /<title>(.*?)<\/title>/s);
  const heading = tagContent(body, /<h1[^>]*>(.*?)<\/h1>/s);
  const description = body.match(/<meta[^>]+name="description"[^>]+content="([^"]+)"/)?.[1] ?? "";
  assert(title.length >= 30 && title.length <= 65, `${localUrl} title length is ${title.length}`);
  assert(!sampledTitles.has(title), `${localUrl} repeats a sampled title`);
  sampledTitles.add(title);
  assert(description.length >= 140 && description.length <= 170, `${localUrl} description length is ${description.length}`);
  assert(heading.length > 5, `${localUrl} lacks H1`);
  matches(body, new RegExp(`<link[^>]+rel="canonical"[^>]+href="${canonical.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}"`), `${localUrl} self-canonical`);
  matches(body, /<meta[^>]+property="og:type"[^>]+content="website"/, `${localUrl} website OG type`);
  matches(body, /Read original source/, `${localUrl} source citation`);
  matches(body, /Reaction V2/, `${localUrl} Reaction V2 label`);
  const types = jsonLdTypes(body);
  assert(types.includes("WebPage") && types.includes("BreadcrumbList"), `${localUrl} lacks page or breadcrumb schema`);
  assert(!types.includes("Article") && !types.includes("NewsArticle"), `${localUrl} makes an article claim`);
}

for (const slug of ["missing-event-one-2026-a1b2c3d4", "missing-event-two-2026-b2c3d4e5", "missing-event-three-2026-c3d4e5f6"]) {
  assert((await fetch(`${baseUrl}/events/${slug}`, googlebot)).status === 404, `${slug} must be a true 404`);
}
const filtered = await read(`${baseUrl}/events?asset=ETH&sort=growth`);
assert(filtered.response.status === 200, "Filtered events page did not return HTTP 200");
matches(filtered.body, /<meta[^>]+name="robots"[^>]+content="[^"]*noindex/, "filtered events noindex");
matches(filtered.body, new RegExp(`<link[^>]+rel="canonical"[^>]+href="${expectedSiteUrl.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\/events"`), "filtered events base canonical");
const legacy = await fetch(`${baseUrl}/?asset=ETH&sort=growth`, { ...googlebot, redirect: "manual" });
assert([307, 308].includes(legacy.status), `Legacy filtered homepage must redirect, received ${legacy.status}`);
assert(new URL(legacy.headers.get("location"), baseUrl).pathname === "/events", "Legacy filter redirect lost its destination");
const eventQueryCanonical = sampleUrls[0];
const eventQuery = await read(`${baseUrl}${new URL(eventQueryCanonical).pathname}?utm_source=seo-smoke`);
matches(eventQuery.body, /<meta[^>]+name="robots"[^>]+content="[^"]*noindex/, "event query noindex");
matches(eventQuery.body, new RegExp(`<link[^>]+rel="canonical"[^>]+href="${eventQueryCanonical.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}"`), "event query canonical");

const robots = await read(`${baseUrl}/robots.txt`);
assert(robots.response.status === 200, "robots.txt did not return HTTP 200");
matches(robots.body, /Allow: \//, "robots allow rule");
matches(robots.body, /Disallow: \/api\//, "robots API disallow rule");
matches(robots.body, new RegExp(`Sitemap: ${expectedSiteUrl.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\/sitemap\.xml`), "robots sitemap URL");

const internal = [...new Set(auditedBodies.flatMap(internalPaths))].filter((path) => !path.startsWith("/_next/") && !path.startsWith("/api/"));
for (const path of seededSample(internal, 30)) {
  const response = await fetch(`${baseUrl}${path}`, googlebot);
  assert(response.status < 400, `Internal link ${path} returned HTTP ${response.status}`);
}

console.log(JSON.stringify({ sitemap_total_urls: sitemapUrls.length, sitemap_event_urls: eventUrls.length, core_and_topic_pages: corePaths.length, sampled_event_pages: sampleUrls.length, unique_event_titles: sampledTitles.size, invalid_slug_404s: 3, filtered_events_noindex: true, legacy_filter_redirect: true, event_query_noindex: true, structured_data_verified: true, internal_links_checked: Math.min(30, internal.length), robots_verified: true, canonical_origin: expectedSiteUrl }, null, 2));
