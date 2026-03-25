import pandas as pd


def safe_int(val) -> int | None:
    return None if pd.isna(val) else int(val)


def safe_str(val) -> str:
    return "" if pd.isna(val) else str(val)
