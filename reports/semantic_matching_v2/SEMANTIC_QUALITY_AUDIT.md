# Semantic Matching V2 — independent quality audit

## Golden dataset

The manually reviewed oracle contains **150** unique events with distribution `{"etf": 20, "hack": 20, "institutional_purchase": 20, "institutional_selling": 20, "large_investment": 30, "negative_control": 20, "sec": 20}`.

## Legacy matcher

| Precision | Recall | F1 | FP | FN | Gate |
|---:|---:|---:|---:|---:|:---:|
| 0.866667 | 0.600000 | 0.709091 | 12 | 52 | FAIL |

| Topic | Precision | Recall | F1 | FP | FN |
|---|---:|---:|---:|---:|---:|
| etf | 1.000000 | 1.000000 | 1.000000 | 0 | 0 |
| hack | 0.833333 | 1.000000 | 0.909091 | 4 | 0 |
| institutional_purchase | 0.000000 | 0.000000 | 0.000000 | 0 | 20 |
| institutional_selling | 0.000000 | 0.000000 | 0.000000 | 0 | 20 |
| large_investment | 0.692308 | 0.600000 | 0.642857 | 8 | 12 |
| sec | 1.000000 | 1.000000 | 1.000000 | 0 | 0 |

## Candidate matcher

| Precision | Recall | F1 | FP | FN | Gate |
|---:|---:|---:|---:|---:|:---:|
| 1.000000 | 1.000000 | 1.000000 | 0 | 0 | PASS |

| Topic | Precision | Recall | F1 | FP | FN |
|---|---:|---:|---:|---:|---:|
| etf | 1.000000 | 1.000000 | 1.000000 | 0 | 0 |
| hack | 1.000000 | 1.000000 | 1.000000 | 0 | 0 |
| institutional_purchase | 1.000000 | 1.000000 | 1.000000 | 0 | 0 |
| institutional_selling | 1.000000 | 1.000000 | 1.000000 | 0 | 0 |
| large_investment | 1.000000 | 1.000000 | 1.000000 | 0 | 0 |
| sec | 1.000000 | 1.000000 | 1.000000 | 0 | 0 |

## Production read-only audit

Scanned 9073 rows (bounded at 10000); writes: **NO**; Reaction V2 recalculation: **NO**.

Legacy ETH large-investment sample: **339**; exact 339 confirmed: **True**.

| Classification | Count | Percent |
|---|---:|---:|
| acquisition_only | 56 | 16.52% |
| eth_secondary_mention | 142 | 41.89% |
| funding_only | 54 | 15.93% |
| generic_investment | 19 | 5.60% |
| true_large_eth_investment | 23 | 6.78% |
| unrelated_false_positive | 45 | 13.27% |

Candidate ETH cohorts from the shipped TypeScript classifier: `large_investment` **117**, `institutional_purchase` **134**, `institutional_selling` **130**.

### Reaction V2 statistical impact

