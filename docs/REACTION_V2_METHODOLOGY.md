# Reaction V2 production methodology

## Production definition

`Reaction V2` is the preserved production methodology
`reaction_v2_next_full_minute_open_to_open`. The reference price is the open of
the first full one-minute candle strictly after the recorded publication
timestamp. Each 1m, 5m, 15m, 1h, 4h, and 24h endpoint is the open of the candle
at the corresponding offset from that reference.

Reaction values are percentage returns. NULL means that a required market-data
observation was unavailable and is never replaced with zero. Reaction V2 is a
historical association around a recorded publication time; it is not proof
that the event caused a price movement.

Migration 009 does not add, infer, or change a Reaction V2 value or version.
It adds only independent source-classification metadata. The existing
`reaction_methodology = 'reaction_v2_next_full_minute_open_to_open'` value is
the production methodology gate, and every BTC, ETH, and SOL reaction field
remains protected.

The frontend displays a neutral `Reaction V2` label and explicitly describes
the values as historical association rather than proof of causality. Alternative
research alignments are not exposed as production data.

## Independent source classification

Migration 009 stores source classification in `source_class_v2`,
`document_class_v2`, `source_class_confidence_v2`, and
`source_classification_version`. Legacy `record_type` and `source_type` remain
unchanged and are not classifier inputs. The public API keeps the compatible
`source_type` response name by aliasing `source_class_v2` at the server query
boundary.
