import pandas as pd
import pytest

from scripts.quality.complete_manual_asset_review import (
    EXPECTED_ROWS,
    FALSE_SOL_IDS,
    REVIEW_PATH,
    validate_review,
)


@pytest.mark.skipif(
    not REVIEW_PATH.is_file(),
    reason="private manual-review package is intentionally not stored in Git",
)
def test_manual_asset_review_is_complete_and_evidence_bounded():
    frame = pd.read_csv(REVIEW_PATH)
    result = validate_review(frame)
    assert result["status"] == "PASS"
    assert result["completed"] == EXPECTED_ROWS
    assert result["remaining"] == 0
    assert result["assign_btc"] == 0
    assert result["keep_empty"] == EXPECTED_ROWS
    assert result["metadata_only_btc_matches_rejected"] == EXPECTED_ROWS - len(FALSE_SOL_IDS)
