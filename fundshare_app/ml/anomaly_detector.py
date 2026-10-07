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


class AnomalyDetector:
    _instance = None
    _lock = RLock()

    def __init__(self, artifact_path=ARTIFACT):
        self.bundle = None
        self.artifact_path = Path(artifact_path)
        self.load_error = None
        if self.artifact_path.exists():
            try:
                # Load only a trusted deployment artifact, never browser-uploaded pickle files.
                bundle = joblib.load(self.artifact_path)
                if bundle['metadata']['sklearn_version'] != sklearn.__version__:
                    raise ValueError('Model library version changed; retrain the model.')
                if bundle['metadata']['input_fields'] != list(INPUT_FIELDS):
                    raise ValueError('Model feature schema changed; retrain the model.')
                self.bundle = bundle
            except Exception:
                self.load_error = 'The model artifact could not be loaded. Retraining is required.'
                logger.exception('Could not load the anomaly model')

    @classmethod
    def get_instance(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @property
    def evaluation_metrics(self):
        if self.bundle:
            meta = dict(self.bundle['metadata'])
            meta['f1_score'] = meta.get('f1', 0.0)
            return meta
        # Check ml_artifacts/anomaly/metrics.json if bundle is not loaded
        metrics_path = Path(settings.BASE_DIR) / 'ml_artifacts' / 'anomaly' / 'metrics.json'
        if metrics_path.exists():
            try:
                data = json.loads(metrics_path.read_text(encoding='utf-8'))
                perf = data.get('model_performance', {})
                f1_val = perf.get('f1', 0.0)
                return {
                    'precision': perf.get('precision', 0.0),
                    'recall': perf.get('recall', 0.0),
                    'f1': f1_val,
                    'f1_score': f1_val,
                    'roc_auc': perf.get('roc_auc', 0.0),
                    'pr_auc': perf.get('pr_auc', 0.0),
                    'model_version': 'iso_forest_v2.0'
                }
            except Exception:
                pass
        return {'available': False, 'message': self.load_error or 'Train the anomaly model first.'}

    @classmethod
    def train(cls, dataset=DATASET, artifact=ARTIFACT):
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
        # Fixed prior, not selected using labels or held-out test results.
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
        """Seed compatibility: reuse the saved dataset model, never fit live ledgers."""
        if not self.bundle:
            self.train()
            self.__init__(self.artifact_path)
        return self.evaluation_metrics

    def analyze_transaction(self, txn):
        if not self.bundle:
            # Fall back to training if not present
            self.train()
            self.__init__(self.artifact_path)
        if not self.bundle:
            raise RuntimeError('Anomaly model unavailable; retry scoring after training.')
        inputs = transaction_features(txn)
        vector = self.bundle['vectorizer'].transform(feature_records([inputs]))
        model = self.bundle['model']
        prediction = int(model.predict(vector)[0] == -1)
        severity = float(-model.score_samples(vector)[0])
        score = float(np.searchsorted(self.bundle['reference_scores'], severity, side='right') / len(self.bundle['reference_scores']))
        metadata = self.bundle['metadata']
        in_domain = (txn.transaction_type in metadata['training_transaction_types']
                     and inputs['category'] in metadata['training_categories']
                     and txn.payment_source in metadata['training_sources'])
        reason = 'Isolation Forest classified this transaction as ' + ('Anomaly (1).' if prediction else 'Normal (0).')
        if not in_domain:
            reason += ' Outside the evaluated training domain; interpret with caution.'
        return {'is_anomaly': bool(prediction), 'anomaly_score': score, 'reason': reason,
                'features_summary': {**inputs, 'raw_anomaly_score': severity,
                                     'decision_score': float(model.decision_function(vector)[0]),
                                     'in_training_domain': in_domain},
                'model_version': metadata['model_version']}

    @classmethod
    def record_transaction(cls, pk, force=False):
        try:
            txn = Transaction.objects.get(pk=pk)
            detector = cls.get_instance()
            version = detector.evaluation_metrics.get('model_version')
            if not force and version and AnomalyResult.objects.filter(transaction=txn, model_version=version).exists():
                return True
            analysis = detector.analyze_transaction(txn)
            AnomalyResult.objects.update_or_create(transaction=txn, defaults={'user_id': txn.sender_id, **analysis})
            return True
        except Transaction.DoesNotExist:
            return False
        except Exception:
            logger.exception('Anomaly scoring unavailable for transaction pk=%s; backfill required', pk)
            return False
