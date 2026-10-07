"""
FUNDShare ML Pipeline - Leakage-Safe Anomaly Detection Pipeline
Includes:
- AnomalyFeaturePipeline (fits statistics ONLY on training split)
- Baseline Models (AmountPercentileBaseline, StatisticalDeviationBaseline)
- IsolationForest Model (pure ML output calibrated on validation split)
- Strict out-of-sample evaluation on held-out test split
- Controlled Feature Ablation Study
"""
import math
import numpy as np
import pandas as pd
from typing import Dict, Any, Tuple, List
from sklearn.ensemble import IsolationForest
from sklearn.metrics import (
    precision_score, recall_score, f1_score, roc_auc_score,
    average_precision_score, confusion_matrix
)


class AnomalyFeaturePipeline:
    """
    Leakage-safe feature extraction pipeline.
    All historical aggregates (user mean/std, category mean/std, merchant frequencies)
    are fitted strictly on the TRAINING set.
    """
    def __init__(self):
        self.is_fitted = False
        self.user_stats: Dict[int, Dict[str, float]] = {}
        self.category_stats: Dict[str, Dict[str, float]] = {}
        self.merchant_freq: Dict[int, float] = {}
        self.global_mean: float = 1000.0
        self.global_std: float = 500.0

    def fit(self, train_df: pd.DataFrame):
        """Fit baseline statistics ONLY on training transactions."""
        amounts = train_df['amount'].astype(float).values
        self.global_mean = float(np.mean(amounts)) if len(amounts) > 0 else 1000.0
        self.global_std = float(np.std(amounts)) if len(amounts) > 0 else 500.0
        if self.global_std < 1.0:
            self.global_std = 1.0

        # User baselines on training data only
        for user_id, group in train_df.groupby('sender_id'):
            u_amts = group['amount'].astype(float).values
            u_mean = float(np.mean(u_amts))
            u_std = float(np.std(u_amts)) if len(u_amts) > 1 else self.global_std * 0.5
            u_med = float(np.median(u_amts))
            self.user_stats[int(user_id)] = {
                'mean': u_mean,
                'std': max(50.0, u_std),
                'median': u_med,
                'count': len(u_amts)
            }

        # Category baselines on training spending transactions only
        spend_df = train_df[~train_df['transaction_type'].isin(['FUND_ALLOCATION', 'CASH_IN'])] if 'transaction_type' in train_df.columns else train_df
        for cat, group in spend_df.groupby('category'):
            c_amts = group['amount'].astype(float).values
            c_mean = float(np.mean(c_amts))
            c_std = float(np.std(c_amts)) if len(c_amts) > 1 else self.global_std * 0.5
            self.category_stats[str(cat)] = {
                'mean': c_mean,
                'std': max(50.0, c_std),
                'count': len(c_amts)
            }

        # Merchant frequencies on training data only
        m_counts = train_df['merchant_id'].dropna().value_counts()
        total_m = len(train_df)
        self.merchant_freq = {int(k): float(v / total_m) for k, v in m_counts.items()}

        self.is_fitted = True
        return self

    def transform(self, df: pd.DataFrame, feature_group: str = 'full') -> np.ndarray:
        """
        Transforms transactions into feature matrices using pre-fitted training statistics.
        Zero future information is utilized.
        """
        if not self.is_fitted:
            raise RuntimeError("Pipeline must be fitted on training data before transform.")

        features_list = []
        for _, row in df.iterrows():
            amt = float(row['amount'])
            ts = pd.to_datetime(row['timestamp'])
            hour = ts.hour
            weekday = ts.weekday()
            is_weekend = 1.0 if weekday in [4, 5] else 0.0  # Bangladesh weekend: Friday, Saturday

            if feature_group == 'amount_only':
                features_list.append([amt])
                continue

            if feature_group == 'amount_temporal':
                features_list.append([amt, hour, weekday, is_weekend])
                continue

            # Behavioral & Contextual features
            u_id = int(row['sender_id']) if pd.notnull(row.get('sender_id')) else -1
            u_stat = self.user_stats.get(u_id, {'mean': self.global_mean, 'std': self.global_std, 'median': self.global_mean})
            u_ratio = amt / u_stat['mean'] if u_stat['mean'] > 0 else 1.0
            u_zscore = abs(amt - u_stat['mean']) / u_stat['std']

            cat = str(row['category']) if pd.notnull(row.get('category')) else 'Other'
            c_stat = self.category_stats.get(cat, {'mean': self.global_mean, 'std': self.global_std})
            c_ratio = amt / c_stat['mean'] if c_stat['mean'] > 0 else 1.0
            c_zscore = abs(amt - c_stat['mean']) / c_stat['std']

            if feature_group == 'amount_temporal_behavioral':
                features_list.append([
                    amt, hour, weekday, is_weekend,
                    u_ratio, u_zscore, c_ratio, c_zscore
                ])
                continue

            # Full feature set
            m_id = int(row['merchant_id']) if pd.notnull(row.get('merchant_id')) and str(row.get('merchant_id')).strip() != '' else -1
            m_freq = self.merchant_freq.get(m_id, 0.0)
            c_freq = float(c_stat.get('count', 0)) / max(1.0, float(sum(s.get('count', 0) for s in self.category_stats.values())))

            hour_sin = math.sin(2 * math.pi * hour / 24.0)
            hour_cos = math.cos(2 * math.pi * hour / 24.0)

            features_list.append([
                amt, hour, weekday, is_weekend,
                u_ratio, u_zscore, c_ratio, c_zscore,
                m_freq, c_freq, hour_sin, hour_cos
            ])

        return np.array(features_list, dtype=np.float64)


