# SOL asset manual review

Generated after full reclassification on 2026-08-23.

- Full machine-readable review: `reports/sol_asset_review.csv` (452 events).
- Manual sample: 20 distinct events across all five remaining SOL sources.
- Generic Coinbase SEC filings in SOL: 0.
- Review result: 20 PASS, 0 FAIL after correction.

During the first review pass, an SEC mortgage document containing the place name
`Solana Beach` was identified as a false positive. The classifier was corrected
with a general geographic-context exclusion, a regression test was added, the
complete dataset was rebuilt, and that event is no longer assigned to SOL.

| Source | Slug | Title | Manual result |
|---|---|---|---|
| sec | `document-2021-0fdff7f7` | Document | PASS — body explicitly discusses the Solana blockchain platform; relevance 1.00 |
| sec | `document-2021-8b08cb99` | Document | PASS — body explicitly discusses the Solana blockchain platform; relevance 1.00 |
| sec | `document-2021-d8e7237d` | Document | PASS — body explicitly discusses the Solana blockchain platform; relevance 1.00 |
| sec | `document-2020-83e1913f` | Document | PASS — body explicitly discusses the Solana blockchain platform; relevance 1.00 |
| sol_github | `solana-labs-solana-always-contact-release-solana-com-over-https-2022-65fa21e1` | solana-labs/solana Always contact release.solana.com over https | PASS — repository/title evidence |
| sol_github | `solana-labs-solana-attack-diary-attempting-to-bypass-sigverify-2020-f2becf8f` | solana-labs/solana Attack Diary: Attempting to Bypass Sigverify | PASS — repository/title evidence |
| sol_github | `solana-labs-solana-change-mainnet-beta-endpoint-2022-4ae77fee` | solana-labs/solana change mainnet-beta endpoint | PASS — repository/title evidence |
| sol_github | `solana-labs-solana-chore-bump-anyhow-from-1-0-52-to-1-0-53-22743-2022-dd350df0` | solana-labs/solana chore: bump anyhow from 1.0.52 to 1.0.53 (#22743) | PASS — repository/title evidence |
| coindesk | `ada-sol-xrp-altcoins-trump-named-for-crypto-reserve-lag-btc-ahead-of-white-house-summit-2025-c787a449` | ADA, SOL, XRP: Altcoins Trump Named For Crypto Reserve Lag BTC Ahead of White House Summit | PASS — explicit SOL ticker in title |
| coindesk | `alameda-moves-16-million-in-solana-s-sol-token-for-possible-creditor-payments-2026-1fdff118` | Alameda moves $16 million in Solana's SOL token for possible creditor payments | PASS — explicit Solana/SOL in title |
| coindesk | `alchemy-acquires-solana-developer-dexterlab-for-undisclosed-fee-2025-49c93df2` | Alchemy Acquires Solana Developer DexterLab For Undisclosed Fee | PASS — explicit Solana in title |
| coindesk | `base-takes-solana-s-crown-in-token-creation-as-coinbase-s-socialfi-ignites-zora-boom-2025-4f503cdf` | Base Takes Solana's Crown in Token Creation as Coinbase's 'SocialFi' Ignites Zora Boom | PASS — explicit Solana in title |
| decrypt | `altcoins-defy-bitcoin-slump-as-xrp-solana-notch-double-digit-gains-2026-1dbffbf0` | Altcoins Defy Bitcoin Slump as XRP, Solana Notch Double-Digit Gains | PASS — explicit Solana in title |
| decrypt | `altcoins-xrp-sol-doge-slump-as-trump-reignites-trade-tensions-passes-big-beautiful-bill-2025-29735d11` | Altcoins XRP, SOL, DOGE Slump as Trump Reignites Trade Tensions, Passes ‘Big, Beautiful Bill’ | PASS — explicit SOL ticker in title |
| decrypt | `altcoins-xrp-sol-doge-surge-following-bitcoin-s-new-all-time-high-2025-9b3f9e83` | Altcoins XRP, SOL, DOGE Surge Following Bitcoin's New All-Time High | PASS — explicit SOL ticker in title |
| decrypt | `anchorage-digital-expands-institutional-access-to-solana-defi-with-jupiter-integration-2025-c4736f31` | Anchorage Digital Expands Institutional Access to Solana DeFi With Jupiter Integration | PASS — explicit Solana in title |
| cointelegraph | `anchorage-digital-adds-solana-staking-via-marinade-finance-2026-a2de78db` | Anchorage Digital Adds Solana Staking via Marinade Finance | PASS — explicit Solana in title |
| cointelegraph | `bitcoin-and-solana-etfs-see-outflows-amid-market-dip-2026-f7fe94fc` | Bitcoin and Solana ETFs See Outflows Amid Market Dip | PASS — explicit Solana in title |
| cointelegraph | `bitcoin-etfs-extend-losses-as-solana-funds-keep-ground-2026-b2acdacf` | Bitcoin ETFs Extend Losses as Solana Funds Keep Ground | PASS — explicit Solana in title |
| cointelegraph | `brera-to-wind-down-soccer-teams-as-it-pivots-to-solana-infrastructure-2026-e59fed04` | Brera to Wind Down Soccer Teams as it Pivots to Solana Infrastructure | PASS — explicit Solana in title |
