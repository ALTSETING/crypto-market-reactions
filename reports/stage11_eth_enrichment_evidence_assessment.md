# Stage 11 evidence-aware enrichment assessment

- Model: `gpt-5-mini-2025-08-07`; v1 versus `eth_market_context_v2` on the same 30 events.
- Schema success: 100%; conservative cost: $0.01515950
- Null rates: {'expected_by_market': 1.0, 'already_priced_in': 1.0, 'primary_source_probability': 0.9333}.
- Contradictions: {'insufficient_with_numeric_score': 0, 'sufficient_with_null_score': 0, 'high_priced_in_and_high_freshness': 0, 'generic_but_highly_actionable': 0}.
- Human-review readiness: `READY_FOR_REVIEW_NOT_YET_REVIEWED`.
- Full batch: **NO-GO pending completed human review and separate confirmation**.
