from pathlib import Path
import pandas as pd
import pytest
from ml.dataset_builder import DATASET_COLUMNS, export_dataset

def test_csv_export(tmp_path: Path):
    frame = pd.DataFrame([{column: None for column in DATASET_COLUMNS}])
    output = export_dataset(frame, tmp_path / "dataset.csv")
    assert output.exists() and pd.read_csv(output).columns.tolist() == DATASET_COLUMNS

def test_unknown_export_extension(tmp_path: Path):
    with pytest.raises(ValueError): export_dataset(pd.DataFrame(), tmp_path / "dataset.txt")
