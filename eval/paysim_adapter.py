#!/usr/bin/env python
"""
PaySim Adapter & Evaluation Benchmark for FundShare-MFS Trust & Risk Engine.
Maps synthetic mobile money transactions (PaySim schema) into FundShare-MFS
behavioral feature representations and evaluates detection accuracy, action
distribution, and inference latency.
"""
import os
import sys
import time
import random
from pathlib import Path
from decimal import Decimal
from typing import Dict, List, Tuple

# Ensure workspace root is in sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Optional Django configuration for standalone execution
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fundshare_core.settings')
try:
    import django
    django.setup()
except Exception:
    pass

from fundshare_app.ml.policy import RiskPolicyEngine
from fundshare_app.ml.graph import TransactionGraphEngine


class PaySimFeatureMapper:
    """
    Transforms standard PaySim records into FundShare-MFS feature vectors.

    PaySim Fields:
      - step: int (1 step = 1 hour)
      - type: str (PAYMENT, TRANSFER, CASH_OUT, CASH_IN, DEBIT)
      - amount: float
      - nameOrig: str (Sender ID, e.g. "C1234567")
      - oldbalanceOrg: float
      - newbalanceOrig: float
      - nameDest: str (Recipient ID, e.g. "M9876543" or "C5555555")
      - oldbalanceDest: float
      - newbalanceDest: float
      - isFraud: int (0 or 1 ground truth)
    """

    TYPE_CATEGORY_MAP = {
        'PAYMENT': 'Grocery',
        'TRANSFER': 'Other',
        'CASH_OUT': 'Other',
        'DEBIT': 'Bills & Utilities',
        'CASH_IN': 'Other'
    }

    CATEGORY_BENCHMARKS = {
        'Grocery': 850.0,
        'Restaurant/Food': 600.0,
        'Medicine': 500.0,
        'Transport': 350.0,
        'Other': 1200.0,
        'Bills & Utilities': 1500.0
    }

    @classmethod
    def transform(cls, record: Dict) -> Dict:
        """Maps a PaySim record to FundShare feature dict."""
        amt = float(record['amount'])
        p_type = record['type']
        cat = cls.TYPE_CATEGORY_MAP.get(p_type, 'Other')
        cat_benchmark = cls.CATEGORY_BENCHMARKS.get(cat, 1200.0)

        step = int(record.get('step', 1))
        hour = step % 24

        # Compute sender profile statistics
        old_bal = float(record.get('oldbalanceOrg', 0.0))
        user_hist_mean = max(300.0, old_bal * 0.25) if old_bal > 0 else 800.0
        user_ratio = amt / user_hist_mean if user_hist_mean > 0 else 1.0
        cat_ratio = amt / cat_benchmark if cat_benchmark > 0 else 1.0

        # Approximate z-score deviations
        user_std = max(100.0, user_hist_mean * 0.40)
        user_zscore = max(0.0, (amt - user_hist_mean) / user_std)
        cat_std = max(100.0, cat_benchmark * 0.35)
        cat_zscore = max(0.0, (amt - cat_benchmark) / cat_std)

        # Baseline velocity approximation
        txns_per_hour = int(record.get('txns_per_hour', 1))

        # Synthetic baseline ML score from behavioral deviation
        norm_surge = min(1.0, user_ratio / 6.0)
        norm_z = min(1.0, user_zscore / 8.0)
        drain_factor = 0.25 if (old_bal > 0 and float(record.get('newbalanceOrig', 1.0)) == 0.0 and amt >= 5000) else 0.0
        night_factor = 0.15 if hour in [1, 2, 3, 4] else 0.0

        base_ml_score = min(0.95, (norm_surge * 0.45) + (norm_z * 0.35) + drain_factor + night_factor)

        return {
            'amount': amt,
            'category': cat,
            'hour': hour,
            'sender_id': record['nameOrig'],
            'receiver_id': record['nameDest'],
            'user_ratio': round(user_ratio, 2),
            'category_ratio': round(cat_ratio, 2),
            'user_zscore': round(user_zscore, 2),
            'category_zscore': round(cat_zscore, 2),
            'txns_per_hour': txns_per_hour,
            'base_ml_score': round(base_ml_score, 4),
            'is_fraud_ground_truth': int(record.get('isFraud', 0))
        }


