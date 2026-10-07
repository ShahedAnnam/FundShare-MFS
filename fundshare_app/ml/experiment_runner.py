"""
FUNDShare ML Pipeline - Experiment Runner & Artifact Manager
Executes reproducible, leakage-free training, ablation, and evaluation.
Saves model binaries, feature configs, and metric results to ml_artifacts/.
"""
import os
import json
import joblib
from datetime import datetime
import numpy as np
import pandas as pd
from typing import Dict, Any

from django.conf import settings
from fundshare_app.models import Transaction, AnomalyResult, PurposeFund, BusinessCategory
from fundshare_app.ml.data_splits import get_temporal_transaction_splits
from fundshare_app.ml.anomaly_pipeline import (
    AnomalyFeaturePipeline, AmountPercentileBaseline,
    StatisticalDeviationBaseline, IsolationForestAnomalyModel,
    evaluate_anomaly_predictions
)
from fundshare_app.ml.forecasting_pipeline import (
    build_spending_panel, ForecastingFeaturePipeline,
    LastValueForecastingBaseline, MovingAverageForecastingBaseline,
    MLForecastingModel, calculate_forecast_metrics
)

ARTIFACTS_DIR = os.path.join(settings.BASE_DIR, 'ml_artifacts')
ANOMALY_ARTIFACTS_DIR = os.path.join(ARTIFACTS_DIR, 'anomaly')
FORECASTING_ARTIFACTS_DIR = os.path.join(ARTIFACTS_DIR, 'forecasting')


def ensure_artifact_dirs():
    os.makedirs(ANOMALY_ARTIFACTS_DIR, exist_ok=True)
    os.makedirs(FORECASTING_ARTIFACTS_DIR, exist_ok=True)


