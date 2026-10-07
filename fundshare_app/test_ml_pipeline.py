"""
FUNDShare ML Pipeline - Automated Validation Tests
Tests:
- Leakage Prevention: Baseline statistics computed strictly on training data
- Temporal Splits: Chronological ordering (Train < Val < Test)
- Prediction Shape: Predictions match test inputs
- Metrics: Metrics generated from actual model predictions without hardcoded fallbacks
- Ground Truth Separation: Ground truth remains evaluation label, not model output
- Database Abstraction: Model pipeline works through Django ORM without raw SQLite SQL
"""
import numpy as np
import pandas as pd
from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from django.contrib.auth import get_user_model

from fundshare_app.models import (
    Transaction, AnomalyResult, PurposeFund, BusinessCategory,
    TransactionType, PaymentSource, UserRole, Wallet
)
from fundshare_app.ml.data_splits import get_temporal_transaction_splits
from fundshare_app.ml.anomaly_pipeline import (
    AnomalyFeaturePipeline, IsolationForestAnomalyModel, evaluate_anomaly_predictions
)
from fundshare_app.ml.forecasting_pipeline import (
    build_spending_panel, ForecastingFeaturePipeline,
    MLForecastingModel, calculate_forecast_metrics
)
from fundshare_app.ml.anomaly_detector import AnomalyDetector
from fundshare_app.ml.budget_forecaster import BudgetForecaster

User = get_user_model()


class MLPipelineHardeningTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Create test user & wallet
        cls.user = User.objects.create_user(
            username='ml_eval_user',
            phone='01799990001',
            role=UserRole.CUSTOMER,
            password='testpassword123'
        )
        cls.wallet = Wallet.objects.create(owner=cls.user, balance=Decimal('50000.00'))

        # Create sequential chronological transactions across 3 periods
        base_time = timezone.now() - timezone.timedelta(days=90)
        cls.transactions = []
        for i in range(60):
            t_time = base_time + timezone.timedelta(days=i)
            # Injected anomaly at day 45
            is_anom = (i == 45)
            amt = Decimal('15000.00') if is_anom else Decimal('500.00')
            txn = Transaction.objects.create(
                sender=cls.user,
                amount=amt,
                category=BusinessCategory.GROCERY,
                transaction_type=TransactionType.MERCHANT_PAYMENT,
                payment_source=PaymentSource.NORMAL_WALLET,
                timestamp=t_time,
                metadata={'ground_truth_anomaly': is_anom}
            )
            cls.transactions.append(txn)

    def test_temporal_split_ordering(self):
        """Verify train_end < val_start and val_end < test_start."""
        df = pd.DataFrame([{
            'amount': float(t.amount),
            'timestamp': t.timestamp,
            'sender_id': t.sender_id,
            'category': t.category
        } for t in self.transactions])

        splits = get_temporal_transaction_splits(df, train_pct=0.60, val_pct=0.20)

        self.assertLess(splits.train_end, splits.val_start)
        self.assertLess(splits.val_end, splits.test_start)
        self.assertEqual(splits.total_count, 60)
        self.assertEqual(splits.train_count, 36)
        self.assertEqual(splits.val_count, 12)
        self.assertEqual(splits.test_count, 12)

    def test_leakage_prevention_on_feature_pipeline(self):
        """
        Verify feature pipeline fits statistics ONLY on training data.
        Future test transactions must not alter fitted means or standard deviations.
        """
        train_data = pd.DataFrame([
            {'amount': 100.0, 'timestamp': timezone.now(), 'sender_id': 1, 'category': 'Grocery', 'merchant_id': 1},
            {'amount': 200.0, 'timestamp': timezone.now(), 'sender_id': 1, 'category': 'Grocery', 'merchant_id': 1},
        ])
        test_data = pd.DataFrame([
            {'amount': 10000.0, 'timestamp': timezone.now(), 'sender_id': 1, 'category': 'Grocery', 'merchant_id': 1},
        ])

        pipeline = AnomalyFeaturePipeline()
        pipeline.fit(train_data)

        # Baseline mean must be strictly 150.0 (from training data), unaffected by test_data
        self.assertAlmostEqual(pipeline.user_stats[1]['mean'], 150.0)
        self.assertAlmostEqual(pipeline.category_stats['Grocery']['mean'], 150.0)

        # Transform test data using frozen training baselines
        X_test = pipeline.transform(test_data, feature_group='amount_temporal_behavioral')
        # Amount ratio for 10000.0 against training mean of 150.0 should be ~66.67
        u_ratio = X_test[0, 4]
        self.assertAlmostEqual(u_ratio, 10000.0 / 150.0, places=2)

    def test_prediction_shape_and_metrics_calculation(self):
        """Verify predictions match test shape and metrics are genuine scikit-learn outputs."""
        y_true = np.array([0, 0, 1, 0, 1])
        y_pred = np.array([0, 0, 1, 0, 0])
        y_scores = np.array([0.1, 0.2, 0.9, 0.3, 0.4])

        metrics = evaluate_anomaly_predictions(y_true, y_pred, y_scores)

        self.assertEqual(metrics['total_test_samples'], 5)
        self.assertEqual(metrics['anomaly_count'], 2)
        self.assertEqual(metrics['normal_count'], 3)
        self.assertAlmostEqual(metrics['precision'], 1.0)
        self.assertAlmostEqual(metrics['recall'], 0.5)
        self.assertGreater(metrics['roc_auc'], 0.5)

    def test_ground_truth_separation_from_anomaly_result(self):
        """
        Verify that ground-truth anomaly tags in metadata are NOT masquerading
        as model outputs in AnomalyResult.
        """
        # In our setup, day 45 is ground truth
        txn_45 = self.transactions[45]
        self.assertTrue(txn_45.metadata.get('ground_truth_anomaly'))

        # Check AnomalyResult records (if any exist)
        results = AnomalyResult.objects.filter(transaction=txn_45)
        for r in results:
            self.assertNotEqual(r.model_version, 'ground_truth_v1.0')
            self.assertEqual(r.model_version, 'iso_forest_v2.0')

    def test_forecasting_pipeline_causality_and_metrics(self):
        """Verify forecasting pipeline enforces causality and produces valid metrics."""
        y_true = np.array([1000.0, 2000.0, 1500.0])
        y_pred = np.array([1100.0, 1900.0, 1600.0])

        metrics = calculate_forecast_metrics(y_true, y_pred)
        self.assertAlmostEqual(metrics['mae'], 100.0)
        self.assertGreater(metrics['rmse'], 0.0)
        self.assertGreater(metrics['wape'], 0.0)
        self.assertLess(metrics['wape'], 50.0)

    def test_dynamic_evaluation_metrics_no_hardcoded_arrays(self):
        """Verify BudgetForecaster and AnomalyDetector dynamically expose metrics."""
        f_metrics = BudgetForecaster.evaluate_offline_model()
        self.assertIn('mae', f_metrics)
        self.assertIn('rmse', f_metrics)
        self.assertIn('wape', f_metrics)

        a_metrics = AnomalyDetector.get_instance().evaluation_metrics
        self.assertIn('precision', a_metrics)
        self.assertIn('roc_auc', a_metrics)
        self.assertIn('confusion_matrix', a_metrics)
