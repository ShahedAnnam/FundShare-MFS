import json
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

import joblib
import numpy as np
import pandas as pd
from django.core.management import call_command
from django.db import transaction
from django.test import TestCase, SimpleTestCase, override_settings
from django.utils import timezone

from fundshare_app.ml.anomaly_detector import (
    AnomalyDetector, DATASET, ARTIFACT, INPUT_FIELDS, feature_records, transaction_features,
)
from fundshare_app.ml.ai_coach import FinancialAIService
from fundshare_app.ml.privacy import strip_ml_details
from fundshare_app.ml.support_context import get_support_context
from fundshare_app.models import AnomalyResult, Transaction, User, Wallet, Merchant, Notification, AIInsight, FinancialRequest
from fundshare_app.serializers.api_serializers import TransactionSerializer
from fundshare_app.services.report_service import ReportService


class ModelTrainingTests(SimpleTestCase):
    def test_saved_model_has_real_held_out_metrics_and_explicit_inputs(self):
        bundle = joblib.load(ARTIFACT)
        metadata = bundle['metadata']
        self.assertEqual((metadata['sample_size'], metadata['train_size'], metadata['test_size']), (480, 336, 144))
        self.assertEqual(sum(map(sum, metadata['confusion_matrix'])), 144)
        self.assertLess(metadata['training_end'], metadata['test_start'])
        self.assertEqual(metadata['training_transaction_types'], ['MERCHANT_PAYMENT'])
        for prohibited in ('anomaly_label', 'anomaly_type', 'user_id', 'transaction_id', 'merchant_id'):
            self.assertNotIn(prohibited, INPUT_FIELDS)
            self.assertFalse(any(prohibited in name for name in bundle['vectorizer'].feature_names_))

    def test_changing_labels_does_not_change_fit_and_zero_metrics_are_not_replaced(self):
        frame = pd.read_csv(DATASET)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            original = path / 'original.joblib'
            changed = path / 'changed.joblib'
            AnomalyDetector.train(DATASET, original)
            frame['anomaly_label'] = 0
            frame['anomaly_type'] = 'DO_NOT_TRAIN_ON_THIS'
            frame.to_csv(path / 'changed.csv', index=False)
            metadata = AnomalyDetector.train(path / 'changed.csv', changed)
            a, b = joblib.load(original), joblib.load(changed)
            records = feature_records(frame.to_dict('records'))
            xa, xb = a['vectorizer'].transform(records), b['vectorizer'].transform(records)
            np.testing.assert_array_equal(xa, xb)
            np.testing.assert_array_equal(a['model'].decision_function(xa), b['model'].decision_function(xb))
            self.assertEqual(metadata['precision'], 0)
            self.assertEqual(metadata['recall'], 0)
            self.assertEqual(metadata['f1'], 0)
            self.assertIsNone(metadata['roc_auc'])

    def test_no_identifier_or_label_fields_enter_feature_extraction(self):
        row = pd.read_csv(DATASET).iloc[0].to_dict()
        baseline = feature_records([row])
        row.update(anomaly_label=0, anomaly_type='changed', user_id='different', transaction_id='different')
        self.assertEqual(baseline, feature_records([row]))