def generate_synthetic_paysim_batch(n_samples: int = 150) -> List[Dict]:
    """Generates a representative batch of synthetic PaySim mobile money records."""
    random.seed(42)
    records = []

    mule_accounts = [f"MULE_{i:03d}" for i in range(1, 4)]
    senders = [f"C{random.randint(10000, 99999)}" for _ in range(30)]

    for i in range(n_samples):
        # 80% normal transactions, 20% fraudulent/mule scenarios
        is_fraud = 1 if (i % 5 == 0) else 0
        step = random.randint(1, 720)

        if not is_fraud:
            p_type = random.choice(['PAYMENT', 'PAYMENT', 'TRANSFER', 'DEBIT', 'CASH_OUT'])
            amount = round(random.uniform(50.0, 3500.0), 2)
            orig = random.choice(senders)
            dest = f"M{random.randint(1000, 9999)}" if p_type == 'PAYMENT' else random.choice(senders)
            old_bal = round(random.uniform(amount * 1.5, amount * 10.0), 2)
            new_bal = round(old_bal - amount, 2)
        else:
            # Fraud Vector: Account drain, large smurfing transfer, or mule cashout
            p_type = random.choice(['TRANSFER', 'CASH_OUT'])
            orig = random.choice(senders)
            dest = random.choice(mule_accounts)
            old_bal = round(random.uniform(15000.0, 85000.0), 2)
            amount = round(old_bal * random.uniform(0.70, 1.0), 2)  # Full balance drain
            new_bal = 0.0 if amount >= old_bal else round(old_bal - amount, 2)

        records.append({
            'step': step,
            'type': p_type,
            'amount': amount,
            'nameOrig': orig,
            'oldbalanceOrg': old_bal,
            'newbalanceOrig': new_bal,
            'nameDest': dest,
            'oldbalanceDest': random.uniform(500.0, 5000.0),
            'newbalanceDest': random.uniform(5000.0, 50000.0),
            'isFraud': is_fraud
        })

    return records


def evaluate_paysim_benchmark(n_samples: int = 150) -> Dict:
    """Executes end-to-end evaluation benchmark using PaySim feature adapter."""
    records = generate_synthetic_paysim_batch(n_samples=n_samples)
    policy_engine = RiskPolicyEngine.get_instance()

    tp = fp = tn = fn = 0
    action_counts = {'ALLOW': 0, 'STEP_UP_PIN': 0, 'FLAG_FOR_REVIEW': 0}
    latencies = []

    for rec in records:
        start_t = time.perf_counter()

        feat = PaySimFeatureMapper.transform(rec)
        risk_score = feat['base_ml_score']
        ground_truth = feat['is_fraud_ground_truth']

        eval_res = policy_engine.evaluate(risk_score=risk_score, features=feat)
        action = eval_res['action']
        action_counts[action] = action_counts.get(action, 0) + 1

        elapsed_ms = (time.perf_counter() - start_t) * 1000.0
        latencies.append(elapsed_ms)

        # Classification threshold: FLAG_FOR_REVIEW or STEP_UP_PIN classified as fraud intervention
        predicted_flag = 1 if action in ['FLAG_FOR_REVIEW', 'STEP_UP_PIN'] else 0

        if predicted_flag == 1 and ground_truth == 1:
            tp += 1
        elif predicted_flag == 1 and ground_truth == 0:
            fp += 1
        elif predicted_flag == 0 and ground_truth == 0:
            tn += 1
        elif predicted_flag == 0 and ground_truth == 1:
            fn += 1

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
    fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0
    avg_latency = sum(latencies) / len(latencies) if latencies else 0.0

    return {
        'total_samples': n_samples,
        'tp': tp, 'fp': fp, 'tn': tn, 'fn': fn,
        'precision': round(precision, 4),
        'recall': round(recall, 4),
        'f1_score': round(f1, 4),
        'fpr': round(fpr, 4),
        'action_counts': action_counts,
        'avg_latency_ms': round(avg_latency, 3)
    }


def print_benchmark_report(results: Dict):
    """Prints a structured benchmark report."""
    print("\n" + "=" * 70)
    print("  FUNDSHARE-MFS: PAYSIM BENCHMARK EVALUATION RESULTS")
    print("=" * 70)
    print(f"  Total Evaluated Transactions : {results['total_samples']}")
    print(f"  Mean Evaluation Latency      : {results['avg_latency_ms']:.3f} ms / transaction")
    print("-" * 70)
    print("  CONFUSION MATRIX & METRICS:")
    print(f"  • True Positives  (TP) : {results['tp']:<4} | False Positives (FP) : {results['fp']:<4}")
    print(f"  • True Negatives  (TN) : {results['tn']:<4} | False Negatives (FN) : {results['fn']:<4}")
    print(f"  • Precision            : {results['precision'] * 100:.2f}%")
    print(f"  • Recall (Sensitivity) : {results['recall'] * 100:.2f}%")
    print(f"  • F1-Score             : {results['f1_score']:.4f}")
    print(f"  • False Positive Rate  : {results['fpr'] * 100:.2f}%")
    print("-" * 70)
    print("  ACTION TIER DISTRIBUTION:")
    for action, count in results['action_counts'].items():
        pct = (count / results['total_samples']) * 100
        print(f"  • {action:<16} : {count:>4} ({pct:>5.1f}%)")
    print("=" * 70 + "\n")


if __name__ == '__main__':
    res = evaluate_paysim_benchmark(n_samples=200)
    print_benchmark_report(res)
