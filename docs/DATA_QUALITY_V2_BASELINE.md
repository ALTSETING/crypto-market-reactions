# Data Quality V2 baseline

Generated: `2026-08-23T05:49:16.297952+00:00` from `data\website\events_mvp.parquet`.

## Identity

- Events / unique IDs: **7,878 / 7,878**.
- SHA-256: `78cc72f91bbd3cfba595ff843486d2e8b82e4ea10a31f68666ce613c6d8ec833`.
- Range: **2017-01-03T10:48:14+00:00** to **2026-07-01T00:00:00+00:00**.
- Duplicate URL rows: **0**; duplicate normalized-title rows: **15**.
- Malformed URLs: **0**; generic titles: **11**.

## Coverage by year

- 2017: **83**
- 2018: **45**
- 2019: **124**
- 2020: **57**
- 2021: **78**
- 2022: **90**
- 2023: **101**
- 2024: **143**
- 2025: **4,080**
- 2026: **3,077**

## Semantic and market fields

- Missing category / sentiment / importance: **0 / 313 / 313**.
- Missing reaction cells: **53,013**; infinite: **0**; <= -100%: **0**.
- Existing reaction methodologies: `{"next_full_minute_latency_0_open_to_open": 6851, "next_full_minute_latency_1_open_to_open": 1027}`.

## Conservative story grouping

- Articles / unique stories: **7,878 / 7,862**.
- Multi-article stories: **6**; largest cluster: **11**.

No canonical dataset or production database was modified. Derived fields are in the staging Parquet and remain subject to review.
