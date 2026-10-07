"""Remove privileged ML fields from public ledgers and old cached responses."""
ML_FIELDS = frozenset({
    'has_anomaly', 'anomaly_reason', 'is_anomaly', 'anomaly_score', 'anomaly_label',
    'anomaly_type', 'ground_truth_anomaly', 'anomaly_analysis', 'prediction',
    'model_version', 'features_summary', 'evaluation_metrics', 'recent_anomalies',
    'anomalies', 'unusual_activity', 'raw_anomaly_score', 'decision_score',
})


def strip_ml_details(value):
    if isinstance(value, dict):
        return {key: strip_ml_details(item) for key, item in value.items() if key not in ML_FIELDS}
    if isinstance(value, (list, tuple)):
        return [strip_ml_details(item) for item in value]
    return value
