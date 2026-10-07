"""
FUNDShare ML Pipeline - Leakage-Safe Forecasting Pipeline
Provides:
- Panel dataset construction from historical transactions
- Pure temporal train / val / test splitting across consecutive time periods
- Strict causal feature engineering (lag, rolling stats, historical baselines)
- Baselines: Last Value and Moving Average (tuned on validation split)
- Machine Learning Forecaster (HistGradientBoosting / RandomForest)
- Out-of-sample evaluation: MAE, RMSE, WAPE, MAPE
- Controlled Forecasting Ablation Study
"""
import numpy as np
import pandas as pd
from typing import Dict, Any, Tuple, List
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.metrics import mean_absolute_error, root_mean_squared_error


def build_spending_panel(transactions_df: pd.DataFrame, freq: str = 'W') -> pd.DataFrame:
    """
    Constructs a regular time panel of spending aggregated by (sender_id, category, period).
    """
    df = transactions_df.copy()
    df['amount'] = df['amount'].astype(float)
    df['timestamp'] = pd.to_datetime(df['timestamp'])

    # Assign period period_idx
    if freq == 'W':
        df['period'] = df['timestamp'].dt.to_period('W-SUN').dt.start_time
    else:
        df['period'] = df['timestamp'].dt.to_period('M').dt.start_time

    # Aggregate
    agg = df.groupby(['sender_id', 'category', 'period']).agg(
        amount=('amount', 'sum'),
        txn_count=('amount', 'count')
    ).reset_index()

    # Reindex to full grid across all observed periods per (sender, category)
    all_periods = sorted(agg['period'].unique())
    user_cats = agg[['sender_id', 'category']].drop_duplicates()

    grid_list = []
    for _, uc in user_cats.iterrows():
        for p in all_periods:
            grid_list.append({
                'sender_id': uc['sender_id'],
                'category': uc['category'],
                'period': p
            })
    grid_df = pd.DataFrame(grid_list)

    merged = pd.merge(grid_df, agg, on=['sender_id', 'category', 'period'], how='left')
    merged['amount'] = merged['amount'].fillna(0.0)
    merged['txn_count'] = merged['txn_count'].fillna(0.0)
    merged = merged.sort_values(['sender_id', 'category', 'period']).reset_index(drop=True)
    return merged


class ForecastingFeaturePipeline:
    """
    Builds causal time-series features strictly utilizing historical observations
    strictly prior to period t (lag_1, lag_2, lag_3, rolling stats, historical baselines).
    """
    def __init__(self):
        self.user_hist_means: Dict[int, float] = {}
        self.cat_hist_means: Dict[str, float] = {}

    def extract_features_and_targets(
        self,
        panel_df: pd.DataFrame,
        feature_group: str = 'full'
    ) -> Tuple[pd.DataFrame, np.ndarray]:
        """
        Generates lag, rolling, and contextual features.
        Any row with insufficient initial history (first 3 periods) is pruned.
        """
        records = []
        targets = []

        grouped = panel_df.groupby(['sender_id', 'category'])
        for (u_id, cat), group in grouped:
            g = group.sort_values('period').reset_index(drop=True)
            amts = g['amount'].values
            counts = g['txn_count'].values
            periods = g['period'].values

            for i in range(3, len(g)):
                target = amts[i]
                t_period = periods[i]

                lag_1 = amts[i - 1]
                lag_2 = amts[i - 2]
                lag_3 = amts[i - 3]

                if feature_group == 'lag_only':
                    records.append({
                        'sender_id': u_id,
                        'category': cat,
                        'period': t_period,
                        'lag_1': lag_1,
                        'lag_2': lag_2,
                        'lag_3': lag_3
                    })
                    targets.append(target)
                    continue

                rolling_mean = float(np.mean([lag_1, lag_2, lag_3]))
                rolling_std = float(np.std([lag_1, lag_2, lag_3]))

                if feature_group == 'lag_rolling':
                    records.append({
                        'sender_id': u_id,
                        'category': cat,
                        'period': t_period,
                        'lag_1': lag_1,
                        'lag_2': lag_2,
                        'lag_3': lag_3,
                        'rolling_mean_3': rolling_mean,
                        'rolling_std_3': rolling_std
                    })
                    targets.append(target)
                    continue

                # Full feature set: include contextual and historical baselines
                u_hist = float(np.mean(amts[:i]))
                c_amts_all = amts[:i]
                cnt_lag_1 = counts[i - 1]
                dt_period = pd.to_datetime(t_period)
                month = dt_period.month
                week_of_year = dt_period.isocalendar().week

                records.append({
                    'sender_id': u_id,
                    'category': cat,
                    'period': t_period,
                    'lag_1': lag_1,
                    'lag_2': lag_2,
                    'lag_3': lag_3,
                    'rolling_mean_3': rolling_mean,
                    'rolling_std_3': rolling_std,
                    'txn_count_lag_1': cnt_lag_1,
                    'month': month,
                    'week_of_year': week_of_year,
                    'user_hist_mean': u_hist,
                    'category_code': hash(cat) % 15
                })
                targets.append(target)

        feature_df = pd.DataFrame(records)
        return feature_df, np.array(targets, dtype=np.float64)


