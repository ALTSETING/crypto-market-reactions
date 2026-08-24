# Reaction V1/V2 sign-flip audit

- Total flips: **1,088**.
- Forensic sample: **100** including the 20 largest differences.
- Raw V2 recalculation failures: **0**.
- V1 families represented: `{"B": 822, "C": 266}`. All flips are in B/C, whose V1 reference used the extra latency minute; V2 uses the first full minute strictly after publication.
- Magnitudes: `{"0.10\u20130.25 pp": 387, "0.05\u20130.10 pp": 275, "<0.05 pp": 220, "0.25\u20130.50 pp": 147, "0.50\u20131.00 pp": 49, "1.00\u20132.00 pp": 8, ">2.00 pp": 2}`.

The full row-level Parquet, grouped distribution CSV, and 100-row forensic sample retain both reference timestamps and values.
