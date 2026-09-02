import { spawn } from "node:child_process";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

const chrome = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const port = 9444;
const baseUrl = (process.env.SMOKE_BASE_URL ?? "http://localhost:3000").replace(/\/$/, "");
const profile = await mkdtemp(join(tmpdir(), "cmr-ai-mobile-"));
const browser = spawn(chrome, [
  "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
  `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`, `${baseUrl}/ai`,
], { stdio: "ignore", windowsHide: true });
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function target() {
  for (let attempt = 0; attempt < 50; attempt += 1) {
    try {
      const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
      const page = targets.find((item) => item.type === "page");
      if (page) return page;
    } catch {}
    await delay(200);
  }
  throw new Error("Chrome DevTools target was unavailable.");
}

class CdpClient {
  constructor(url) {
    this.socket = new WebSocket(url);
    this.nextId = 1;
    this.pending = new Map();
    this.errors = [];
    this.socket.onmessage = (event) => {
      const message = JSON.parse(event.data);
      if (!message.id) {
        if (message.method === "Log.entryAdded" && message.params?.entry?.level === "error") this.errors.push(message.params.entry.text);
        if (message.method === "Runtime.exceptionThrown") this.errors.push(message.params?.exceptionDetails?.text ?? "Runtime exception");
        return;
      }
      const handler = this.pending.get(message.id);
      if (!handler) return;
      this.pending.delete(message.id);
      if (message.error) handler.reject(new Error(message.error.message));
      else handler.resolve(message.result);
    };
  }
  async ready() {
    if (this.socket.readyState === WebSocket.OPEN) return;
    await new Promise((resolve, reject) => { this.socket.onopen = resolve; this.socket.onerror = reject; });
  }
  send(method, params = {}) {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.socket.send(JSON.stringify({ id, method, params }));
    });
  }
  close() { this.socket.close(); }
}

async function evaluate(cdp, expression) {
  const response = await cdp.send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (response.exceptionDetails) throw new Error(response.exceptionDetails.text);
  return response.result.value;
}

async function viewport(cdp, width) {
  await cdp.send("Emulation.setDeviceMetricsOverride", { width, height: width === 1440 ? 1000 : 844, deviceScaleFactor: 1, mobile: width < 600 });
  await delay(150);
  return evaluate(cdp, `(() => {
    const root = document.documentElement;
    const table = document.querySelector('[data-testid="historical-table-scroll"]');
    const nav = document.querySelector('nav[aria-label="Primary"]')?.getBoundingClientRect();
    const heading = document.querySelector('main h1')?.getBoundingClientRect();
    return {
      width: innerWidth,
      clientWidth: root.clientWidth,
      scrollWidth: root.scrollWidth,
      overflow: Math.max(0, root.scrollWidth - root.clientWidth),
      table: table ? { clientWidth: table.clientWidth, scrollWidth: table.scrollWidth, overflowX: getComputedStyle(table).overflowX } : null,
      navigationClear: Boolean(nav && heading && nav.bottom <= heading.top),
    };
  })()`);
}

async function submit(cdp, question) {
  await evaluate(cdp, `(() => {
    const input = document.querySelector('#ai-search-question');
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
    setter.call(input, ${JSON.stringify(question)});
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.dispatchEvent(new Event('change', { bubbles: true }));
  })()`);
  await delay(250);
  const submitted = await evaluate(cdp, `(() => {
    const button = document.querySelector('button[type="submit"]');
    if (!button || button.disabled) return false;
    button.click();
    return true;
  })()`);
  if (!submitted) throw new Error("AI submit button remained disabled.");
  for (let attempt = 0; attempt < 100; attempt += 1) {
    const ready = await evaluate(cdp, `!document.body.innerText.includes('Analyzing…') && (Boolean(document.querySelector('[aria-label="AI explanation"]')) || document.body.innerText.includes('Request not supported:') || document.body.innerText.includes('unavailable'))`);
    if (ready) return;
    await delay(100);
  }
  throw new Error("AI answer did not finish within the smoke window.");
}

let cdp;
try {
  const page = await target();
  cdp = new CdpClient(page.webSocketDebuggerUrl);
  await cdp.ready();
  await cdp.send("Page.enable");
  await cdp.send("Runtime.enable");
  await cdp.send("Log.enable");
  await cdp.send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  await cdp.send("Page.reload");
  await delay(2_000);

  const states = {};
  await submit(cdp, "How did SOL react historically?");
  for (const width of [320, 360, 375, 390, 430, 1440]) states[width] = await viewport(cdp, width);

  await submit(cdp, "What is Ethereum Layer 2?");
  states.general = await viewport(cdp, 390);
  await submit(cdp, "На які новини ETH найчастіше реагував зростанням за 24h?");
  states.topicRanking = await viewport(cdp, 390);
  await submit(cdp, "ETF approvals or institutional purchases — which had a stronger ETH 24h reaction?");
  states.comparison = await viewport(cdp, 390);
  await submit(cdp, "Як ETH реагував на надзвичайно довгу назву інституційної купівлі з поясненням ліквідності та ринкового впливу через 24 години?");
  states.longUkrainian = await viewport(cdp, 320);

  const failures = Object.entries(states).filter(([, state]) => state.overflow !== 0 || !state.navigationClear);
  const tableStates = [320, 360, 375, 390, 430].map((width) => states[width].table);
  if (tableStates.some((table) => !table || table.overflowX !== "auto" || table.scrollWidth < table.clientWidth)) {
    throw new Error("Historical table is not isolated in its horizontal scroll wrapper.");
  }
  if (failures.length > 0) throw new Error(`Mobile layout failures: ${JSON.stringify(failures)}`);
  const criticalErrors = cdp.errors.filter((message) => !/favicon\.ico|Failed to load resource.*404/iu.test(message));
  if (criticalErrors.length > 0) throw new Error(`Critical browser errors: ${JSON.stringify(criticalErrors)}`);
  console.log(JSON.stringify({ states, criticalConsoleErrors: criticalErrors.length }, null, 2));
} finally {
  cdp?.close();
  browser.kill();
}
