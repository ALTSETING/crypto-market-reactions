# Security policy

## Reporting a vulnerability

Please do not open a public issue for a suspected vulnerability or exposed
credential. Use the repository's **Security → Report a vulnerability** flow so
the report is handled through a private GitHub Security Advisory.

Include the affected path or endpoint, reproduction steps, expected impact,
and any suggested mitigation. Do not include live credentials or personal data
in the report.

## Credential model

- Root `.env` and `frontend/.env.local` are local-only and ignored by Git.
- The frontend accepts only a Supabase project URL and an anon/publishable key.
- Database passwords, pooler URLs, `service_role`, `sb_secret_...`, and private
  keys must never be placed in frontend files or GitHub Actions variables used
  by client builds.
- Supabase RLS and the anon SELECT-only policy are part of the security boundary.

If a credential is committed, revoke or rotate it immediately before removing
it from Git history. Deleting it only in a later commit is not sufficient.