class LastValueForecastingBaseline:
    """Baseline A: Predicts next period spending using the most recent observation."""
    def predict(self, feature_df: pd.DataFrame) -> np.ndarray:
        return feature_df['lag_1'].values


class MovingAverageForecastingBaseline:
    """Baseline B: Predicts next period using moving average of previous N periods."""
    def __init__(self, n_periods: int = 3):
        self.n_periods = n_periods

    def fit(self, feature_df_val: pd.DataFrame, y_val: np.ndarray):
        best_n = 3
        best_mae = float('inf')
        for n in [2, 3]:
            if n == 2:
                preds = (feature_df_val['lag_1'].values + feature_df_val['lag_2'].values) / 2.0
            else:
                preds = (feature_df_val['lag_1'].values + feature_df_val['lag_2'].values + feature_df_val['lag_3'].values) / 3.0
            mae = mean_absolute_error(y_val, preds)
            if mae < best_mae:
                best_mae = mae
                best_n = n
        self.n_periods = best_n
        return self

    def predict(self, feature_df: pd.DataFrame) -> np.ndarray:
        if self.n_periods == 2:
            return (feature_df['lag_1'].values + feature_df['lag_2'].values) / 2.0
        return (feature_df['lag_1'].values + feature_df['lag_2'].values + feature_df['lag_3'].values) / 3.0


class MLForecastingModel:
    """Machine Learning Forecaster using Gradient Boosting with causal features."""
    def __init__(self, random_state: int = 42):
        self.model = HistGradientBoostingRegressor(
            random_state=random_state,
            max_iter=100,
            min_samples_leaf=5,
            learning_rate=0.08
        )
        self.feature_cols = []

    def fit(self, feature_df_train: pd.DataFrame, y_train: np.ndarray):
        cols_to_drop = ['sender_id', 'category', 'period']
        self.feature_cols = [c for c in feature_df_train.columns if c not in cols_to_drop]
        X = feature_df_train[self.feature_cols].values
        self.model.fit(X, y_train)
        return self

    def predict(self, feature_df: pd.DataFrame) -> np.ndarray:
        X = feature_df[self.feature_cols].values
        preds = self.model.predict(X)
        return np.clip(preds, 0.0, None)  # Financial spending cannot be negative


def calculate_forecast_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> Dict[str, float]:
    """
    Computes MAE, RMSE, and WAPE / MAPE handling zero actuals safely.
    WAPE = sum(|actual - pred|) / sum(actual) * 100%
    """
    mae = float(mean_absolute_error(y_true, y_pred))
    rmse = float(root_mean_squared_error(y_true, y_pred))

    sum_true = float(np.sum(y_true))
    wape = float((np.sum(np.abs(y_true - y_pred)) / sum_true) * 100.0) if sum_true > 0 else 0.0

    # Non-zero MAPE for cases where actual spending > 0
    non_zero_mask = y_true > 0
    if np.sum(non_zero_mask) > 0:
        nz_true = y_true[non_zero_mask]
        nz_pred = y_pred[non_zero_mask]
        mape = float(np.mean(np.abs((nz_true - nz_pred) / nz_true)) * 100.0)
    else:
        mape = 0.0

    return {
        "mae": round(mae, 2),
        "rmse": round(rmse, 2),
        "wape": round(wape, 2),
        "mape": round(mape, 2),
        "sample_count": len(y_true)
    }