def run_anomaly_experiment(random_seed: int = 42) -> Dict[str, Any]:
    """
    Runs end-to-end reproducible anomaly detection training, baselines, ablation,
    and out-of-sample evaluation.
    """
    ensure_artifact_dirs()

    # 1. Load transactions from Django ORM
    qs = Transaction.objects.all().order_by('timestamp')
    df = pd.DataFrame([{
        'transaction_id': t.transaction_id,
        'sender_id': t.sender_id,
        'merchant_id': t.merchant_id,
        'amount': float(t.amount),
        'category': t.category or 'Other',
        'transaction_type': t.transaction_type,
        'timestamp': t.timestamp,
        'status': t.status,
        'is_anomaly': int(t.metadata.get('ground_truth_anomaly', False))
    } for t in qs])

    # 2. Strict Temporal Split
    splits = get_temporal_transaction_splits(df)

    # 3. Fit pipeline on TRAIN only
    pipeline = AnomalyFeaturePipeline().fit(splits.train_df)

    X_train = pipeline.transform(splits.train_df, feature_group='full')
    X_val = pipeline.transform(splits.val_df, feature_group='full')
    X_test = pipeline.transform(splits.test_df, feature_group='full')

    y_train = splits.train_df['is_anomaly'].values
    y_val = splits.val_df['is_anomaly'].values
    y_test = splits.test_df['is_anomaly'].values

    # 4. Train Baselines
    b1 = AmountPercentileBaseline(percentile=95.0).fit(X_train)
    b2 = StatisticalDeviationBaseline().fit(X_train, X_val, y_val)

    # 5. Train Isolation Forest (calibrated on Validation)
    model = IsolationForestAnomalyModel(
        n_estimators=100,
        contamination=0.05,
        random_state=random_seed
    ).fit(X_train, X_val, y_val)

    # 6. Evaluate on Test Split
    b1_metrics = evaluate_anomaly_predictions(y_test, b1.predict(X_test), b1.predict_score(X_test))
    b2_metrics = evaluate_anomaly_predictions(y_test, b2.predict(X_test), b2.predict_score(X_test))
    iso_metrics = evaluate_anomaly_predictions(y_test, model.predict(X_test), model.predict_score(X_test))

    # 7. Ablation Experiments on Test Split
    ablation_results = {}
    ablation_groups = [
        ('amount_only', 'Amount Only'),
        ('amount_temporal', 'Amount + Temporal'),
        ('amount_temporal_behavioral', 'Amount + Temporal + Behavioral'),
        ('full', 'Full Features')
    ]

    for grp_key, grp_label in ablation_groups:
        X_tr_abl = pipeline.transform(splits.train_df, feature_group=grp_key)
        X_v_abl = pipeline.transform(splits.val_df, feature_group=grp_key)
        X_te_abl = pipeline.transform(splits.test_df, feature_group=grp_key)

        m_abl = IsolationForestAnomalyModel(
            n_estimators=100,
            contamination=0.05,
            random_state=random_seed
        ).fit(X_tr_abl, X_v_abl, y_val)

        m_res = evaluate_anomaly_predictions(y_test, m_abl.predict(X_te_abl), m_abl.predict_score(X_te_abl))
        ablation_results[grp_key] = {
            'label': grp_label,
            'precision': m_res['precision'],
            'recall': m_res['recall'],
            'f1': m_res['f1'],
            'roc_auc': m_res['roc_auc'],
            'pr_auc': m_res['pr_auc']
        }

    # 8. Save Artifacts
    joblib.dump(model, os.path.join(ANOMALY_ARTIFACTS_DIR, 'model.joblib'))
    joblib.dump(pipeline, os.path.join(ANOMALY_ARTIFACTS_DIR, 'pipeline.joblib'))

    metrics_payload = {
        'model_type': 'IsolationForest',
        'random_seed': random_seed,
        'timestamp': datetime.utcnow().isoformat(),
        'train_period': f"{splits.train_df['timestamp'].iloc[0]} to {splits.train_end}",
        'validation_period': f"{splits.val_start} to {splits.val_end}",
        'test_period': f"{splits.test_start} to {splits.test_end}",
        'samples': {
            'total': splits.total_count,
            'train': splits.train_count,
            'validation': splits.val_count,
            'test': splits.test_count
        },
        'anomalies': {
            'train': splits.train_anomalies,
            'validation': splits.val_anomalies,
            'test': splits.test_anomalies
        },
        'baselines': {
            'amount_percentile_baseline': b1_metrics,
            'statistical_deviation_baseline': b2_metrics
        },
        'model_performance': iso_metrics,
        'ablation_study': ablation_results,
        'calibrated_threshold': round(float(model.threshold), 4)
    }

    with open(os.path.join(ANOMALY_ARTIFACTS_DIR, 'metrics.json'), 'w') as f:
        json.dump(metrics_payload, f, indent=2)

    with open(os.path.join(ANOMALY_ARTIFACTS_DIR, 'feature_config.json'), 'w') as f:
        json.dump({
            'features': [
                'amount', 'hour', 'weekday', 'is_weekend',
                'user_amount_ratio', 'user_z_score', 'cat_amount_ratio', 'cat_z_score',
                'merchant_freq', 'cat_freq', 'hour_sin', 'hour_cos'
            ],
            'version': 'iso_forest_v2.0_causal'
        }, f, indent=2)

    return metrics_payload


