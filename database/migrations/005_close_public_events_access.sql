-- Server-only dataset access. Next.js uses a Supabase secret/service-role key.
-- RLS stays enabled; browser roles receive no table privileges or policies.

BEGIN;

ALTER TABLE public.events ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Public read access" ON public.events;
DROP POLICY IF EXISTS events_public_read_only ON public.events;

REVOKE ALL PRIVILEGES ON TABLE public.events FROM PUBLIC;
REVOKE ALL PRIVILEGES ON TABLE public.events FROM anon;
REVOKE ALL PRIVILEGES ON TABLE public.events FROM authenticated;

GRANT USAGE ON SCHEMA public TO service_role;
GRANT SELECT ON TABLE public.events TO service_role;

COMMIT;
