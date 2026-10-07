"""
FUNDShare ML Pipeline - Leakage-Safe Data Splits
Provides strictly temporal, non-random splits for time-series financial transactions.
"""
from dataclasses import dataclass
from typing import List, Tuple
from django.utils import timezone
import pandas as pd


@dataclass
class TemporalSplitResult:
    train_df: pd.DataFrame
    val_df: pd.DataFrame
    test_df: pd.DataFrame
    train_end: str
    val_start: str
    val_end: str
    test_start: str
    test_end: str
    total_count: int
    train_count: int
    val_count: int
    test_count: int
    train_anomalies: int
    val_anomalies: int
    test_anomalies: int


def get_temporal_transaction_splits(
    transactions_df: pd.DataFrame,
    train_pct: float = 0.60,
    val_pct: float = 0.20
) -> TemporalSplitResult:
    """
    Splits transactions chronologically into Train (first ~60%), Validation (next ~20%),
    and Test (final ~20%) without shuffling.
    Guarantees:
      - Max timestamp of Train < Min timestamp of Validation
      - Max timestamp of Validation < Min timestamp of Test
    """
    if 'timestamp' not in transactions_df.columns:
        raise ValueError("DataFrame must contain 'timestamp' column.")

    # Sort strictly by timestamp
    df_sorted = transactions_df.sort_values('timestamp').reset_index(drop=True)
    n = len(df_sorted)
    if n < 10:
        raise ValueError(f"Insufficient transactions for temporal splitting: {n}")

    idx_val = int(n * train_pct)
    idx_test = int(n * (train_pct + val_pct))

    train_df = df_sorted.iloc[:idx_val].copy().reset_index(drop=True)
    val_df = df_sorted.iloc[idx_val:idx_test].copy().reset_index(drop=True)
    test_df = df_sorted.iloc[idx_test:].copy().reset_index(drop=True)

    train_end = str(train_df['timestamp'].iloc[-1])
    val_start = str(val_df['timestamp'].iloc[0])
    val_end = str(val_df['timestamp'].iloc[-1])
    test_start = str(test_df['timestamp'].iloc[0])
    test_end = str(test_df['timestamp'].iloc[-1])

    def count_anoms(sub_df):
        if 'is_anomaly' in sub_df.columns:
            return int(sub_df['is_anomaly'].sum())
        return 0

    return TemporalSplitResult(
        train_df=train_df,
        val_df=val_df,
        test_df=test_df,
        train_end=train_end,
        val_start=val_start,
        val_end=val_end,
        test_start=test_start,
        test_end=test_end,
        total_count=n,
        train_count=len(train_df),
        val_count=len(val_df),
        test_count=len(test_df),
        train_anomalies=count_anoms(train_df),
        val_anomalies=count_anoms(val_df),
        test_anomalies=count_anoms(test_df)
    )