class AmountPercentileBaseline:
    """Baseline A: Flags transaction if amount > training percentile threshold."""
    def __init__(self, percentile: float = 95.0):
        self.percentile = percentile
        self.threshold = 5000.0

    def fit(self, X_train: np.ndarray, y_train: np.ndarray = None):
        amounts = X_train[:, 0]
        self.threshold = float(np.percentile(amounts, self.percentile))
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        amounts = X[:, 0]
        return (amounts > self.threshold).astype(int)

    def predict_score(self, X: np.ndarray) -> np.ndarray:
        amounts = X[:, 0]
        # Normalized ranking proxy
        return np.clip(amounts / (self.threshold * 2.0), 0.0, 1.0)


class StatisticalDeviationBaseline:
    """Baseline B: Flags transaction if amount > mean + k * std. k tuned on validation."""
    def __init__(self):
        self.mean = 1000.0
        self.std = 500.0
        self.k = 3.0

    def fit(self, X_train: np.ndarray, X_val: np.ndarray = None, y_val: np.ndarray = None):
        amounts = X_train[:, 0]
        self.mean = float(np.mean(amounts))
        self.std = float(np.std(amounts))
        if self.std < 1.0:
            self.std = 1.0

        # Select k using validation data (NOT test data)
        if X_val is not None and y_val is not None and len(y_val) > 0 and np.sum(y_val) > 0:
            val_amounts = X_val[:, 0]
            best_f1 = -1.0
            best_k = 3.0
            for candidate_k in [1.5, 2.0, 2.5, 3.0, 3.5, 4.0]:
                preds = (val_amounts > (self.mean + candidate_k * self.std)).astype(int)
                score = f1_score(y_val, preds, zero_division=0)
                if score > best_f1:
                    best_f1 = score
                    best_k = candidate_k
            self.k = best_k
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        amounts = X[:, 0]
        return (amounts > (self.mean + self.k * self.std)).astype(int)

    def predict_score(self, X: np.ndarray) -> np.ndarray:
        amounts = X[:, 0]
        z = (amounts - self.mean) / self.std
        return np.clip(z / (self.k * 2.0), 0.0, 1.0)


class IsolationForestAnomalyModel:
    """Primary Unsupervised Anomaly Detection Model."""
    def __init__(self, n_estimators: int = 100, contamination: float = 0.05, random_state: int = 42):
        self.model = IsolationForest(
            n_estimators=n_estimators,
            contamination=contamination,
            random_state=random_state
        )
        self.threshold = 0.50
        self.is_fitted = False

    def fit(self, X_train: np.ndarray, X_val: np.ndarray = None, y_val: np.ndarray = None):
        self.model.fit(X_train)
        self.is_fitted = True

        # Calibrate decision threshold on VALIDATION data only
        if X_val is not None and y_val is not None and len(y_val) > 0 and np.sum(y_val) > 0:
            val_scores = self.predict_score(X_val)
            best_f1 = -1.0
            best_t = 0.50
            for candidate_t in np.linspace(0.40, 0.75, 36):
                preds = (val_scores >= candidate_t).astype(int)
                score = f1_score(y_val, preds, zero_division=0)
                if score > best_f1:
                    best_f1 = score
                    best_t = candidate_t
            self.threshold = best_t
        return self

    def predict_score(self, X: np.ndarray) -> np.ndarray:
        """Returns pure ML continuous anomaly probability in [0, 1]."""
        raw = self.model.decision_function(X)
        # Decision function is negative for outliers; convert to [0, 1] probability
        return 1.0 / (1.0 + np.exp(raw * 5.0))

    def predict(self, X: np.ndarray) -> np.ndarray:
        scores = self.predict_score(X)
        return (scores >= self.threshold).astype(int)


def evaluate_anomaly_predictions(y_true: np.ndarray, y_pred: np.ndarray, y_scores: np.ndarray) -> Dict[str, Any]:
    """Calculates all standard classification metrics."""
    prec = float(precision_score(y_true, y_pred, zero_division=0))
    rec = float(recall_score(y_true, y_pred, zero_division=0))
    f1 = float(f1_score(y_true, y_pred, zero_division=0))

    try:
        roc_auc = float(roc_auc_score(y_true, y_scores))
    except Exception:
        roc_auc = 0.0

    try:
        pr_auc = float(average_precision_score(y_true, y_scores))
    except Exception:
        pr_auc = 0.0

    cm = confusion_matrix(y_true, y_pred).tolist()
    total = len(y_true)
    anom_cnt = int(np.sum(y_true))
    norm_cnt = total - anom_cnt
    prevalence = float(anom_cnt / total) if total > 0 else 0.0

    return {
        "precision": round(prec, 4),
        "recall": round(rec, 4),
        "f1": round(f1, 4),
        "roc_auc": round(roc_auc, 4),
        "pr_auc": round(pr_auc, 4),
        "confusion_matrix": cm,
        "normal_count": norm_cnt,
        "anomaly_count": anom_cnt,
        "prevalence": round(prevalence, 4),
        "total_test_samples": total
    }
