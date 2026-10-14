"""
Unit & Integration Tests for Phase 1 Trust & Risk Policy Engine and Feature Attribution.
"""
from decimal import Decimal
import tempfile
from pathlib import Path
from django.test import TestCase, override_settings
from django.utils import timezone

from fundshare_app.models import User, Wallet, Merchant, Transaction, AnomalyResult
from fundshare_app.ml.policy import RiskPolicyEngine, _simple_yaml_parse
from fundshare_app.ml.anomaly_detector import AnomalyDetector


@override_settings(GEMINI_API_KEY='')
class RiskPolicyEngineTests(TestCase):
    def setUp(self):
        self.engine = RiskPolicyEngine.get_instance()

    def test_policy_bands_evaluation(self):
        # 1. Low risk (< 0.35) -> ALLOW
        res_low = self.engine.evaluate(0.20, {})
        self.assertEqual(res_low['action'], 'ALLOW')
        self.assertEqual(res_low['risk_tier'], 'LOW')
        self.assertFalse(res_low['is_hold'])
        self.assertFalse(res_low['step_up_required'])

        # 2. Medium risk (0.35 <= score < 0.70) -> STEP_UP_PIN
        res_med = self.engine.evaluate(0.50, {})
        self.assertEqual(res_med['action'], 'STEP_UP_PIN')
        self.assertEqual(res_med['risk_tier'], 'MEDIUM')
        self.assertFalse(res_med['is_hold'])
        self.assertTrue(res_med['step_up_required'])

        # 3. High risk (>= 0.70) -> FLAG_FOR_REVIEW
        res_high = self.engine.evaluate(0.75, {})
        self.assertEqual(res_high['action'], 'FLAG_FOR_REVIEW')
        self.assertEqual(res_high['risk_tier'], 'HIGH')
        self.assertTrue(res_high['is_hold'])
        self.assertFalse(res_high['step_up_required'])

    def test_velocity_hard_rule_escalation(self):
        # Velocity > 5 txns/hr escalates ALLOW to STEP_UP_PIN
        res = self.engine.evaluate(0.10, {'txns_per_hour': 6})
        self.assertEqual(res['action'], 'STEP_UP_PIN')
        self.assertIn('VELOCITY_LIMIT_EXCEEDED', res['hard_rules_triggered'])
        self.assertTrue(res['step_up_required'])

        # Velocity > 5 txns/hr escalates STEP_UP_PIN to FLAG_FOR_REVIEW
        res_med_escalated = self.engine.evaluate(0.45, {'txns_per_hour': 7})
        self.assertEqual(res_med_escalated['action'], 'FLAG_FOR_REVIEW')
        self.assertEqual(res_med_escalated['risk_tier'], 'HIGH')
        self.assertTrue(res_med_escalated['is_hold'])

    def test_amount_spike_ratio_hard_rule(self):
        # Spike ratio > 3.5x escalates directly to FLAG_FOR_REVIEW
        res = self.engine.evaluate(0.15, {'user_ratio': 4.2})
        self.assertEqual(res['action'], 'FLAG_FOR_REVIEW')
        self.assertEqual(res['risk_tier'], 'HIGH')
        self.assertIn('AMOUNT_SPIKE_RATIO', res['hard_rules_triggered'])
        self.assertTrue(res['is_hold'])

    def test_statistical_outlier_and_off_peak_rules(self):
        res = self.engine.evaluate(0.20, {'user_zscore': 4.0, 'hour': 2})
        self.assertIn('STATISTICAL_OUTLIER', res['hard_rules_triggered'])
        self.assertIn('OFF_PEAK_HOUR', res['hard_rules_triggered'])
        self.assertEqual(res['action'], 'STEP_UP_PIN')

    def test_custom_yaml_loading_and_parser(self):
        yaml_content = """
bands:
  allow_threshold: 0.40
  step_up_threshold: 0.80
actions:
  low: PASS
  medium: CHALLENGE
  high: BLOCK
velocity_rules:
  max_txns_per_hour: 10
  amount_spike_ratio: 5.0
"""
        parsed = _simple_yaml_parse(yaml_content)
        self.assertEqual(parsed['bands']['allow_threshold'], 0.40)
        self.assertEqual(parsed['bands']['step_up_threshold'], 0.80)
        self.assertEqual(parsed['actions']['low'], 'PASS')

        with tempfile.NamedTemporaryFile('w', delete=False, suffix='.yaml', encoding='utf-8') as f:
            f.write(yaml_content)
            temp_path = f.name

        try:
            custom_engine = RiskPolicyEngine(temp_path)
            eval_res = custom_engine.evaluate(0.30)
            self.assertEqual(eval_res['action'], 'PASS')
        finally:
            Path(temp_path).unlink(missing_ok=True)


@override_settings(GEMINI_API_KEY='')
class AnomalyDetectorPolicyIntegrationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='policy-user', phone='01760000088', password='Test-password-938!')
        self.merchant_user = User.objects.create_user(username='policy-merchant', phone='01760000089', password='Test-password-938!', role='MERCHANT')
        Wallet.objects.create(owner=self.user, balance=50000)
        self.merchant = Merchant.objects.create(user=self.merchant_user, business_name='Policy Store', category='Grocery', account_number='POL-STORE')
        self.detector = AnomalyDetector.get_instance()

    def test_analyze_transaction_includes_top_contributions_and_policy(self):
        txn = Transaction.objects.create(
            sender=self.user,
            merchant=self.merchant,
            amount=15000,
            category='Grocery',
            transaction_type='MERCHANT_PAYMENT'
        )
        analysis = self.detector.analyze_transaction(txn)

        # 1. Top-3 contributing features attribution
        self.assertIn('top_contributions', analysis)
        self.assertIsInstance(analysis['top_contributions'], list)
        self.assertLessEqual(len(analysis['top_contributions']), 3)
        self.assertGreaterEqual(len(analysis['top_contributions']), 1)
        for contrib in analysis['top_contributions']:
            self.assertIn('feature', contrib)
            self.assertIn('contribution_score', contrib)
            self.assertIn('description', contrib)

        # 2. Risk Policy Engine wiring
        self.assertIn('risk_action', analysis)
        self.assertIn(analysis['risk_action'], ('ALLOW', 'STEP_UP_PIN', 'FLAG_FOR_REVIEW'))
        self.assertIn('risk_tier', analysis)
        self.assertIn(analysis['risk_tier'], ('LOW', 'MEDIUM', 'HIGH'))
        self.assertIn('policy_evaluation', analysis)

        # 3. Features summary preserves original keys and exposes new attribution
        fs = analysis['features_summary']
        self.assertIn('amount', fs)
        self.assertIn('user_historical_mean', fs)
        self.assertIn('in_training_domain', fs)
        self.assertIn('risk_action', fs)
        self.assertIn('risk_tier', fs)
        self.assertIn('top_contributions', fs)

    def test_record_transaction_persists_policy_in_anomaly_result(self):
        txn = Transaction.objects.create(
            sender=self.user,
            merchant=self.merchant,
            amount=25000,
            category='Grocery',
            transaction_type='MERCHANT_PAYMENT'
        )
        scored = AnomalyDetector.record_transaction(txn.pk)
        self.assertTrue(scored)

        result = AnomalyResult.objects.get(transaction=txn)
        self.assertIn('risk_action', result.features_summary)
        self.assertIn('top_contributions', result.features_summary)
        self.assertIsInstance(result.features_summary['top_contributions'], list)