@override_settings(GEMINI_API_KEY='')
class AnomalyIntegrationTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(username='ml-customer', phone='01760000001', password='Test-password-938!')
        self.admin = User.objects.create_user(username='ml-admin', phone='01760000002', password='Test-password-938!', role='ADMIN', is_staff=True)
        self.merchant_user = User.objects.create_user(username='ml-merchant', phone='01760000003', password='Test-password-938!', role='MERCHANT')
        self.customer.set_transaction_pin('482951')
        self.customer.save(update_fields=['transaction_pin'])
        Wallet.objects.create(owner=self.customer, balance=1000)
        self.merchant = Merchant.objects.create(user=self.merchant_user, business_name='ML Grocery', category='Grocery', account_number='ML-GROCERY')
        self.client.force_login(self.customer)
        self.txn = Transaction.objects.create(sender=self.customer, merchant=self.merchant, amount=25, category='Grocery', transaction_type='MERCHANT_PAYMENT',
                                              metadata={'ground_truth_anomaly': True, 'anomaly_type': 'HIGH_AMOUNT', 'provider': 'preserved'})
        AnomalyDetector.record_transaction(self.txn.pk)

    def test_each_transaction_type_is_scored_only_after_commit(self):
        from fundshare_app.models import TransactionType
        for kind in TransactionType.values:
            with self.captureOnCommitCallbacks(execute=True):
                txn = Transaction.objects.create(sender=self.customer, amount=10, transaction_type=kind)
                self.assertFalse(AnomalyResult.objects.filter(transaction=txn).exists())
            result = AnomalyResult.objects.get(transaction=txn)
            self.assertIn(result.prediction, (0, 1))
            self.assertGreaterEqual(result.anomaly_score, 0)
            self.assertLessEqual(result.anomaly_score, 1)
            self.assertFalse(result.features_summary['in_training_domain'] if kind != 'MERCHANT_PAYMENT' else False)

    def test_rollback_does_not_score(self):
        with patch.object(AnomalyDetector, 'record_transaction') as score:
            with self.captureOnCommitCallbacks(execute=True):
                with transaction.atomic():
                    Transaction.objects.create(sender=self.customer, amount=12, transaction_type='SEND_MONEY')
                    transaction.set_rollback(True)
            score.assert_not_called()

    def test_causal_history_ignores_current_future_and_rejected_transactions(self):
        start = timezone.now() - timezone.timedelta(days=1)
        previous = Transaction.objects.create(sender=self.customer, amount=40, category='Grocery', transaction_type='MERCHANT_PAYMENT', timestamp=start)
        current = Transaction.objects.create(sender=self.customer, amount=80, category='Grocery', transaction_type='MERCHANT_PAYMENT', timestamp=start + timezone.timedelta(minutes=5))
        Transaction.objects.create(sender=self.customer, amount=9000, category='Grocery', transaction_type='MERCHANT_PAYMENT', timestamp=start + timezone.timedelta(minutes=10))
        Transaction.objects.create(sender=self.customer, amount=7000, category='Grocery', transaction_type='MERCHANT_PAYMENT', timestamp=start - timezone.timedelta(minutes=1), status='REJECTED')
        fields = transaction_features(current)
        self.assertEqual(fields['prior_txn_count'], 1)
        self.assertEqual(fields['user_avg_amount_prior'], 40)
        self.assertEqual(fields['category_avg_amount_prior'], 40)
        self.assertEqual(fields['rolling_7d_spend_prior'], 40)
        self.assertEqual(fields['minutes_since_prev_txn'], 5)

    def test_loaded_model_round_trip_produces_identical_predictions(self):
        a = AnomalyDetector().analyze_transaction(self.txn)
        b = AnomalyDetector().analyze_transaction(self.txn)
        self.assertEqual(a, b)
        self.assertIn(a['is_anomaly'], (True, False))

    def test_model_unavailable_does_not_undo_payment(self):
        unavailable = AnomalyDetector(Path(tempfile.gettempdir()) / f'missing-{uuid.uuid4()}.joblib')
        with patch.object(AnomalyDetector, 'get_instance', return_value=unavailable), self.assertLogs('fundshare_app.ml.anomaly_detector', level='ERROR'):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post('/api/pay/', {'merchant_id': self.merchant.pk, 'amount': '20', 'pin': '482951'},
                                            content_type='application/json', HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))
            self.assertEqual(response.status_code, 200)
        self.assertEqual(Wallet.objects.get(owner=self.customer).balance, 980)
        self.assertEqual(self.client.get('/api/admin/ml/transactions/').status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get('/api/admin/ml/transactions/?prediction=unscored').json()['count'], 1)

    def test_pin_failure_and_idempotent_retry_preserve_one_payment_and_prediction(self):
        payload = {'merchant_id': self.merchant.pk, 'amount': '20', 'pin': '482951'}
        key = str(uuid.uuid4())
        with self.captureOnCommitCallbacks(execute=True):
            bad = self.client.post('/api/pay/', {**payload, 'pin': '999999'}, content_type='application/json', HTTP_IDEMPOTENCY_KEY=key)
            self.assertEqual(bad.status_code, 403)
            response = self.client.post('/api/pay/', payload, content_type='application/json', HTTP_IDEMPOTENCY_KEY=key)
        self.assertEqual(response.status_code, 200)
        before = AnomalyResult.objects.count()
        cached = FinancialRequest.objects.get(user=self.customer, key=key)
        cached.response.update(has_anomaly=True, anomaly_reason='PRIVATE MODEL REASON')
        cached.save(update_fields=['response'])
        retry = self.client.post('/api/pay/', payload, content_type='application/json', HTTP_IDEMPOTENCY_KEY=key)
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(retry['Idempotency-Replayed'], 'true')
        self.assertNotIn('has_anomaly', retry.json())
        self.assertNotContains(retry, 'PRIVATE MODEL REASON')
        self.assertEqual(AnomalyResult.objects.count(), before)
        self.assertEqual(Wallet.objects.get(owner=self.customer).balance, 980)

    def test_admin_only_endpoints_reject_customer_merchant_and_staff_customer(self):
        self.customer.is_staff = True
        self.customer.save(update_fields=['is_staff'])
        for user in (self.customer, self.merchant_user):
            self.client.force_login(user)
            for path in ('/api/admin/ml/transactions/', '/api/evaluation/metrics/', '/api/intelligence/dashboard/'):
                self.assertEqual(self.client.get(path, {'role': 'ADMIN'}).status_code, 403)
            self.assertNotContains(self.client.get('/'), 'id="evalSection"')
            self.assertNotContains(self.client.get('/'), 'ml-report.js')
        self.client.logout()
        self.assertEqual(self.client.get('/api/admin/ml/transactions/').status_code, 401)

    def test_admin_report_contains_details_predictions_and_evaluation(self):
        self.client.force_login(self.admin)
        response = self.client.get('/api/admin/ml/transactions/')
        self.assertEqual(response.status_code, 200)
        row = response.json()['results'][0]
        self.assertEqual(row['transaction']['transaction_id'], str(self.txn.transaction_id))
        self.assertIn(row['prediction'], (0, 1))
        self.assertIn('anomaly_score', row['analysis'])
        self.assertEqual(response.json()['model']['test_size'], 144)
        self.assertContains(self.client.get('/'), 'id="evalSection"')

    def test_filters_pagination_and_stale_model_are_explicit(self):
        self.client.force_login(self.admin)
        for i in range(21):
            Transaction.objects.create(sender=self.customer, amount=10, transaction_type='SEND_MONEY')
        response = self.client.get('/api/admin/ml/transactions/').json()
        self.assertEqual(len(response['results']), 20)
        self.assertTrue(response['next'])
        self.assertEqual(response['summary']['unscored'], 21)
        self.assertEqual(self.client.get('/api/admin/ml/transactions/?prediction=unscored&type=SEND_MONEY').json()['count'], 21)
        self.assertEqual(self.client.get('/api/admin/ml/transactions/?search=not-a-real-id').json()['count'], 0)
        self.assertEqual(self.client.get('/api/admin/ml/transactions/?prediction=invalid').status_code, 400)
        self.assertEqual(self.client.get('/api/admin/ml/transactions/?type=invalid').status_code, 400)
        self.assertEqual(self.client.get('/api/admin/ml/transactions/?page=999').status_code, 404)
        AnomalyResult.objects.filter(transaction=self.txn).update(model_version='obsolete')
        self.assertEqual(self.client.get('/api/admin/ml/transactions/?prediction=unscored').json()['count'], 22)

    def test_public_ledger_report_notifications_and_chat_do_not_leak_ml(self):
        public = TransactionSerializer(self.txn).data
        self.assertEqual(public['metadata'], {'provider': 'preserved'})
        self.assertNotIn('has_anomaly', public)
        self.assertNotIn('anomalies', ReportService.generate_report(self.customer))
        AIInsight.objects.create(user=self.customer, insight_type='ANOMALY', title='Secret model finding', description='Private')
        notif = Notification.objects.create(user=self.customer, notification_type='ANOMALY_ALERT', title='Secret model finding', message='Private')
        self.assertEqual(self.client.get('/api/notifications/').json(), [])
        self.assertEqual(self.client.post(f'/api/notifications/{notif.pk}/read/').status_code, 404)
        context = get_support_context(self.customer)
        self.assertNotIn('unusual_activity', context)
        self.assertNotIn('ANOMALY', context['insight_types'])
        self.assertNotIn('anomalies', FinancialAIService.get_user_financial_context(self.customer))
        with patch.object(FinancialAIService, 'generate_online_response') as online:
            answer = FinancialAIService.answer_query(self.customer, 'Explain unusual flagged transactions')
            self.assertIn('ADMIN', answer['answer'])
            online.assert_not_called()
        self.assertNotContains(self.client.get('/'), 'Explain unusual flagged transactions')
        self.assertNotEqual(self.client.get('/model/artifacts/evaluation.json').status_code, 200)

    def test_backfill_preserves_ledger_and_balances(self):
        before = list(Transaction.objects.values())
        wallets = list(Wallet.objects.values())
        with patch.object(AnomalyDetector, 'record_transaction', wraps=AnomalyDetector.record_transaction):
            call_command('backfill_anomaly_predictions', force=True, verbosity=0)
        self.assertEqual(before, list(Transaction.objects.values()))
        self.assertEqual(wallets, list(Wallet.objects.values()))
        self.assertEqual(AnomalyResult.objects.count(), Transaction.objects.count())

    def test_account_deletion_keeps_transaction_prediction(self):
        result = AnomalyResult.objects.get(transaction=self.txn)
        self.customer.delete()
        result.refresh_from_db()
        self.assertIsNone(result.user_id)
        self.assertTrue(Transaction.objects.filter(pk=self.txn.pk).exists())

    def test_recursive_redaction_preserves_business_fields(self):
        self.assertEqual(strip_ml_details({'transaction': {'metadata': {'ground_truth_anomaly': True, 'provider': 'Telco'}}, 'amount': '10'}),
                         {'transaction': {'metadata': {'provider': 'Telco'}}, 'amount': '10'})
