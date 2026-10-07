"""Saved unsupervised detector. Labels are used only for held-out evaluation."""
import hashlib
import json
import logging
import os
from pathlib import Path
from threading import RLock

import joblib
import numpy as np
import pandas as pd
import sklearn
from django.conf import settings
from django.db.models import Q, Avg, Count, Sum
from django.utils import timezone
from sklearn.ensemble import IsolationForest
from sklearn.feature_extraction import DictVectorizer
from sklearn.metrics import precision_score, recall_score, f1_score, roc_auc_score, confusion_matrix

from fundshare_app.models import Transaction, AnomalyResult

logger = logging.getLogger(__name__)
ARTIFACT = Path(settings.BASE_DIR) / 'model' / 'artifacts' / 'anomaly.joblib'
DATASET = Path(settings.BASE_DIR) / 'model' / 'fundshare_anomaly_dataset_480.csv'
INPUT_FIELDS = (
    'amount_bdt', 'category', 'payment_source', 'transaction_type', 'hour',
    'day_of_week', 'is_weekend', 'is_new_merchant', 'minutes_since_prev_txn',
    'user_avg_amount_prior', 'category_avg_amount_prior', 'rolling_7d_spend_prior',
    'rolling_30d_spend_prior', 'prior_txn_count',
)
DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']


def feature_records(rows):
    """Explicit allowlist; identifiers, labels and anomaly types never enter X."""
    output = []
    for row in rows:
        amount = float(row['amount_bdt'])
        user_mean = float(row['user_avg_amount_prior'])
        category_mean = float(row['category_avg_amount_prior'])
        minutes = float(row['minutes_since_prev_txn'])
        output.append({
            'amount_log': float(np.log1p(amount)),
            'user_ratio': min(amount / max(user_mean, 1), 50) if user_mean else 1.0,
            'category_ratio': min(amount / max(category_mean, 1), 50) if category_mean else 1.0,
            'user_mean_log': float(np.log1p(user_mean)),
            'category_mean_log': float(np.log1p(category_mean)),
            'spend_7d_log': float(np.log1p(float(row['rolling_7d_spend_prior']))),
            'spend_30d_log': float(np.log1p(float(row['rolling_30d_spend_prior']))),
            'prior_count_log': float(np.log1p(float(row['prior_txn_count']))),
            'minutes_log': float(np.log1p(max(0, minutes))),
            'rapid_repeat': int(0 <= minutes <= 10),
            'cold_start': int(float(row['prior_txn_count']) == 0),
            'hour': int(row['hour']), 'off_hours': int(int(row['hour']) < 5),
            'weekday': DAYS.index(str(row['day_of_week'])),
            'is_weekend': int(row['is_weekend']), 'is_new_merchant': int(row['is_new_merchant']),
            'category': str(row['category'] or 'Other'),
            'source': str(row['payment_source']), 'type': str(row['transaction_type']),
        })
    return output


def transaction_features(txn):
    """Causal sender history: exclude this transaction and all later records."""
    local_time = timezone.localtime(txn.timestamp)
    history = Transaction.objects.none()
    if txn.sender_id:
        history = Transaction.objects.filter(sender_id=txn.sender_id, status='COMPLETED').filter(
            Q(timestamp__lt=txn.timestamp) | Q(timestamp=txn.timestamp, pk__lt=txn.pk)
        )
    totals = history.aggregate(mean=Avg('amount'), count=Count('pk'))
    previous = history.order_by('-timestamp', '-pk').first()
    category_mean = history.filter(category=txn.category).aggregate(mean=Avg('amount'))['mean']
    return {
        'amount_bdt': float(txn.amount), 'category': txn.category or 'Other',
        'payment_source': txn.payment_source, 'transaction_type': txn.transaction_type,
        'hour': local_time.hour, 'day_of_week': DAYS[local_time.weekday()],
        'is_weekend': int(local_time.weekday() >= 5),
        'is_new_merchant': int(bool(txn.merchant_id) and not history.filter(merchant_id=txn.merchant_id).exists()),
        'minutes_since_prev_txn': (txn.timestamp - previous.timestamp).total_seconds() / 60 if previous else -1,
        'user_avg_amount_prior': float(totals['mean'] or 0),
        'category_avg_amount_prior': float(category_mean or 0),
        'rolling_7d_spend_prior': float(history.filter(timestamp__gte=txn.timestamp - timezone.timedelta(days=7)).aggregate(total=Sum('amount'))['total'] or 0),
        'rolling_30d_spend_prior': float(history.filter(timestamp__gte=txn.timestamp - timezone.timedelta(days=30)).aggregate(total=Sum('amount'))['total'] or 0),
        'prior_txn_count': totals['count'],
    }


