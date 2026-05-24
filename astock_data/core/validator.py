"""Data integrity validation — schema checks, null ratio, range validation."""

import logging
from typing import Sequence

import pandas as pd

logger = logging.getLogger(__name__)

# Required columns per data type
KLINE_COLUMNS = {"open", "high", "low", "close", "vol"}
QUOTE_COLUMNS = {"price", "open", "high", "low", "vol", "amount"}

# Max allowed null ratio
DEFAULT_MAX_NULL_RATIO = 0.10


class DataValidator:
    """Validates DataFrames for integrity before returning to callers."""

    @staticmethod
    def not_empty(df: pd.DataFrame | None) -> bool:
        return df is not None and not df.empty

    @staticmethod
    def has_columns(df: pd.DataFrame, required: set[str]) -> bool:
        return required.issubset(set(df.columns))

    @staticmethod
    def null_ratio(df: pd.DataFrame, max_ratio: float = DEFAULT_MAX_NULL_RATIO) -> bool:
        if df.empty:
            return False
        ratio = df.isnull().sum().sum() / (len(df) * len(df.columns))
        return ratio <= max_ratio

    @staticmethod
    def range_check(df: pd.DataFrame, column: str, min_val: float = 0, max_val: float = float("inf")) -> bool:
        if column not in df.columns:
            return False
        col = df[column].dropna()
        if col.empty:
            return False
        return bool((col >= min_val).all() and (col <= max_val).all())

    @classmethod
    def validate_kline(cls, df: pd.DataFrame | None, *, require_positive: bool = True) -> tuple[bool, str]:
        """Validate K-line DataFrame. Returns (ok, reason)."""
        if not cls.not_empty(df):
            return False, "DataFrame is None or empty"
        if not cls.has_columns(df, KLINE_COLUMNS):
            missing = KLINE_COLUMNS - set(df.columns)
            return False, f"Missing columns: {missing}"
        if not cls.null_ratio(df):
            return False, f"Null ratio exceeds {DEFAULT_MAX_NULL_RATIO:.0%}"
        if require_positive:
            for col in KLINE_COLUMNS:
                if not cls.range_check(df, col, min_val=0):
                    return False, f"Column '{col}' has negative values"
        return True, "ok"

    @classmethod
    def validate_quote(cls, df: pd.DataFrame | None) -> tuple[bool, str]:
        """Validate real-time quote DataFrame."""
        if not cls.not_empty(df):
            return False, "DataFrame is None or empty"
        if not cls.has_columns(df, QUOTE_COLUMNS):
            missing = QUOTE_COLUMNS - set(df.columns)
            return False, f"Missing columns: {missing}"
        if not cls.null_ratio(df):
            return False, f"Null ratio exceeds {DEFAULT_MAX_NULL_RATIO:.0%}"
        return True, "ok"

    @classmethod
    def validate_dataframe(
        cls,
        df: pd.DataFrame | None,
        required_columns: Sequence[str] | None = None,
        *,
        max_null_ratio: float = DEFAULT_MAX_NULL_RATIO,
        positive_columns: Sequence[str] | None = None,
    ) -> tuple[bool, str]:
        """Generic DataFrame validation.

        Args:
            df: DataFrame to validate.
            required_columns: Columns that must be present.
            max_null_ratio: Maximum allowed null ratio.
            positive_columns: Columns that must be strictly positive.

        Returns:
            (ok, reason) tuple.
        """
        if not cls.not_empty(df):
            return False, "DataFrame is None or empty"
        if required_columns:
            if not cls.has_columns(df, set(required_columns)):
                missing = set(required_columns) - set(df.columns)
                return False, f"Missing columns: {missing}"
        if not cls.null_ratio(df, max_ratio=max_null_ratio):
            return False, f"Null ratio exceeds {max_null_ratio:.0%}"
        if positive_columns:
            for col in positive_columns:
                if col in df.columns and not cls.range_check(df, col, min_val=0):
                    return False, f"Column '{col}' has negative values"
        return True, "ok"


# Convenience functions
def validate_kline(df: pd.DataFrame | None) -> tuple[bool, str]:
    return DataValidator.validate_kline(df)


def validate_quote(df: pd.DataFrame | None) -> tuple[bool, str]:
    return DataValidator.validate_quote(df)


def validate_dataframe(
    df: pd.DataFrame | None,
    required_columns: Sequence[str] | None = None,
    *,
    max_null_ratio: float = DEFAULT_MAX_NULL_RATIO,
    positive_columns: Sequence[str] | None = None,
) -> tuple[bool, str]:
    return DataValidator.validate_dataframe(
        df, required_columns, max_null_ratio=max_null_ratio, positive_columns=positive_columns
    )
