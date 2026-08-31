import { describe, expect, it, vi } from "vitest";

import { OpenAiGeneralAnswerProvider } from "@/lib/ai-search/general-provider";

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("general explanation provider", () => {
  it("uses bounded server-only input and store false", async () => {
    const onUsage = vi.fn();
    const timeoutSpy = vi.spyOn(globalThis, "setTimeout");
    const telemetrySpy = vi.spyOn(console, "info").mockImplementation(() => undefined);
    const fetchImpl = vi.fn(async (_url: string | URL | Request, init?: RequestInit) => {
      const request = JSON.parse(String(init?.body));
      expect(request.store).toBe(false);
      expect(request.max_output_tokens).toBe(700);
      expect(request.input).toContain('"topic":"staking"');
      return response({ output_text: "Staking helps proof-of-stake networks coordinate validators without implying guaranteed returns.", model: "gpt-5-mini", usage: { input_tokens: 30, output_tokens: 15, total_tokens: 45 } });
    });
    const provider = new OpenAiGeneralAnswerProvider({ apiKey: "server-secret", model: "gpt-5-mini", fetchImpl, onUsage });
    await expect(provider.answer({ question: "What is staking?", language: "en", topic: "staking" })).resolves.toContain("Staking");
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    expect(timeoutSpy).toHaveBeenCalledWith(expect.any(Function), 25_000);
    expect(onUsage).toHaveBeenCalledWith(expect.objectContaining({ inputTokens: 30, outputTokens: 15 }));
    expect(telemetrySpy).toHaveBeenCalledWith("AI general provider attempt", {
      attempt: 1,
      model: "gpt-5-mini",
      latencyMs: expect.any(Number),
      outcome: "success",
      status: 200,
      tokenUsage: { input: 30, cachedInput: 0, output: 15, total: 45 },
      estimatedCostUsd: expect.any(Number),
    });
    expect(JSON.stringify(telemetrySpy.mock.calls)).not.toContain("What is staking?");
    expect(JSON.stringify(telemetrySpy.mock.calls)).not.toContain("server-secret");
    timeoutSpy.mockRestore();
    telemetrySpy.mockRestore();
  });

  it("retries once, rejects secret-like output, and exposes no fallback answer", async () => {
    const fetchImpl = vi.fn()
      .mockResolvedValueOnce(response({}, 500))
      .mockResolvedValueOnce(response({ output_text: "OPENAI_API_KEY=unsafe" }));
    const provider = new OpenAiGeneralAnswerProvider({ apiKey: "server-secret", model: "gpt-5-mini", fetchImpl });
    await expect(provider.answer({ question: "What is Bitcoin?", language: "en", topic: "bitcoin" })).rejects.toThrow("temporarily unavailable");
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });

  it("does not retry non-transient failures or oversized input", async () => {
    const fetchImpl = vi.fn(async () => response({}, 400));
    const provider = new OpenAiGeneralAnswerProvider({ apiKey: "server-secret", model: "gpt-5-mini", fetchImpl });
    await expect(provider.answer({ question: "What is Bitcoin?", language: "en", topic: "bitcoin" })).rejects.toThrow("temporarily unavailable");
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    await expect(provider.answer({ question: "x".repeat(501), language: "en", topic: "bitcoin" })).rejects.toThrow("too long");
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it("applies the timeout to each attempt and retries one timeout once", async () => {
    const telemetrySpy = vi.spyOn(console, "info").mockImplementation(() => undefined);
    const fetchImpl = vi.fn(async (_url: string | URL | Request, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")), { once: true });
    }));
    const provider = new OpenAiGeneralAnswerProvider({ apiKey: "server-secret", model: "gpt-5-mini", fetchImpl, timeoutMs: 5 });

    await expect(provider.answer({ question: "What is Bitcoin?", language: "en", topic: "bitcoin" })).rejects.toThrow("temporarily unavailable");

    expect(fetchImpl).toHaveBeenCalledTimes(2);
    expect(telemetrySpy.mock.calls.map(([, metric]) => metric)).toEqual([
      expect.objectContaining({ attempt: 1, model: "gpt-5-mini", outcome: "timeout", status: null }),
      expect.objectContaining({ attempt: 2, model: "gpt-5-mini", outcome: "timeout", status: null }),
    ]);
    telemetrySpy.mockRestore();
  });
});
