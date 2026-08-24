# Reaction V2 production cutover report

- Cutover time: 2026-08-23T16:21:14.743617+00:00.
- Production: `https://crypto-market-reactions-nu.vercel.app` / Supabase project `ickflwksigaotygtdyko`.
- Backup: `data/website/backups/pre_reaction_v2_cutover/`; hash `11f84ef17c4c8e21a86f8391b36c217a65c3de9fa178ee91fbc76dff7cbc02d1`.
- Migration: `database/migrations/007_reaction_v2_cutover.sql`, applied in the same transaction as the data import. RLS was not changed.
- Rows staged / matched / updated: 7,878 / 7,878 / 7,878. Unknown IDs: 0. Missing IDs: 0.
- Post-update DB checks: 7,878 rows, 7,878 unique event IDs, 7,878 unique slugs, 0 V2 mismatches, 0 non-reaction changes.
- Random DB check: 100 events and all 3,400 staged reaction fields, 0 mismatches.
- Website core, API/CSV, browser, SEO, and security checks: PASS. Direct anon SELECT: HTTP 401.
- Rollback: `python -m scripts.database.reaction_v2_rollback --apply`; it restores the backed-up V1 reaction fields transactionally and removes V2-only quality columns after a zero-mismatch verification.
- Database production status: PASS.
- Frontend V2 production deployment: `BLOCKED — USER ACTION REQUIRED` because Vercel CLI is logged out. The verified local build is ready; no git push was performed.

The existing production frontend continues to serve the V2 database safely. One of 174 checked rendered cells remained stale in the server-side one-hour cache; it is not a DB mismatch and does not justify rollback. The new frontend's default 1h ranking, dynamic coverage, related/context split, and updated schema copy passed local production-build browser validation but await an authenticated Vercel deployment.
