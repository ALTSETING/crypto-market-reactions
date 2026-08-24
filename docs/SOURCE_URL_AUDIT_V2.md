# Source URL Audit V2

- Existing production URLs inventoried: **7,878**.
- Statuses: `{"blocked_403": 52, "unknown": 634, "verified_200": 6963, "verified_source_artifact": 229}`.
- Title verification: `{"exact": 6961, "unverified": 917}`.
- Material title-drift candidates: **0**.
- Manual URL package: **100** prioritized rows.

Publisher pages already present in the Scrapy cache use their captured HTTP status and capture timestamp; this avoids re-hammering thousands of news pages. Stage16b accepted official-source records retain a distinct `verified_source_artifact` status rather than falsely claiming a new HTTP 200. HTTP 403/429 are classified as access restrictions, not dead links. No CAPTCHA, proxy, paywall, login, or anti-bot bypass was attempted. CoinDesk's current sitemap request returned 429/Vercel Security Checkpoint and was not retried.
