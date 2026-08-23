# Stage 11 ETH enrichment A/B assessment

- Technical winner: `gpt-5-mini-2025-08-07`
- Actual total cost: `$0.01315300`
- Significant divergences: 28 / 30
- API requests this run: 0
- Resume verified without new requests: True
- Predictive inference: intentionally not evaluated on n=30.

## Decision

**NO-GO pending completed human review.** Schema, variability, contradictions, leakage, cost, and resume are technical gates; the required human fields are deliberately blank, so semantic quality and whether priced-in/expectation scores are grounded cannot yet pass.

## Systematic-risk checks

- `gpt-5-mini-2025-08-07`: directions={'negative': 7, 'positive': 3, 'neutral': 20}; low-variability fields=none; contradictions={'high_priced_in_and_high_freshness': 0, 'low_confidence_but_extreme_surprise': 0, 'generic_but_highly_actionable': 0}.
- `gpt-5-nano-2025-08-07`: directions={'neutral': 29, 'positive': 1}; low-variability fields=none; contradictions={'high_priced_in_and_high_freshness': 0, 'low_confidence_but_extreme_surprise': 0, 'generic_but_highly_actionable': 0}.
- Detected: `strong_neutral_default_bias` — {'model': 'gpt-5-nano-2025-08-07', 'issue': 'strong_neutral_default_bias', 'neutral_count': 29, 'sample_size': 30}.
- Detected: `low_cross_model_stability` — {'models': ['gpt-5-mini-2025-08-07', 'gpt-5-nano-2025-08-07'], 'issue': 'low_cross_model_stability', 'significant_divergences': 28, 'paired': 30}.