| Cohort | Horizon | n | Mean | Median | Positive share | 5% trimmed mean | SD | SE |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| eth_large_before_legacy | 1m | 339 | -0.001851 | 0.001570 | 0.507375 | 0.000280 | 0.121316 | 0.006589 |
| eth_large_before_legacy | 5m | 339 | -0.011383 | -0.007902 | 0.471976 | -0.011799 | 0.229136 | 0.012445 |
| eth_large_before_legacy | 15m | 339 | -0.011212 | -0.003017 | 0.492625 | -0.010955 | 0.404788 | 0.021985 |
| eth_large_before_legacy | 1h | 339 | -0.062887 | -0.039133 | 0.483776 | -0.046607 | 0.894014 | 0.048556 |
| eth_large_before_legacy | 4h | 339 | -0.001379 | -0.019889 | 0.492625 | 0.056777 | 1.780904 | 0.096725 |
| eth_large_before_legacy | 24h | 339 | -0.239890 | -0.262196 | 0.477876 | -0.309798 | 3.716271 | 0.201840 |
| eth_large_after_semantic_cleaning | 1m | 117 | -0.020493 | -0.012492 | 0.427350 | -0.014301 | 0.110993 | 0.010261 |
| eth_large_after_semantic_cleaning | 5m | 117 | 0.011609 | 0.009476 | 0.529915 | 0.011227 | 0.217654 | 0.020122 |
| eth_large_after_semantic_cleaning | 15m | 117 | 0.012698 | 0.046861 | 0.521368 | 0.016687 | 0.306578 | 0.028343 |
| eth_large_after_semantic_cleaning | 1h | 117 | 0.006964 | 0.048116 | 0.512821 | -0.000019 | 0.799747 | 0.073937 |
| eth_large_after_semantic_cleaning | 4h | 117 | 0.138623 | 0.046997 | 0.521368 | 0.104492 | 1.639731 | 0.151593 |
| eth_large_after_semantic_cleaning | 24h | 117 | 0.025187 | -0.425415 | 0.487179 | -0.167749 | 3.978700 | 0.367831 |
| institutional_buying | 1m | 134 | -0.009757 | 0.001074 | 0.500000 | -0.003515 | 0.113514 | 0.009806 |
| institutional_buying | 5m | 134 | 0.016801 | 0.010890 | 0.559701 | 0.008468 | 0.240215 | 0.020751 |
| institutional_buying | 15m | 134 | 0.055107 | 0.053159 | 0.544776 | 0.045985 | 0.420607 | 0.036335 |
| institutional_buying | 1h | 134 | 0.056801 | 0.064678 | 0.529851 | 0.058528 | 0.793278 | 0.068529 |
| institutional_buying | 4h | 134 | -0.066616 | -0.176496 | 0.462687 | -0.038275 | 1.645840 | 0.142179 |
| institutional_buying | 24h | 134 | -0.157822 | -0.234446 | 0.455224 | -0.137276 | 3.692113 | 0.318950 |
| institutional_selling_or_outflow | 1m | 130 | -0.020780 | -0.009773 | 0.446154 | -0.013408 | 0.109016 | 0.009561 |
| institutional_selling_or_outflow | 5m | 130 | -0.034601 | 0.004901 | 0.515385 | -0.012506 | 0.302548 | 0.026535 |
| institutional_selling_or_outflow | 15m | 130 | -0.049469 | -0.007472 | 0.500000 | -0.028851 | 0.553126 | 0.048512 |
| institutional_selling_or_outflow | 1h | 130 | 0.049650 | 0.012533 | 0.530769 | 0.024469 | 0.784382 | 0.068795 |
| institutional_selling_or_outflow | 4h | 130 | -0.175323 | -0.193708 | 0.400000 | -0.175272 | 1.444505 | 0.126691 |
| institutional_selling_or_outflow | 24h | 130 | -0.572694 | -0.293541 | 0.453846 | -0.581321 | 4.689979 | 0.411338 |

### Cohort deltas

| Comparison | Horizon | left n | right n | Mean delta | Median delta | Positive-share delta (pp) | Trimmed-mean delta |
|---|---|---:|---:|---:|---:|---:|---:|
| after_minus_before | 1m | 117 | 339 | -0.018642 | -0.014062 | -8.002420 | -0.014581 |
| after_minus_before | 5m | 117 | 339 | 0.022993 | 0.017378 | 5.793813 | 0.023027 |
| after_minus_before | 15m | 117 | 339 | 0.023910 | 0.049878 | 2.874215 | 0.027642 |
| after_minus_before | 1h | 117 | 339 | 0.069851 | 0.087248 | 2.904470 | 0.046588 |
| after_minus_before | 4h | 117 | 339 | 0.140002 | 0.066886 | 2.874215 | 0.047715 |
| after_minus_before | 24h | 117 | 339 | 0.265077 | -0.163219 | 0.930338 | 0.142049 |
| institutional_buying_minus_selling | 1m | 134 | 130 | 0.011023 | 0.010848 | 5.384615 | 0.009893 |
| institutional_buying_minus_selling | 5m | 134 | 130 | 0.051402 | 0.005989 | 4.431688 | 0.020975 |
| institutional_buying_minus_selling | 15m | 134 | 130 | 0.104577 | 0.060631 | 4.477612 | 0.074836 |
| institutional_buying_minus_selling | 1h | 134 | 130 | 0.007151 | 0.052145 | -0.091848 | 0.034059 |
| institutional_buying_minus_selling | 4h | 134 | 130 | 0.108707 | 0.017212 | 6.268657 | 0.136998 |
| institutional_buying_minus_selling | 24h | 134 | 130 | 0.414871 | 0.059095 | 0.137773 | 0.444046 |

## Independent math verification

Cases: **30**; tolerance: `1e-09`; mismatches: **0**.

## Limitations

Golden labels use immutable headline evidence; ambiguous facts requiring article-body context are excluded or labelled conservatively. Production classification is an independent deterministic audit, not a replacement for the golden oracle. EUR normalization is fixed at 1.08 rather than live FX. No production rows were sent to an AI service.
