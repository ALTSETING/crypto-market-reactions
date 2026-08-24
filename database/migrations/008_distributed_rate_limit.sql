-- Atomic shared fixed-window limiter using the existing Supabase database.
-- Raw client IPs are never persisted; the server sends a one-way hash.

BEGIN;

CREATE TABLE IF NOT EXISTS public.api_rate_limit_buckets (
    key_hash text NOT NULL,
    window_started_at timestamptz NOT NULL,
    request_count integer NOT NULL CHECK (request_count > 0),
    PRIMARY KEY (key_hash, window_started_at)
);

CREATE INDEX IF NOT EXISTS ix_api_rate_limit_buckets_window_started_at
    ON public.api_rate_limit_buckets (window_started_at);

ALTER TABLE public.api_rate_limit_buckets ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.api_rate_limit_buckets FROM PUBLIC, anon, authenticated;

CREATE OR REPLACE FUNCTION public.consume_events_rate_limit(
    p_key_hash text,
    p_limit integer DEFAULT 60,
    p_window_seconds integer DEFAULT 60
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    v_now timestamptz := clock_timestamp();
    v_window timestamptz;
    v_count integer;
    v_reset_ms bigint;
BEGIN
    IF p_key_hash !~ '^[0-9a-f]{64}$' OR p_limit < 1 OR p_limit > 10000
       OR p_window_seconds < 1 OR p_window_seconds > 86400 THEN
        RAISE EXCEPTION 'invalid rate limit arguments';
    END IF;
    v_window := to_timestamp(floor(extract(epoch FROM v_now) / p_window_seconds) * p_window_seconds);
    INSERT INTO public.api_rate_limit_buckets(key_hash, window_started_at, request_count)
    VALUES (p_key_hash, v_window, 1)
    ON CONFLICT (key_hash, window_started_at)
    DO UPDATE SET request_count = public.api_rate_limit_buckets.request_count + 1
    RETURNING request_count INTO v_count;

    -- Deterministically remove at most 1,000 expired buckets per request.
    DELETE FROM public.api_rate_limit_buckets
    WHERE ctid IN (
        SELECT ctid
        FROM public.api_rate_limit_buckets
        WHERE window_started_at < v_now - interval '2 days'
        ORDER BY window_started_at
        LIMIT 1000
    );
    v_reset_ms := floor(extract(epoch FROM v_window + make_interval(secs => p_window_seconds)) * 1000);
    RETURN jsonb_build_object(
        'allowed', v_count <= p_limit,
        'limit', p_limit,
        'remaining', greatest(0, p_limit - v_count),
        'reset_at_epoch_ms', v_reset_ms
    );
END;
$$;

REVOKE ALL ON FUNCTION public.consume_events_rate_limit(text, integer, integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.consume_events_rate_limit(text, integer, integer) TO service_role;

COMMIT;
