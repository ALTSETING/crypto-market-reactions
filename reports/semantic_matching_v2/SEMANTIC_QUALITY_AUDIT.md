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

Candidate ETH cohorts from the shipped TypeScript classifier: `large_investment` **55**, `institutional_purchase` **48**, `institutional_selling` **33**.

### Reaction V2 statistical impact

| Cohort | Horizon | n | Mean | Median | Positive share | 5% trimmed mean | SD | SE |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| eth_large_before_legacy | 1m | 339 | -0.001851 | 0.001570 | 0.507375 | 0.000280 | 0.121316 | 0.006589 |
| eth_large_before_legacy | 5m | 339 | -0.011383 | -0.007902 | 0.471976 | -0.011799 | 0.229136 | 0.012445 |
| eth_large_before_legacy | 15m | 339 | -0.011212 | -0.003017 | 0.492625 | -0.010955 | 0.404788 | 0.021985 |
| eth_large_before_legacy | 1h | 339 | -0.062887 | -0.039133 | 0.483776 | -0.046607 | 0.894014 | 0.048556 |
| eth_large_before_legacy | 4h | 339 | -0.001379 | -0.019889 | 0.492625 | 0.056777 | 1.780904 | 0.096725 |
| eth_large_before_legacy | 24h | 339 | -0.239890 | -0.262196 | 0.477876 | -0.309798 | 3.716271 | 0.201840 |
| eth_large_after_semantic_cleaning | 1m | 55 | -0.037389 | -0.016164 | 0.418182 | -0.027146 | 0.149899 | 0.020212 |
| eth_large_after_semantic_cleaning | 5m | 55 | 0.048024 | 0.024191 | 0.581818 | 0.044484 | 0.246868 | 0.033288 |
| eth_large_after_semantic_cleaning | 15m | 55 | 0.056623 | 0.111826 | 0.618182 | 0.060142 | 0.354490 | 0.047799 |
| eth_large_after_semantic_cleaning | 1h | 55 | -0.102085 | -0.176134 | 0.472727 | -0.073429 | 0.719857 | 0.097066 |
| eth_large_after_semantic_cleaning | 4h | 55 | -0.209237 | -0.143251 | 0.472727 | -0.192698 | 1.611800 | 0.217335 |
| eth_large_after_semantic_cleaning | 24h | 55 | -0.347376 | -0.918543 | 0.418182 | -0.411995 | 4.018999 | 0.541922 |
| institutional_buying | 1m | 48 | -0.025418 | -0.008193 | 0.437500 | -0.011363 | 0.132388 | 0.019109 |
| institutional_buying | 5m | 48 | 0.030050 | 0.017937 | 0.562500 | 0.020812 | 0.299038 | 0.043162 |
| institutional_buying | 15m | 48 | 0.080561 | 0.119626 | 0.604167 | 0.076207 | 0.432497 | 0.062426 |
| institutional_buying | 1h | 48 | 0.025427 | 0.150058 | 0.541667 | 0.057345 | 0.722734 | 0.104318 |
| institutional_buying | 4h | 48 | -0.038424 | -0.108700 | 0.479167 | -0.061289 | 1.544660 | 0.222953 |
| institutional_buying | 24h | 48 | 0.148571 | -0.179318 | 0.479167 | 0.093940 | 3.680953 | 0.531300 |
| institutional_selling_or_outflow | 1m | 33 | 0.014445 | -0.012090 | 0.424242 | 0.013830 | 0.134491 | 0.023412 |
| institutional_selling_or_outflow | 5m | 33 | 0.005197 | -0.021550 | 0.454545 | -0.000426 | 0.333463 | 0.058048 |
| institutional_selling_or_outflow | 15m | 33 | -0.101553 | -0.067544 | 0.363636 | -0.077603 | 0.477411 | 0.083107 |
| institutional_selling_or_outflow | 1h | 33 | -0.062877 | 0.009347 | 0.545455 | -0.009328 | 0.795567 | 0.138490 |
| institutional_selling_or_outflow | 4h | 33 | -0.212636 | -0.434896 | 0.303030 | -0.279868 | 1.238563 | 0.215606 |
| institutional_selling_or_outflow | 24h | 33 | -0.039959 | -0.657846 | 0.424242 | -0.059408 | 4.056341 | 0.706118 |

### Cohort deltas

| Comparison | Horizon | left n | right n | Mean delta | Median delta | Positive-share delta (pp) | Trimmed-mean delta |
|---|---|---:|---:|---:|---:|---:|---:|
| after_minus_before | 1m | 55 | 339 | -0.035537 | -0.017734 | -8.919281 | -0.027426 |
| after_minus_before | 5m | 55 | 339 | 0.059407 | 0.032093 | 10.984178 | 0.056283 |
| after_minus_before | 15m | 55 | 339 | 0.067835 | 0.114843 | 12.555645 | 0.071097 |
| after_minus_before | 1h | 55 | 339 | -0.039198 | -0.137002 | -1.104854 | -0.026822 |
| after_minus_before | 4h | 55 | 339 | -0.207858 | -0.123362 | -1.989810 | -0.249475 |
| after_minus_before | 24h | 55 | 339 | -0.107487 | -0.656347 | -5.969429 | -0.102197 |
| institutional_buying_minus_selling | 1m | 48 | 33 | -0.039863 | 0.003897 | 1.325758 | -0.025193 |
| institutional_buying_minus_selling | 5m | 48 | 33 | 0.024854 | 0.039486 | 10.795455 | 0.021238 |
| institutional_buying_minus_selling | 15m | 48 | 33 | 0.182114 | 0.187170 | 24.053030 | 0.153809 |
| institutional_buying_minus_selling | 1h | 48 | 33 | 0.088304 | 0.140710 | -0.378788 | 0.066673 |
| institutional_buying_minus_selling | 4h | 48 | 33 | 0.174212 | 0.326195 | 17.613636 | 0.218579 |
| institutional_buying_minus_selling | 24h | 48 | 33 | 0.188530 | 0.478528 | 5.492424 | 0.153347 |

## Independent math verification

Cases: **30**; tolerance: `1e-09`; mismatches: **0**.

## Limitations

Golden labels use immutable headline evidence; ambiguous facts requiring article-body context are excluded or labelled conservatively. Production classification is an independent deterministic audit, not a replacement for the golden oracle. EUR normalization is fixed at 1.08 rather than live FX. No production rows were sent to an AI service.
