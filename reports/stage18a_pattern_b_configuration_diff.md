# Stage 18A — Pattern B configuration reconciliation

The old Stage 17B estimator and row-level predictions were not persisted, so they were not reconstructed or invented.

## Identical

- Asset scope: ETH.
- Model family: Gradient Boosting.
- Parameters: n_estimators=80, learning_rate=0.05, max_depth=2.
- Primary horizon: 12h; neutral threshold: 0.10%; confidence threshold: 0.40.
- Feature family: semantic plus pre-event market context.

## Changed in Pattern B V2

- Dataset: unified Stage 18 canonical A/B/C rows instead of the Stage 16 high-impact-only matrix.
- Feature registry: 42 old columns versus 92 canonical columns; exact lists are not identical.
- Semantic fields were renamed and missing flags added.
- Split: new event-level chronological 70/15/15 split; old Stage 16 split/manifests were used by Stage 17B.
- Random seed: Stage 18 uses 18017; old lock does not persist an equivalent fitted-model seed artifact.
- Preprocessor and fitted estimator are new V2 artifacts, not the unavailable old estimator.

## Cannot be verified

- The old 46 validation and 111 walk-forward row-level predictions.
- Old per-row probabilities, fitted trees, encoder state, and model hash.

Old lock hash: `509a91b2d6fda0991eba012cf273ad54ef9b2f711a49a6891a7ba0a7277f900e`. New config hash: `561ce0b2c4ec83d287a7336e4aa8d8cd42e5e11b90f64d1335cb26137b35e9d6`.
