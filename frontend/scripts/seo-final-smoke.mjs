const baseUrl = (process.env.SMOKE_BASE_URL ?? "http://localhost:3000").replace(/\/$/u, "");
const expectedSiteUrl = (process.env.SITE_URL ?? baseUrl).replace(/\/$/u, "");
const expectedOrigin = new URL(expectedSiteUrl).origin;
const topicPaths = ["bitcoin-etf", "ethereum-etf", "sec-enforcement", "crypto-hacks", "etf-inflows", "etf-outflows", "fed-rate-decisions"].map((slug) => `/topics/${slug}`);
const corePaths = ["/", "/events", "/ai"];
const googlebotUserAgent = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)";
const browserUserAgent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36";

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function decodeEntities(value) {
  return value
    .replaceAll("&amp;", "&")
    .replaceAll("&lt;", "<")
    .replaceAll("&gt;", ">")
    .replaceAll("&quot;", '"')
    .replaceAll("&apos;", "'")
    .replaceAll("&nbsp;", " ")
    .replace(/&#x([0-9a-f]+);/giu, (_, code) => String.fromCodePoint(Number.parseInt(code, 16)))
    .replace(/&#(\d+);/gu, (_, code) => String.fromCodePoint(Number(code)));
}

function textContent(value) {
  return decodeEntities(value).replace(/<script\b[^>]*>[\s\S]*?<\/script>/giu, " ").replace(/<style\b[^>]*>[\s\S]*?<\/style>/giu, " ").replace(/<[^>]+>/gu, " ").replace(/\s+/gu, " ").trim();
}

function tags(html, name) {
  return [...html.matchAll(new RegExp(`<${name}\\b[^>]*>`, "giu"))].map((match) => match[0]);
}

function attribute(tag, name) {
  return decodeEntities(tag.match(new RegExp(`\\b${name}=["']([^"']*)["']`, "iu"))?.[1] ?? "");
}

function metadata(html) {
  const title = textContent(html.match(/<title>([\s\S]*?)<\/title>/iu)?.[1] ?? "");
  const descriptions = tags(html, "meta").filter((tag) => attribute(tag, "name").toLowerCase() === "description").map((tag) => attribute(tag, "content"));
  const robots = tags(html, "meta").filter((tag) => attribute(tag, "name").toLowerCase() === "robots").map((tag) => attribute(tag, "content").toLowerCase());
  const verification = tags(html, "meta").filter((tag) => attribute(tag, "name").toLowerCase() === "google-site-verification").map((tag) => attribute(tag, "content"));
  const canonicals = tags(html, "link").filter((tag) => attribute(tag, "rel").toLowerCase() === "canonical").map((tag) => attribute(tag, "href"));
  const openGraphUrls = tags(html, "meta").filter((tag) => attribute(tag, "property").toLowerCase() === "og:url").map((tag) => attribute(tag, "content"));
  const h1 = textContent(html.match(/<h1\b[^>]*>([\s\S]*?)<\/h1>/iu)?.[1] ?? "");
  return { title, descriptions, robots, verification, canonicals, openGraphUrls, h1 };
}

function parseJsonLd(html) {
  const documents = [];
  const errors = [];
  for (const match of html.matchAll(/<script\b[^>]*type=["']application\/ld\+json["'][^>]*>([\s\S]*?)<\/script>/giu)) {
    try { documents.push(JSON.parse(match[1])); } catch (error) { errors.push(String(error)); }
  }
  return { documents, errors };
}

function visitJson(value, visitor, key = "") {
  if (Array.isArray(value)) return value.forEach((item) => visitJson(item, visitor, key));
  if (!value || typeof value !== "object") return;
  for (const [childKey, child] of Object.entries(value)) {
    visitor(child, childKey);
    visitJson(child, visitor, childKey);
  }
}

function structuredTypes(documents) {
  const types = [];
  visitJson(documents, (value, key) => { if (key === "@type" && typeof value === "string") types.push(value); });
  return types;
}

function structuredInternalUrls(documents) {
  const urls = [];
  visitJson(documents, (value, key) => {
    if (["url", "@id", "item"].includes(key) && typeof value === "string" && /^https?:\/\//iu.test(value)) urls.push(value);
  });
  return urls;
}

function internalLinks(html) {
  const links = [];
  for (const tag of tags(html, "a")) {
    const href = attribute(tag, "href");
    if (!href || href.startsWith("#")) continue;
    const parsed = new URL(href, expectedSiteUrl);
    if (parsed.origin === expectedOrigin) links.push(`${parsed.pathname}${parsed.search}`);
  }
  return links;
}

function normalizedCanonical(value) {
  const parsed = new URL(value);
  parsed.hash = "";
  parsed.search = "";
  if (parsed.pathname === "/") return parsed.origin;
  return `${parsed.origin}${parsed.pathname.replace(/\/$/u, "")}`;
}

function expectedCanonical(path) {
  return path === "/" ? expectedOrigin : `${expectedOrigin}${path}`;
}

function seededSample(values, count) {
  let state = 0x5e0c2026;
  const selected = new Set();
  while (selected.size < Math.min(count, values.length)) {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    selected.add(state % values.length);
  }
  return [...selected].map((index) => values[index]);
}

async function fetchWithRetry(url, options = {}) {
  let lastError;
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(30_000), ...options });
      if (response.status < 500 && response.status !== 429) return response;
      lastError = new Error(`${url} returned HTTP ${response.status}`);
    } catch (error) { lastError = error; }
    if (attempt < 3) await new Promise((done) => setTimeout(done, attempt * 400));
  }
  throw lastError;
}

async function read(url, userAgent = googlebotUserAgent, options = {}) {
  const response = await fetchWithRetry(url, { ...options, headers: { ...(options.headers ?? {}), "User-Agent": userAgent } });
  return { response, body: await response.text() };
}

async function mapLimit(values, limit, mapper) {
  const results = new Array(values.length);
  let cursor = 0;
  async function worker() {
    while (cursor < values.length) {
      const index = cursor;
      cursor += 1;
      results[index] = await mapper(values[index], index);
    }
  }
  await Promise.all(Array.from({ length: Math.min(limit, values.length) }, worker));
  return results;
}

function assertNoPreviewLeak(values, label) {
  for (const value of values) {
    const parsed = new URL(value);
    assert(parsed.protocol === "https:", `${label} is not HTTPS: ${value}`);
    assert(parsed.origin === expectedOrigin, `${label} does not use the production hostname: ${value}`);
  }
}

function auditIndexableHtml(html, path) {
  const data = metadata(html);
  assert(data.title.length > 10, `${path} has no meaningful title`);
  assert(data.descriptions.length === 1 && data.descriptions[0].length > 50, `${path} has missing or multiple descriptions`);
  assert(data.h1.length > 5, `${path} has no meaningful H1`);
  assert(textContent(html).length > 250, `${path} lacks meaningful SSR HTML`);
  assert(data.canonicals.length === 1, `${path} must have exactly one canonical`);
  assert(normalizedCanonical(data.canonicals[0]) === expectedCanonical(path), `${path} canonical is not self-referential`);
  assert(!data.robots.some((value) => value.includes("noindex")), `${path} is unexpectedly noindex`);
  assert(data.openGraphUrls.length === 1 && normalizedCanonical(data.openGraphUrls[0]) === expectedCanonical(path), `${path} has an invalid Open Graph URL`);
  assertNoPreviewLeak([...data.canonicals, ...data.openGraphUrls], `${path} metadata URL`);
  const jsonLd = parseJsonLd(html);
  assert(jsonLd.errors.length === 0, `${path} contains invalid JSON-LD`);
  const types = structuredTypes(jsonLd.documents);
  assert(types.includes("WebPage") && types.includes("BreadcrumbList"), `${path} lacks WebPage or BreadcrumbList JSON-LD`);
  assert(!types.includes("Article") && !types.includes("NewsArticle"), `${path} makes an unsupported article claim`);
  assertNoPreviewLeak(structuredInternalUrls(jsonLd.documents), `${path} structured-data URL`);
  return { ...data, jsonLdTypes: types, visibleText: textContent(html), links: internalLinks(html) };
}

async function auditPage(path) {
  const url = `${baseUrl}${path}`;
  const [normal, googlebot] = await Promise.all([read(url, browserUserAgent), read(url, googlebotUserAgent)]);
  assert(normal.response.status === 200, `${path} returned HTTP ${normal.response.status} to a browser`);
  assert(googlebot.response.status === normal.response.status, `${path} has inconsistent browser/Googlebot status`);
  const normalAudit = auditIndexableHtml(normal.body, path);
  const googlebotAudit = auditIndexableHtml(googlebot.body, path);
  assert(normalAudit.title === googlebotAudit.title, `${path} title differs for Googlebot`);
  assert(normalAudit.h1 === googlebotAudit.h1, `${path} H1 differs for Googlebot`);
  assert(normalAudit.canonicals[0] === googlebotAudit.canonicals[0], `${path} canonical differs for Googlebot`);
  const lengthRatio = googlebotAudit.visibleText.length / normalAudit.visibleText.length;
  assert(lengthRatio >= 0.98 && lengthRatio <= 1.02, `${path} meaningful content differs for Googlebot`);
  return { path, body: googlebot.body, ...googlebotAudit };
}

const robots = await read(`${baseUrl}/robots.txt`);
assert(robots.response.status === 200, "robots.txt did not return HTTP 200");
const robotsLines = robots.body.split(/\r?\n/gu).map((line) => line.trim()).filter(Boolean);
const normalizedRobotsLines = robotsLines.map((line) => line.toLowerCase());
assert(normalizedRobotsLines.includes("user-agent: *"), "robots.txt lacks User-agent: *");
assert(normalizedRobotsLines.includes("allow: /"), "robots.txt does not allow crawling");
assert(normalizedRobotsLines.includes("disallow: /api/"), "robots.txt does not disallow /api/");
assert(!normalizedRobotsLines.includes("disallow: /"), "robots.txt globally blocks crawling");
assert(normalizedRobotsLines.includes(`sitemap: ${expectedOrigin.toLowerCase()}/sitemap.xml`), "robots.txt has the wrong sitemap URL");

const sitemap = await read(`${baseUrl}/sitemap.xml`);
assert(sitemap.response.status === 200, "sitemap.xml did not return HTTP 200");
assert(/^<\?xml[^>]*>/u.test(sitemap.body) && /<urlset[^>]*xmlns="http:\/\/www\.sitemaps\.org\/schemas\/sitemap\/0\.9"/u.test(sitemap.body), "sitemap.xml is not a valid sitemap document");
const sitemapUrls = [...sitemap.body.matchAll(/<loc>(.*?)<\/loc>/gu)].map((match) => decodeEntities(match[1]));
const sitemapEntries = [...sitemap.body.matchAll(/<url>([\s\S]*?)<\/url>/gu)];
const lastModifiedValues = [...sitemap.body.matchAll(/<lastmod>(.*?)<\/lastmod>/gu)].map((match) => decodeEntities(match[1]));
assert(sitemapEntries.length === sitemapUrls.length && /<\/urlset>\s*$/u.test(sitemap.body), "sitemap.xml has malformed URL entries");
const duplicateSitemapUrls = sitemapUrls.length - new Set(sitemapUrls).size;
assert(duplicateSitemapUrls === 0, `sitemap.xml contains ${duplicateSitemapUrls} duplicate URLs`);
const parsedSitemapUrls = sitemapUrls.map((value) => new URL(value));
assertNoPreviewLeak(sitemapUrls, "sitemap URL");
assert(parsedSitemapUrls.every((url) => !url.search && !url.hash), "sitemap.xml contains query or fragment URLs");
const sitemapPaths = parsedSitemapUrls.map((url) => url.pathname);
const eventUrls = sitemapUrls.filter((url) => /^\/events\/[a-z0-9]+(?:-+[a-z0-9]+)*$/u.test(new URL(url).pathname));
const sitemapTopicPaths = sitemapPaths.filter((path) => path.startsWith("/topics/"));
const malformedSitemapUrls = sitemapPaths.filter((path) => !corePaths.includes(path) && !topicPaths.includes(path) && !/^\/events\/[a-z0-9]+(?:-+[a-z0-9]+)*$/u.test(path));
assert(malformedSitemapUrls.length === 0, `sitemap.xml contains malformed URLs: ${malformedSitemapUrls.join(", ")}`);
assert(corePaths.every((path) => sitemapPaths.includes(path)), "sitemap.xml omits a core page");
assert(topicPaths.every((path) => sitemapPaths.includes(path)), "sitemap.xml omits an allowed topic page");
assert(sitemapTopicPaths.length === topicPaths.length, "sitemap.xml contains an unexpected topic page");
const apiResponse = await fetchWithRetry(`${baseUrl}/api/events?pageSize=1`);
assert(apiResponse.status === 200, "public events API did not return HTTP 200");
const apiEventCount = Number((await apiResponse.json()).total);
assert(eventUrls.length === apiEventCount, `sitemap has ${eventUrls.length} events while the API reports ${apiEventCount}`);
assert(sitemapUrls.length === corePaths.length + topicPaths.length + eventUrls.length, "sitemap inventory categories do not add up");
assert(lastModifiedValues.length === eventUrls.length && lastModifiedValues.every((value) => !Number.isNaN(Date.parse(value))), "sitemap event lastmod values are missing or malformed");

const eventSampleUrls = seededSample(eventUrls, 30);
assert(eventSampleUrls.length === 30, "fewer than 30 event pages are available for the audit");
const auditedCoreAndTopics = await mapLimit([...corePaths, ...topicPaths], 5, auditPage);
const auditedEvents = await mapLimit(eventSampleUrls, 6, async (canonical) => {
  const path = new URL(canonical).pathname;
  const audit = await auditPage(path);
  const publishedAt = attribute(audit.body.match(/<time\b[^>]*>/iu)?.[0] ?? "", "datetime");
  const publishedDate = publishedAt.slice(0, 10);
  assert(!Number.isNaN(Date.parse(publishedAt)) && audit.title.includes(publishedDate) && audit.descriptions[0].includes(publishedDate), `${path} has inconsistent event dates`);
  assert(/Reaction V2/iu.test(audit.body), `${path} lacks Reaction V2 content`);
  assert(/Read original source/iu.test(audit.body), `${path} lacks a source citation`);
  assert(/Related assets/iu.test(audit.body), `${path} lacks asset context`);
  assert(audit.links.some((href) => href === "/events"), `${path} lacks a crawlable Events link`);
  return audit;
});

const eventTitles = auditedEvents.map((page) => page.title);
const eventDescriptions = auditedEvents.map((page) => page.descriptions[0]);
assert(new Set(eventTitles).size === eventTitles.length, "sampled event pages contain duplicate titles");
assert(new Set(eventDescriptions).size === eventDescriptions.length, "sampled event pages contain duplicate descriptions");

const auditedTopics = auditedCoreAndTopics.filter((page) => page.path.startsWith("/topics/"));
assert(new Set(auditedTopics.map((page) => page.title)).size === topicPaths.length, "topic pages contain duplicate titles");
assert(new Set(auditedTopics.map((page) => page.descriptions[0])).size === topicPaths.length, "topic pages contain duplicate descriptions");
const topicRecords = {};
for (const topic of auditedTopics) {
  const matchedRecords = Number(topic.body.match(/<dt[^>]*>Matched records<\/dt><dd[^>]*>(\d+)<\/dd>/iu)?.[1] ?? 0);
  assert(matchedRecords >= 5, `${topic.path} is too thin (${matchedRecords} matched records)`);
  assert(topic.links.some((href) => href.startsWith("/events/")), `${topic.path} lacks crawlable event links`);
  topicRecords[topic.path] = matchedRecords;
}

const home = auditedCoreAndTopics.find((page) => page.path === "/");
assert(home?.verification.length === 1 && home.verification[0].length > 10, "homepage lacks Google site verification metadata");
assert(home.links.includes("/events") && home.links.includes("/ai") && topicPaths.every((path) => home.links.includes(path)), "homepage lacks required crawlable navigation links");
assert(home.jsonLdTypes.includes("WebSite"), "homepage lacks WebSite JSON-LD");
const ai = auditedCoreAndTopics.find((page) => page.path === "/ai");
for (const phrase of ["AI Research", "historical BTC, ETH and SOL reactions", "Reaction V2"]) assert(ai.visibleText.includes(phrase), `/ai SSR HTML lacks ${phrase}`);
assert(home.body.includes("googletagmanager.com/gtag/js?id=G-57LB5R97PG") && home.body.includes("gtag('config', 'G-57LB5R97PG')"), "GA4 is missing from the production SSR response");

const queryCases = [
  { path: "/events?asset=ETH&sort=growth", canonical: "/events" },
  { path: `${new URL(eventSampleUrls[0]).pathname}?utm_source=seo-final`, canonical: new URL(eventSampleUrls[0]).pathname },
  { path: `${topicPaths[0]}?view=filtered`, canonical: topicPaths[0] },
];
for (const item of queryCases) {
  const { response, body } = await read(`${baseUrl}${item.path}`);
  assert(response.status === 200, `${item.path} returned HTTP ${response.status}`);
  const data = metadata(body);
  assert(data.canonicals.length === 1 && normalizedCanonical(data.canonicals[0]) === expectedCanonical(item.canonical), `${item.path} has the wrong canonical`);
  assert(data.robots.some((value) => value.includes("noindex") && value.includes("follow")), `${item.path} must be noindex,follow`);
}
const aiQuestion = "seo-final-user-question-must-not-render";
const aiQuery = await read(`${baseUrl}/ai?question=${aiQuestion}`);
assert(aiQuery.response.status === 200, "/ai query state returned a non-200 response");
assert(normalizedCanonical(metadata(aiQuery.body).canonicals[0]) === expectedCanonical("/ai"), "/ai query state changed the canonical");
assert(!textContent(aiQuery.body).includes(aiQuestion), "/ai rendered a user question into indexable SSR content");

for (const query of ["asset=BTC&sort=growth", "q=ETF&page=2", "source=decrypt&horizon=24h"]) {
  const response = await fetchWithRetry(`${baseUrl}/?${query}`, { redirect: "manual", headers: { "User-Agent": googlebotUserAgent } });
  assert([307, 308].includes(response.status), `legacy query ${query} returned HTTP ${response.status}`);
  const location = new URL(response.headers.get("location"), baseUrl);
  assert(location.pathname === "/events" && location.searchParams.size > 0, `legacy query ${query} lost its filter state`);
  const followed = await fetchWithRetry(location, { redirect: "follow", headers: { "User-Agent": googlebotUserAgent } });
  assert(followed.status === 200, `legacy query ${query} redirects to HTTP ${followed.status}`);
}

for (const path of ["/events/missing-event-seo-final-a1b2c3d4", "/topics/not-a-real-topic", "/not-a-real-route/seo-final"]) {
  const response = await fetchWithRetry(`${baseUrl}${path}`, { headers: { "User-Agent": googlebotUserAgent } });
  assert(response.status === 404, `${path} is a soft 404 with HTTP ${response.status}`);
}

const allAudits = [...auditedCoreAndTopics, ...auditedEvents];
const uniqueInternalLinks = [...new Set(allAudits.flatMap((page) => page.links))].filter((href) => !href.startsWith("/_next/") && !href.startsWith("/api/"));
const sampledInternalLinks = seededSample(uniqueInternalLinks, 50);
assert(sampledInternalLinks.length === 50, `only ${sampledInternalLinks.length} internal links were available for the required sample`);
await mapLimit(sampledInternalLinks, 8, async (href) => {
  const response = await fetchWithRetry(`${baseUrl}${href}`, { headers: { "User-Agent": googlebotUserAgent } });
  assert(response.status < 400, `internal link ${href} returned HTTP ${response.status}`);
});

console.log(JSON.stringify({
  production_origin: expectedOrigin,
  inventory: { core: corePaths.length, topics: topicPaths.length, events: eventUrls.length, total: sitemapUrls.length, api_events: apiEventCount },
  robots: "PASS",
  sitemap: { valid: true, duplicate_urls: duplicateSitemapUrls, malformed_urls: malformedSitemapUrls.length, query_urls: 0, preview_urls: 0 },
  canonical_sample: { checked: allAudits.length, correct: allAudits.length },
  googlebot_parity: { checked: allAudits.length, mismatches: 0 },
  event_sample: { checked: auditedEvents.length, duplicate_titles: 0, duplicate_descriptions: 0, unexpected_404s: 0 },
  metadata: { pages_checked: allAudits.length, missing_titles: 0, missing_descriptions: 0, duplicate_event_titles: 0, duplicate_event_descriptions: 0, duplicate_topic_titles: 0, duplicate_topic_descriptions: 0 },
  topics: { checked: auditedTopics.length, indexable: auditedTopics.length, thin: 0, matched_records: topicRecords },
  structured_data: { parsing_errors: 0, unsupported_article_claims: 0 },
  internal_links: { checked: sampledInternalLinks.length, broken: 0 },
  true_404s: 3,
  google_verification: true,
  ga4_ssr_present: true,
  ai_query_state_rendered: false,
  ai_query_canonical: `${expectedOrigin}/ai`,
}, null, 2));
