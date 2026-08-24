# Reaction V1 vs V2 comparison

Comparable non-NULL cells: **88,791**. V2 is staged separately and does not overwrite V1.

V2 uses the first full one-minute candle open strictly after `published_at`; every horizon is open-to-open. Detailed asset/year/family/source statistics are in `reports/REACTION_V1_V2_COMPARISON.csv`.

Sign flips: **1,088**. Cells differing by >0.1pp / >0.5pp / >1pp / >2pp: **2,352 / 168 / 25 / 5**.
