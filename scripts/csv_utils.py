from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd


def csv_has_header(path: Path, expected_columns: list[str]) -> bool:
    if not path.exists() or path.stat().st_size == 0:
        return False

    with path.open("r", encoding="utf-8", newline="") as handle:
        first_row = next(csv.reader(handle, skipinitialspace=True), [])

    normalized = [value.strip() for value in first_row]
    return normalized == expected_columns


def read_csv_with_optional_header(path: Path, expected_columns: list[str]) -> pd.DataFrame:
    if csv_has_header(path, expected_columns):
        return pd.read_csv(path)
    return pd.read_csv(path, names=expected_columns)
