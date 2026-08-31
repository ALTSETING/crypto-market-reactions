import { describe, expect, it, vi } from "vitest";

import { OpenAiGeneralAnswerProvider } from "@/lib/ai-search/general-provider";

function response(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("general explanation provider", () => {
  it("uses bounded server-only input and store false", async () => {
    const onUsage = vi.fn();
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
    expect(onUsage).toHaveBeenCalledWith(expect.objectContaining({ inputTokens: 30, outputTokens: 15 }));
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
});
