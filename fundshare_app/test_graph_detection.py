from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from django.contrib.auth import get_user_model

from fundshare_app.models import (
    Transaction, TransactionType, PaymentSource, TransactionStatus,
    AnomalyResult, FraudIncident, Wallet
)
from fundshare_app.ml.graph import TransactionGraphEngine
from fundshare_app.ml.anomaly_detector import AnomalyDetector

User = get_user_model()


class TransactionGraphDetectionTests(TestCase):
    def setUp(self):
        self.engine = TransactionGraphEngine.get_instance()

        # Create test users
        self.sender_a = User.objects.create_user(
            username="sender_alice",
            email="alice@fundshare.local",
            phone="01711100001",
            role="CUSTOMER"
        )
        self.sender_b = User.objects.create_user(
            username="sender_bob",
            email="bob@fundshare.local",
            phone="01711100002",
            role="CUSTOMER"
        )
        self.sender_c = User.objects.create_user(
            username="sender_charlie",
            email="charlie@fundshare.local",
            phone="01711100003",
            role="CUSTOMER"
        )
        self.mule_hub = User.objects.create_user(
            username="mule_hub_user",
            email="mule@fundshare.local",
            phone="01711100004",
            role="CUSTOMER"
        )
        self.cashout_dest = User.objects.create_user(
            username="cashout_dest_user",
            email="dest@fundshare.local",
            phone="01711100005",
            role="CUSTOMER"
        )

        # Wallets
        for u in [self.sender_a, self.sender_b, self.sender_c, self.mule_hub, self.cashout_dest]:
            Wallet.objects.create(owner=u, balance=Decimal("20000.00"), is_frozen=False)

    def test_normal_transfer_no_mule_flag(self):
        """Single transfer produces no mule alert, 0 in-degree fan-in anomaly, and 0.0 boost."""
        txn = Transaction.objects.create(
            sender=self.sender_a,
            receiver=self.mule_hub,
            amount=Decimal("1500.00"),
            transaction_type=TransactionType.SEND_MONEY,
            payment_source=PaymentSource.NORMAL_WALLET,
            status=TransactionStatus.COMPLETED
        )

        res = self.engine.analyze_account_risk(self.mule_hub, lookback_hours=24, rebuild=True)

        self.assertFalse(res['is_mule_suspect'])
        self.assertEqual(res['mule_boost'], 0.0)
        self.assertEqual(len(res['reasons']), 0)
        self.assertEqual(res['graph_metrics']['in_degree'], 1)
        self.assertEqual(res['graph_metrics']['distinct_senders'], 1)
        self.assertEqual(res['graph_metrics']['total_fan_in_volume'], 1500.00)

    def test_fan_in_pattern_triggers_mule_flag_and_boost(self):
        """3 distinct senders sending to 1 recipient triggers in-degree >= 3 and +0.25 mule boost."""
        # Create transfers from 3 distinct senders into mule_hub
        Transaction.objects.create(
            sender=self.sender_a,
            receiver=self.mule_hub,
            amount=Decimal("5000.00"),
            transaction_type=TransactionType.SEND_MONEY,
            payment_source=PaymentSource.NORMAL_WALLET,
            status=TransactionStatus.COMPLETED
        )
        Transaction.objects.create(
            sender=self.sender_b,
            receiver=self.mule_hub,
            amount=Decimal("6000.00"),
            transaction_type=TransactionType.SEND_MONEY,
            payment_source=PaymentSource.NORMAL_WALLET,
            status=TransactionStatus.COMPLETED
        )
        Transaction.objects.create(
            sender=self.sender_c,
            receiver=self.mule_hub,
            amount=Decimal("7000.00"),
            transaction_type=TransactionType.SEND_MONEY,
            payment_source=PaymentSource.NORMAL_WALLET,
            status=TransactionStatus.COMPLETED
        )

        # Inflow aggregation analysis
        res = self.engine.analyze_account_risk(self.mule_hub, lookback_hours=24, rebuild=True)

        self.assertTrue(res['is_mule_suspect'])
        self.assertEqual(res['mule_boost'], 0.25)
        self.assertEqual(res['graph_metrics']['in_degree'], 3)
        self.assertEqual(res['graph_metrics']['total_fan_in_volume'], 18000.00)
        self.assertTrue(any("High fan-in: 3 distinct senders" in r for r in res['reasons']))

        # 2-hop pass-through with rapid outflow
        res_outflow = self.engine.analyze_account_risk(
            self.mule_hub,
            current_amount=Decimal("17000.00"),
            lookback_hours=24,
            rebuild=False
        )
        self.assertTrue(res_outflow['is_mule_suspect'])
        self.assertEqual(res_outflow['mule_boost'], 0.25)
        self.assertTrue(any("2-hop mule ring pattern" in r for r in res_outflow['reasons']))

    def test_anomaly_detector_integration_triggers_fraud_incident_on_mule_pattern(self):
        """End-to-end integration: 3 senders aggregate into mule_hub, then mule_hub sends funds."""
        # 3 aggregated incoming transfers
        Transaction.objects.create(
            sender=self.sender_a,
            receiver=self.mule_hub,
            amount=Decimal("10000.00"),
            transaction_type=TransactionType.SEND_MONEY,
            payment_source=PaymentSource.NORMAL_WALLET,
            status=TransactionStatus.COMPLETED
        )
        Transaction.objects.create(
            sender=self.sender_b,
            receiver=self.mule_hub,
            amount=Decimal("12000.00"),
            transaction_type=TransactionType.SEND_MONEY,
            payment_source=PaymentSource.NORMAL_WALLET,
            status=TransactionStatus.COMPLETED
        )
        Transaction.objects.create(
            sender=self.sender_c,
            receiver=self.mule_hub,
            amount=Decimal("15000.00"),
            transaction_type=TransactionType.SEND_MONEY,
            payment_source=PaymentSource.NORMAL_WALLET,
            status=TransactionStatus.COMPLETED
        )

        # Mule hub initiates outgoing cashout transfer
        outflow_txn = Transaction.objects.create(
            sender=self.mule_hub,
            receiver=self.cashout_dest,
            amount=Decimal("35000.00"),
            transaction_type=TransactionType.SEND_MONEY,
            payment_source=PaymentSource.NORMAL_WALLET,
            status=TransactionStatus.COMPLETED
        )

        detector = AnomalyDetector.get_instance()
        analysis = detector.analyze_transaction(outflow_txn)

        # Graph engine detects mule suspect on sender and adds +0.25 boost
        self.assertTrue(analysis['is_mule_suspect'])
        self.assertEqual(analysis['mule_boost'], 0.25)
        self.assertGreaterEqual(analysis['anomaly_score'], 0.25)
        self.assertIn("GRAPH_MULE_RING", analysis['rules_flagged'])
        self.assertTrue(any("2-hop mule ring pattern" in r for r in analysis['features_summary']['graph_reasons']))

        # Top contributions contains networkx_mule_ring
        feat_names = [tc.get('feature') for tc in analysis['top_contributions']]
        self.assertIn("networkx_mule_ring", feat_names)

        # Run record_transaction to ensure FraudIncident is created
        success = AnomalyDetector.record_transaction(outflow_txn.pk, force=True)
        self.assertTrue(success)

        # Verify FraudIncident was generated with status PENDING and mule reasons
        incident = FraudIncident.objects.filter(transaction=outflow_txn).first()
        self.assertIsNotNone(incident)
        self.assertEqual(incident.status, "PENDING")
        self.assertTrue(any("mule" in str(r).lower() for r in incident.reasons))

        # Resolving incident as CONFIRMED_FRAUD freezes mule hub wallet
        incident.resolve(status="CONFIRMED_FRAUD", notes="Confirmed 2-hop money mule cashout")
        self.mule_hub.wallet.refresh_from_db()
        self.assertTrue(self.mule_hub.wallet.is_frozen)
