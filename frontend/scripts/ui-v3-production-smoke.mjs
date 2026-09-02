import { spawn } from "node:child_process";
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const chrome = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const port = 9555;
const baseUrl = (process.env.SMOKE_BASE_URL ?? "http://localhost:3000").replace(/\/$/u, "");
const screenshotDir = resolve(process.env.SMOKE_SCREENSHOT_DIR ?? join(tmpdir(), "cmr-ui-v3-smoke"));
const profile = await mkdtemp(join(tmpdir(), "cmr-ui-v3-chrome-"));
const browser = spawn(chrome, [
  "--headless=new",
  "--disable-gpu",
  "--no-first-run",
  "--no-default-browser-check",
  `--remote-debugging-port=${port}`,
  `--user-data-dir=${profile}`,
  "about:blank",
], { stdio: "ignore", windowsHide: true });
const delay = (ms) => new Promise((done) => setTimeout(done, ms));

async function findTarget() {
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
    this.socket.onmessage = (event) => {
      const message = JSON.parse(event.data);
      if (!message.id) return;
      const pending = this.pending.get(message.id);
      if (!pending) return;
      this.pending.delete(message.id);
      if (message.error) pending.reject(new Error(message.error.message));
      else pending.resolve(message.result);
    };
  }
  async ready() {
    if (this.socket.readyState === WebSocket.OPEN) return;
    await new Promise((done, reject) => { this.socket.onopen = done; this.socket.onerror = reject; });
  }
  send(method, params = {}) {
    const id = this.nextId++;
    return new Promise((done, reject) => {
      this.pending.set(id, { resolve: done, reject });
      this.socket.send(JSON.stringify({ id, method, params }));
    });
  }
  close() { this.socket.close(); }
}

async function evaluate(cdp, expression) {
  const response = await cdp.send("Runtime.evaluate", { expression, returnByValue: true });
  if (response.exceptionDetails) throw new Error(response.exceptionDetails.text);
  return response.result.value;
}

async function inspect(cdp, width) {
  await cdp.send("Emulation.setDeviceMetricsOverride", { width, height: width === 390 ? 844 : 1000, deviceScaleFactor: 1, mobile: width === 390 });
  await cdp.send("Page.navigate", { url: `${baseUrl}/ai` });
  await delay(1500);
  const state = await evaluate(cdp, `(() => {
    const nav = document.querySelector('nav[aria-label="Primary"]')?.getBoundingClientRect();
    const theme = document.querySelector('button[aria-label^="Switch to"]')?.getBoundingClientRect();
    const examples = document.querySelector('button[aria-controls="ai-example-questions"]');
    return {
      width: window.innerWidth,
      overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      navVisible: Boolean(nav && nav.left >= 0 && nav.right <= window.innerWidth),
      themeVisible: Boolean(theme && theme.left >= 0 && theme.right <= window.innerWidth),
      examplesExpanded: examples?.getAttribute('aria-expanded'),
      promptVisible: Boolean(document.querySelector('#ai-search-question')),
      heading: document.querySelector('h1')?.textContent?.trim(),
    };
  })()`);
  const capture = await cdp.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
  await writeFile(join(screenshotDir, `ai-${width}.png`), Buffer.from(capture.data, "base64"));
  return state;
}

let cdp;
try {
  await mkdir(screenshotDir, { recursive: true });
  cdp = new CdpClient((await findTarget()).webSocketDebuggerUrl);
  await cdp.ready();
  await cdp.send("Page.enable");
  const states = { mobile: await inspect(cdp, 390), desktop: await inspect(cdp, 1440) };
  for (const state of Object.values(states)) {
    if (state.overflow !== 0 || !state.navVisible || !state.themeVisible || !state.promptVisible || state.examplesExpanded !== "false") {
      throw new Error(`UI V3 smoke failed: ${JSON.stringify(states)}`);
    }
  }
  console.log(JSON.stringify({ url: `${baseUrl}/ai`, screenshotDir, states }, null, 2));
} finally {
  cdp?.close();
  browser.kill();
}
