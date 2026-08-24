export interface RateLimitResult {
  allowed: boolean;
  limit: number;
  remaining: number;
  resetAt: number;
}

export interface RateLimiter {
  consume(key: string, now?: number): RateLimitResult | Promise<RateLimitResult>;
}

interface Bucket {
  count: number;
  resetAt: number;
}

export class InMemoryRateLimiter implements RateLimiter {
  private readonly buckets = new Map<string, Bucket>();

  constructor(
    private readonly limit = 60,
    private readonly windowMs = 60_000,
  ) {}

  consume(key: string, now = Date.now()): RateLimitResult {
    let bucket = this.buckets.get(key);
    if (!bucket || bucket.resetAt <= now) {
      bucket = { count: 0, resetAt: now + this.windowMs };
    }
    bucket.count += 1;
    this.buckets.set(key, bucket);

    if (this.buckets.size > 10_000) this.removeExpired(now);

    return {
      allowed: bucket.count <= this.limit,
      limit: this.limit,
      remaining: Math.max(0, this.limit - bucket.count),
      resetAt: bucket.resetAt,
    };
  }

  private removeExpired(now: number): void {
    for (const [key, bucket] of this.buckets) {
      if (bucket.resetAt <= now) this.buckets.delete(key);
    }
  }
}

export class SupabaseRateLimiter implements RateLimiter {
  constructor(
    private readonly url: string,
    private readonly serverKey: string,
    private readonly fallback: RateLimiter,
    private readonly limit = 60,
    private readonly windowMs = 60_000,
  ) {}

  async consume(key: string, now = Date.now()): Promise<RateLimitResult> {
    try {
      const digest = await crypto.subtle.digest(
        "SHA-256",
        new TextEncoder().encode(`${this.serverKey.slice(-24)}:${key}`),
      );
      const keyHash = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
      const response = await fetch(`${this.url.replace(/\/$/, "")}/rest/v1/rpc/consume_events_rate_limit`, {
        method: "POST",
        headers: {
          apikey: this.serverKey,
          Authorization: `Bearer ${this.serverKey}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          p_key_hash: keyHash,
          p_limit: this.limit,
          p_window_seconds: Math.ceil(this.windowMs / 1000),
        }),
        cache: "no-store",
      });
      if (!response.ok) throw new Error(`rate limit RPC returned ${response.status}`);
      const value = (await response.json()) as {
        allowed: boolean;
        limit: number;
        remaining: number;
        reset_at_epoch_ms: number;
      };
      return {
        allowed: value.allowed,
        limit: value.limit,
        remaining: value.remaining,
        resetAt: value.reset_at_epoch_ms,
      };
    } catch (error) {
      console.warn("Distributed rate limiter unavailable; using process-local fallback", {
        name: error instanceof Error ? error.name : "UnknownError",
      });
      return this.fallback.consume(key, now);
    }
  }
}

const localEventsRateLimiter = new InMemoryRateLimiter(60, 60_000);
const supabaseUrl = process.env.SUPABASE_URL?.trim();
const supabaseServerKey =
  process.env.SUPABASE_SECRET_KEY?.trim() || process.env.SUPABASE_SERVICE_ROLE_KEY?.trim();

export const eventsRateLimiter: RateLimiter =
  supabaseUrl && supabaseServerKey
    ? new SupabaseRateLimiter(supabaseUrl, supabaseServerKey, localEventsRateLimiter)
    : localEventsRateLimiter;

export function getClientIp(headers: Headers): string {
  const forwarded = headers.get("x-forwarded-for")?.split(",")[0]?.trim();
  const candidate = forwarded || headers.get("x-real-ip")?.trim() || "unknown";
  return candidate.slice(0, 128);
}