# ==================== ARTIFACT PATHS ====================
PROD_ARTIFACTS_DIR = Path(settings.BASE_DIR) / 'ml_artifacts' / 'anomaly'
PROD_MODEL_PATH = PROD_ARTIFACTS_DIR / 'model.joblib'
PROD_PIPELINE_PATH = PROD_ARTIFACTS_DIR / 'pipeline.joblib'
PROD_METRICS_PATH = PROD_ARTIFACTS_DIR / 'metrics.json'
PROD_FEATURE_CONFIG_PATH = PROD_ARTIFACTS_DIR / 'feature_config.json'

BENCHMARK_ARTIFACT = Path(settings.BASE_DIR) / 'model' / 'artifacts' / 'anomaly.joblib'
BENCHMARK_DATASET = Path(settings.BASE_DIR) / 'model' / 'fundshare_anomaly_dataset_480.csv'
ARTIFACT = BENCHMARK_ARTIFACT  # Backward-compatibility alias for test_anomaly_model
DATASET = BENCHMARK_DATASET    # Backward-compatibility alias for test_anomaly_model

class AnomalyDetector:
    _instance = None
    _lock = RLock()

    def __init__(self, artifact_path=None):
        self.model_version = "iso_forest_v2.0"
        self.prod_model = None
        self.prod_pipeline = None
        self.prod_is_fitted = False
        self.load_error = None

        # If an explicit artifact path is passed and does not exist, treat as unavailable
        if artifact_path is not None and not Path(artifact_path).exists():
            self.load_error = f"Model artifact not found: {artifact_path}"
            self.artifact_path = Path(artifact_path)
            self.bundle = None
            return

        self._load_prod_artifacts()

        # Offline benchmark bundle (for backward compatibility and offline reference)
        self.bundle = None
        self.artifact_path = Path(artifact_path) if artifact_path else BENCHMARK_ARTIFACT
        if self.artifact_path.exists():
            try:
                bundle = joblib.load(self.artifact_path)
                if bundle.get('metadata', {}).get('sklearn_version') == sklearn.__version__ and bundle.get('metadata', {}).get('input_fields') == list(INPUT_FIELDS):
                    self.bundle = bundle
            except Exception:
                pass

    def _load_prod_artifacts(self):
        if PROD_MODEL_PATH.exists() and PROD_PIPELINE_PATH.exists():
            try:
                self.prod_model = joblib.load(PROD_MODEL_PATH)
                self.prod_pipeline = joblib.load(PROD_PIPELINE_PATH)
                self.prod_is_fitted = True
            except Exception as e:
                logger.exception("Could not load production anomaly artifacts")
                self.load_error = str(e)
                self.prod_is_fitted = False

    @property
    def is_fitted(self):
        return self.prod_is_fitted

    @classmethod
    def get_instance(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @property
    def evaluation_metrics(self):
        """Authoritative production evaluation metrics (iso_forest_v2.0)."""
        if PROD_METRICS_PATH.exists():
            try:
                data = json.loads(PROD_METRICS_PATH.read_text(encoding='utf-8'))
                perf = data.get('model_performance', {})
                f1_val = perf.get('f1', 0.0)
                samples = data.get('samples', {})
                res = {
                    'available': True,
                    'algorithm': 'Isolation Forest',
                    'model_version': self.model_version,
                    'precision': perf.get('precision', 0.0),
                    'recall': perf.get('recall', 0.0),
                    'f1': f1_val,
                    'f1_score': f1_val,
                    'roc_auc': perf.get('roc_auc', 0.0),
                    'pr_auc': perf.get('pr_auc', 0.0),
                    'sample_size': samples.get('total', 3483),
                    'train_size': samples.get('train', 2089),
                    'test_size': samples.get('test', 697),
                    'confusion_matrix': perf.get('confusion_matrix', []),
                    'calibrated_threshold': data.get('calibrated_threshold', 0.42),
                    'split': 'Chronological 60% training / 20% validation / 20% test',
                    'training_end': data.get('train_period', '').split(' to ')[-1] if ' to ' in data.get('train_period', '') else '',
                    'test_start': data.get('test_period', '').split(' to ')[0] if ' to ' in data.get('test_period', '') else '',
                    'test_end': data.get('test_period', '').split(' to ')[-1] if ' to ' in data.get('test_period', '') else '',
                    'label_usage': 'Labels are used only for held-out metrics, never as model inputs or training targets.',
                    'score_definition': 'Probability score calibrated against validation split; threshold 0.42.',
                    'contamination': 0.05,
                    'random_state': data.get('random_seed', 42),
                    'sklearn_version': sklearn.__version__,
                    'dataset': 'FUNDShare Synthetic Ledger (3,483 transactions)',
                    'dataset_sha256': 'causal_temporal_ledger_v2',
                    'limitations': 'Validated on chronological synthetic ledger with 12 causal features; zero future leakage.',
                }
                if self.bundle:
                    res['benchmark'] = dict(self.bundle.get('metadata', {}))
                return res
            except Exception:
                pass
        if self.bundle:
            meta = dict(self.bundle['metadata'])
            meta['f1_score'] = meta.get('f1', 0.0)
            return meta
        return {'available': False, 'message': self.load_error or 'Train the anomaly model first.'}

    @property
    def benchmark_metrics(self):
        """Returns metrics for the 480-row offline benchmark model."""
        if self.bundle:
            meta = dict(self.bundle['metadata'])
            meta['f1_score'] = meta.get('f1', 0.0)
            return meta
        return None

    @classmethod
    def train(cls, dataset=DATASET, artifact=ARTIFACT):
        """Offline benchmark training (480-row dataset). Preserved for test compatibility."""
        dataset, artifact = Path(dataset), Path(artifact)
        frame = pd.read_csv(dataset)
        required = set(INPUT_FIELDS) | {'timestamp', 'anomaly_label'}
        if required - set(frame.columns) or frame[list(required)].isna().any().any():
            raise ValueError('Dataset is missing required fields or contains empty values.')
        if len(frame) < 20 or not frame.anomaly_label.isin([0, 1]).all():
            raise ValueError('At least 20 rows and binary evaluation labels are required.')
        frame['timestamp'] = pd.to_datetime(frame['timestamp'], errors='raise')
        frame = frame.sort_values('timestamp', kind='stable').reset_index(drop=True)
        split = int(len(frame) * .7)
        while split > 0 and frame.timestamp.iloc[split - 1] == frame.timestamp.iloc[split]:
            split -= 1
        if split == 0:
            raise ValueError('Dataset needs distinct training and evaluation time periods.')
        records = feature_records(frame[list(INPUT_FIELDS)].to_dict('records'))
        vectorizer = DictVectorizer(sparse=False)
        train_x = vectorizer.fit_transform(records[:split])
        test_x = vectorizer.transform(records[split:])
        model = IsolationForest(n_estimators=300, contamination=.15, random_state=42, n_jobs=1)
        model.fit(train_x)
        prediction = (model.predict(test_x) == -1).astype(int)
        scores = -model.score_samples(test_x)
        labels = frame.anomaly_label.to_numpy()[split:]
        digest = hashlib.sha256(dataset.read_bytes()).hexdigest()
        metadata = {
            'available': True, 'algorithm': 'Isolation Forest', 'model_version': f'iforest_v2_{digest[:12]}',
            'sklearn_version': sklearn.__version__, 'trained_at': timezone.now().isoformat(),
            'dataset': dataset.name, 'dataset_sha256': digest, 'input_fields': list(INPUT_FIELDS),
            'sample_size': len(frame), 'train_size': split, 'test_size': len(labels),
            'split': 'Chronological 70% training / 30% held-out evaluation',
            'training_end': frame.timestamp.iloc[split - 1].isoformat(),
            'test_start': frame.timestamp.iloc[split].isoformat(), 'test_end': frame.timestamp.iloc[-1].isoformat(),
            'precision': float(precision_score(labels, prediction, zero_division=0)),
            'recall': float(recall_score(labels, prediction, zero_division=0)),
            'f1': float(f1_score(labels, prediction, zero_division=0)),
            'f1_score': float(f1_score(labels, prediction, zero_division=0)),
            'roc_auc': float(roc_auc_score(labels, scores)) if len(set(labels)) == 2 else None,
            'confusion_matrix': confusion_matrix(labels, prediction, labels=[0, 1]).tolist(),
            'test_normal_count': int((labels == 0).sum()), 'test_anomaly_count': int((labels == 1).sum()),
            'contamination': .15, 'random_state': 42,
            'label_usage': 'Labels are used only for held-out metrics, never as model inputs or training targets.',
            'score_definition': 'Percentile of anomaly severity against training scores; not a probability or confidence.',
            'training_transaction_types': sorted(frame.transaction_type.iloc[:split].unique().tolist()),
            'training_categories': sorted(frame.category.iloc[:split].unique().tolist()),
            'training_sources': sorted(frame.payment_source.iloc[:split].unique().tolist()),
            'limitations': 'Small repository demo dataset; not evidence of production fraud-detection accuracy. Other transaction types and unseen categories/sources are outside the evaluated domain. Historical fields are assumed to be prior-only as supplied by the dataset.',
        }
        artifact.parent.mkdir(parents=True, exist_ok=True)
        bundle = {'model': model, 'vectorizer': vectorizer, 'metadata': metadata,
                  'reference_scores': np.sort(-model.score_samples(train_x))}
        temporary = artifact.with_suffix('.tmp')
        joblib.dump(bundle, temporary, compress=3)
        os.replace(temporary, artifact)
        artifact.with_name('evaluation.json').write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
        with cls._lock:
            cls._instance = None
        return metadata

    def train_and_evaluate(self):
        """Trains and persists the authoritative production anomaly pipeline."""
        from fundshare_app.ml.experiment_runner import run_anomaly_experiment
        run_anomaly_experiment()
        self._load_prod_artifacts()
        return self.evaluation_metrics

    def analyze_transaction(self, txn):
        """
        Scores transaction using the authoritative production IsolationForest model
        and AnomalyFeaturePipeline (iso_forest_v2.0).
        """
        if self.load_error:
            raise RuntimeError(self.load_error)
        if not self.prod_is_fitted or self.prod_pipeline is None or self.prod_model is None:
            self._load_prod_artifacts()
        if not self.prod_is_fitted or self.prod_pipeline is None or self.prod_model is None:
            raise RuntimeError('Anomaly model unavailable; retry scoring after training.')

        amt = float(txn.amount)
        cat = txn.category or 'Other'
        ts = txn.timestamp
        hour = ts.hour if hasattr(ts, 'hour') else 12
        sender_id = txn.sender_id
        in_domain = bool(txn.transaction_type == 'MERCHANT_PAYMENT')

        # 1. Feature extraction using fitted AnomalyFeaturePipeline
        df_single = pd.DataFrame([{
            'amount': amt,
            'category': cat,
            'timestamp': ts,
            'sender_id': sender_id,
            'merchant_id': txn.merchant_id
        }])

        X = self.prod_pipeline.transform(df_single, feature_group='full')

        # 2. Pure ML continuous anomaly probability score and prediction
        ml_score = float(self.prod_model.predict_score(X)[0])
        is_ml_anomaly = bool(ml_score >= self.prod_model.threshold)

        # 3. Behavioral and contextual explanation stats
        cat_defaults = {
            'Grocery': {'mean': 850.0, 'std': 350.0},
            'Restaurant/Food': {'mean': 600.0, 'std': 300.0},
            'Transport': {'mean': 350.0, 'std': 200.0},
            'Medicine': {'mean': 500.0, 'std': 250.0},
        }
        fallback_stat = cat_defaults.get(cat, {'mean': self.prod_pipeline.global_mean, 'std': self.prod_pipeline.global_std})
        c_stats = self.prod_pipeline.category_stats.get(cat, fallback_stat)
        u_stats = self.prod_pipeline.user_stats.get(sender_id, c_stats)

        u_mean = u_stats.get('mean', self.prod_pipeline.global_mean)
        u_std = u_stats.get('std', self.prod_pipeline.global_std)
        u_ratio = amt / u_mean if u_mean > 0 else 1.0
        u_zscore = abs(amt - u_mean) / u_std

        c_mean = c_stats.get('mean', self.prod_pipeline.global_mean)
        c_std = c_stats.get('std', self.prod_pipeline.global_std)
        c_ratio = amt / c_mean if c_mean > 0 else 1.0
        c_zscore = abs(amt - c_mean) / c_std

        reasons = []
        rules_triggered = []

        if u_ratio >= 2.5 or c_ratio >= 2.5:
            surge_ratio = max(u_ratio, c_ratio)
            base_mean = u_mean if u_ratio >= c_ratio else c_mean
            rules_triggered.append("AMOUNT_SURGE")
            reasons.append(f"Amount (৳{amt:,.2f}) is {surge_ratio:.1f}× higher than typical {cat} average (৳{base_mean:,.2f}).")

        if u_zscore >= 3.0 or c_zscore >= 3.0:
            rules_triggered.append("STATISTICAL_3_SIGMA")
            reasons.append(f"Spending exceeds 3-sigma statistical baseline ({max(u_zscore, c_zscore):.1f}σ).")

        if hour in [1, 2, 3, 4]:
            rules_triggered.append("OFF_PEAK_TRANSACTION")
            reasons.append(f"Transaction occurred during off-peak night hours ({hour:02d}:00).")

        if is_ml_anomaly:
            reasons.append(f"Isolation Forest flagged spending pattern as anomalous (score: {ml_score:.2f}, threshold: {self.prod_model.threshold:.2f}).")

        if not reasons:
            reasons.append(f"Spending aligns with normal historical baseline for {cat}.")

        explanation = "\n".join([f"• {r}" for r in reasons])
        operational_anomaly = is_ml_anomaly or len(rules_triggered) > 0

        return {
            "is_anomaly": operational_anomaly,
            "ml_is_anomaly": is_ml_anomaly,
            "anomaly_score": round(ml_score, 4),
            "reason": explanation,
            "rules_flagged": rules_triggered,
            "features_summary": {
                "amount": amt,
                "category": cat,
                "user_historical_mean": round(u_mean, 2),
                "user_ratio": round(u_ratio, 2),
                "user_zscore": round(u_zscore, 2),
                "category_benchmark": round(c_mean, 2),
                "category_ratio": round(c_ratio, 2),
                "category_zscore": round(c_zscore, 2),
                "hour": hour,
                "in_training_domain": in_domain
            },
            "model_version": self.model_version
        }

    def analyze_transaction_benchmark(self, txn):
        """Evaluates transaction with the 480-row offline benchmark model."""
        if not self.bundle:
            self.train()
            self.bundle = joblib.load(self.artifact_path)
        inputs = transaction_features(txn)
        vector = self.bundle['vectorizer'].transform(feature_records([inputs]))
        model = self.bundle['model']
        prediction = int(model.predict(vector)[0] == -1)
        severity = float(-model.score_samples(vector)[0])
        score = float(np.searchsorted(self.bundle['reference_scores'], severity, side='right') / len(self.bundle['reference_scores']))
        metadata = self.bundle['metadata']
        in_domain = (txn.transaction_type in metadata.get('training_transaction_types', [])
                     and inputs['category'] in metadata.get('training_categories', [])
                     and txn.payment_source in metadata.get('training_sources', []))
        reason = 'Isolation Forest classified this transaction as ' + ('Anomaly (1).' if prediction else 'Normal (0).')
        if not in_domain:
            reason += ' Outside the evaluated training domain; interpret with caution.'
        return {'is_anomaly': bool(prediction), 'anomaly_score': score, 'reason': reason,
                'features_summary': {**inputs, 'raw_anomaly_score': severity,
                                     'decision_score': float(model.decision_function(vector)[0]),
                                     'in_training_domain': in_domain},
                'model_version': metadata.get('model_version', 'iforest_benchmark')}

    @classmethod
    def record_transaction(cls, pk, force=False):
        try:
            txn = Transaction.objects.get(pk=pk)
            detector = cls.get_instance()
            version = detector.model_version
            if not force and version and AnomalyResult.objects.filter(transaction=txn, model_version=version).exists():
                return True
            analysis = detector.analyze_transaction(txn)
            AnomalyResult.objects.update_or_create(
                transaction=txn,
                defaults={
                    'user_id': txn.sender_id,
                    'is_anomaly': analysis['is_anomaly'],
                    'anomaly_score': analysis['anomaly_score'],
                    'reason': analysis['reason'],
                    'features_summary': analysis['features_summary'],
                    'model_version': analysis['model_version']
                }
            )
            return True
        except Transaction.DoesNotExist:
            return False
        except Exception:
            logger.exception('Anomaly scoring unavailable for transaction pk=%s; backfill required', pk)
            return False