def run_forecasting_experiment(random_seed: int = 42) -> Dict[str, Any]:
    """
    Runs end-to-end reproducible time-series budget forecasting training, baselines,
    ablation, and out-of-sample evaluation.
    """
    ensure_artifact_dirs()

    # 1. Load completed transactions
    qs = Transaction.objects.filter(status='COMPLETED').order_by('timestamp')
    df = pd.DataFrame([{
        'transaction_id': t.transaction_id,
        'sender_id': t.sender_id,
        'amount': float(t.amount),
        'category': t.category or 'Other',
        'timestamp': t.timestamp
    } for t in qs])

    # 2. Build spending panel
    panel = build_spending_panel(df, freq='W')

    # 3. Extract causal features
    pipe = ForecastingFeaturePipeline()
    f_df, f_targets = pipe.extract_features_and_targets(panel, feature_group='full')

    # 4. Strict Temporal Sequence Split
    periods = sorted(f_df['period'].unique())
    n_p = len(periods)
    p_train = periods[:int(n_p * 0.6)]
    p_val = periods[int(n_p * 0.6):int(n_p * 0.8)]
    p_test = periods[int(n_p * 0.8):]

    train_mask = f_df['period'].isin(p_train)
    val_mask = f_df['period'].isin(p_val)
    test_mask = f_df['period'].isin(p_test)

    f_train, y_train = f_df[train_mask], f_targets[train_mask]
    f_val, y_val = f_df[val_mask], f_targets[val_mask]
    f_test, y_test = f_df[test_mask], f_targets[test_mask]

    # 5. Baselines
    b1 = LastValueForecastingBaseline()
    b2 = MovingAverageForecastingBaseline().fit(f_val, y_val)

    # 6. ML Model
    ml_model = MLForecastingModel(random_state=random_seed).fit(f_train, y_train)

    b1_metrics = calculate_forecast_metrics(y_test, b1.predict(f_test))
    b2_metrics = calculate_forecast_metrics(y_test, b2.predict(f_test))
    ml_metrics = calculate_forecast_metrics(y_test, ml_model.predict(f_test))

    # 7. Forecasting Ablation Study
    ablation_results = {}
    for grp_key, grp_label in [
        ('lag_only', 'Lag Features Only'),
        ('lag_rolling', 'Lag + Rolling Statistics'),
        ('full', 'Lag + Rolling + Contextual Features')
    ]:
        abl_df, abl_targets = pipe.extract_features_and_targets(panel, feature_group=grp_key)
        tr_m = abl_df['period'].isin(p_train)
        te_m = abl_df['period'].isin(p_test)

        m_abl = MLForecastingModel(random_state=random_seed).fit(abl_df[tr_m], abl_targets[tr_m])
        abl_eval = calculate_forecast_metrics(abl_targets[te_m], m_abl.predict(abl_df[te_m]))
        ablation_results[grp_key] = {
            'label': grp_label,
            'mae': abl_eval['mae'],
            'rmse': abl_eval['rmse'],
            'wape': abl_eval['wape'],
            'mape': abl_eval['mape']
        }

    # 8. Save Artifacts
    joblib.dump(ml_model, os.path.join(FORECASTING_ARTIFACTS_DIR, 'model.joblib'))
    joblib.dump(pipe, os.path.join(FORECASTING_ARTIFACTS_DIR, 'pipeline.joblib'))

    forecast_payload = {
        'model_type': 'HistGradientBoostingRegressor',
        'random_seed': random_seed,
        'timestamp': datetime.utcnow().isoformat(),
        'aggregation_level': 'Weekly User-Category Panel',
        'train_period': f"{p_train[0]} to {p_train[-1]}",
        'validation_period': f"{p_val[0]} to {p_val[-1]}",
        'test_period': f"{p_test[0]} to {p_test[-1]}",
        'samples': {
            'train': len(f_train),
            'validation': len(f_val),
            'test': len(f_test)
        },
        'baselines': {
            'last_value_baseline': b1_metrics,
            'moving_average_baseline': b2_metrics
        },
        'ml_model_performance': ml_metrics,
        'ablation_study': ablation_results
    }

    with open(os.path.join(FORECASTING_ARTIFACTS_DIR, 'metrics.json'), 'w') as f:
        json.dump(forecast_payload, f, indent=2)

    with open(os.path.join(FORECASTING_ARTIFACTS_DIR, 'feature_config.json'), 'w') as f:
        json.dump({
            'features': ml_model.feature_cols,
            'version': 'hist_gb_forecaster_v2.0'
        }, f, indent=2)

    return forecast_payload
