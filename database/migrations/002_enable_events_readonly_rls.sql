-- Public MVP access: anonymous users may only read events.
-- Imports continue to use the database owner or a server-only service role.

BEGIN;

ALTER TABLE public.events ENABLE ROW LEVEL SECURITY;

REVOKE ALL PRIVILEGES ON TABLE public.events FROM PUBLIC;
REVOKE ALL PRIVILEGES ON TABLE public.events FROM anon;
REVOKE ALL PRIVILEGES ON TABLE public.events FROM authenticated;

GRANT USAGE ON SCHEMA public TO anon;
GRANT SELECT ON TABLE public.events TO anon;

DROP POLICY IF EXISTS events_public_read_only ON public.events;
CREATE POLICY events_public_read_only
    ON public.events
    FOR SELECT
    TO anon
    USING (true);

COMMIT;
