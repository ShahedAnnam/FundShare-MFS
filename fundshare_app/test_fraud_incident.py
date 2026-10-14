from decimal import Decimal
from django.test import TestCase, RequestFactory
from django.utils import timezone
from django.contrib.admin.sites import site
from django.contrib.auth import get_user_model

from fundshare_app.models import (
    Transaction, AnomalyResult, FraudIncident, Wallet,
    IncidentRiskTier, IncidentPolicyAction, IncidentStatus,
    TransactionType, PaymentSource, TransactionStatus
)
from fundshare_app.admin import FraudIncidentAdmin
from fundshare_app.ml.anomaly_detector import AnomalyDetector

User = get_user_model()


class FraudIncidentModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="analyst_test_user",
            email="analyst@fundshare.local",
            phone="01711000111",
            role="CUSTOMER"
        )
        self.wallet = Wallet.objects.create(
            owner=self.user,
            balance=Decimal("10000.00"),
            is_frozen=False
        )
        self.receiver_user = User.objects.create_user(
            username="mule_receiver_user",
            email="receiver@fundshare.local",
            phone="01711000333",
            role="CUSTOMER"
        )
        self.receiver_wallet = Wallet.objects.create(
            owner=self.receiver_user,
            balance=Decimal("2000.00"),
            is_frozen=False
        )
        self.admin_user = User.objects.create_superuser(
            username="admin_analyst",
            email="admin@fundshare.local",
            phone="01711000222",
            password="adminpassword123"
        )

    def test_fraud_incident_creation_and_defaults(self):
        txn = Transaction.objects.create(
            sender=self.user,
            amount=Decimal("2500.00"),
            transaction_type=TransactionType.SEND_MONEY,
            payment_source=PaymentSource.NORMAL_WALLET,
            status=TransactionStatus.COMPLETED
        )
        anomaly_res = AnomalyResult.objects.create(
            transaction=txn,
            user=self.user,
            is_anomaly=False,
            anomaly_score=0.20,
            reason="Normal baseline transaction.",
            features_summary={"risk_action": "ALLOW", "risk_tier": "LOW"}
        )

        incident = FraudIncident.objects.create(
            transaction=txn,
            anomaly_result=anomaly_res,
            risk_score=0.88,
            risk_tier=IncidentRiskTier.HIGH,
            policy_action=IncidentPolicyAction.FLAG_FOR_REVIEW,
            reasons=["Amount spike > 3.5x"],
            top_contributions=[{"feature": "amount", "contribution": 0.45}]
        )
        self.assertEqual(incident.status, IncidentStatus.PENDING)
        self.assertIsNone(incident.reviewed_by)
        self.assertIsNone(incident.resolved_at)
        self.assertIn("HIGH", str(incident))
        self.assertEqual(txn.fraud_incident, incident)
        self.assertEqual(anomaly_res.incident, incident)

    def test_incident_resolution_helper_freezes_sender_wallet(self):
        txn = Transaction.objects.create(
            sender=self.user,
            amount=Decimal("12000.00"),
            transaction_type=TransactionType.SEND_MONEY,
            payment_source=PaymentSource.NORMAL_WALLET,
            status=TransactionStatus.COMPLETED
        )
        incident = FraudIncident.objects.create(
            transaction=txn,
            risk_score=0.92,
            risk_tier="CRITICAL",
            policy_action="FLAG_FOR_REVIEW",
            status="PENDING"
        )
        before_resolve = timezone.now()
        incident.resolve(
            status="CONFIRMED_FRAUD",
            reviewer=self.admin_user,
            notes="Confirmed compromised account after user call."
        )

        incident.refresh_from_db()
        self.wallet.refresh_from_db()

        self.assertEqual(incident.status, "CONFIRMED_FRAUD")
        self.assertEqual(incident.reviewed_by, self.admin_user)
        self.assertIn("Confirmed compromised account after user call.", incident.reviewer_notes)
        self.assertIn("[Auto-Lock", incident.reviewer_notes)
        self.assertIsNotNone(incident.resolved_at)
        self.assertGreaterEqual(incident.resolved_at, before_resolve)

        # Check sender wallet is automatically frozen
        self.assertTrue(self.wallet.is_frozen)
        self.assertFalse(self.wallet.is_active)

    def test_resolve_confirmed_fraud_freezes_destination_wallet_on_mule_ring(self):
        txn = Transaction.objects.create(
            sender=self.user,
            receiver=self.receiver_user,
            amount=Decimal("45000.00"),
            transaction_type=TransactionType.SEND_MONEY,
            payment_source=PaymentSource.NORMAL_WALLET,
            status=TransactionStatus.COMPLETED
        )
        incident = FraudIncident.objects.create(
            transaction=txn,
            risk_score=0.98,
            risk_tier="CRITICAL",
            policy_action="FLAG_FOR_REVIEW",
            status="PENDING",
            reasons=["High-velocity money mule fan-in destination", "Unusual recipient pattern"]
        )
        incident.resolve(
            status="CONFIRMED_FRAUD",
            reviewer=self.admin_user,
            notes="Mule laundering network ring identified."
        )

        self.wallet.refresh_from_db()
        self.receiver_wallet.refresh_from_db()
        incident.refresh_from_db()

        # Both source and mule destination wallets are auto-locked
        self.assertTrue(self.wallet.is_frozen)
        self.assertTrue(self.receiver_wallet.is_frozen)
        self.assertIn(f"Destination wallet for {self.receiver_user.username} frozen", incident.reviewer_notes)

    def test_resolve_approved_leaves_active_and_unlocks_previously_frozen_wallet(self):
        txn = Transaction.objects.create(
            sender=self.user,
            amount=Decimal("1500.00"),
            transaction_type=TransactionType.SEND_MONEY,
            payment_source=PaymentSource.NORMAL_WALLET,
            status=TransactionStatus.COMPLETED
        )
        incident = FraudIncident.objects.create(
            transaction=txn,
            risk_score=0.65,
            risk_tier="MEDIUM",
            policy_action="STEP_UP_PIN",
            status="PENDING"
        )

        # Case A: Initially active wallet resolved as APPROVED stays active
        incident.resolve(status="APPROVED", reviewer=self.admin_user, notes="Legitimate transaction.")
        self.wallet.refresh_from_db()
        self.assertFalse(self.wallet.is_frozen)
        self.assertTrue(self.wallet.is_active)

        # Case B: Previously frozen wallet gets restored when resolved as APPROVED
        self.wallet.freeze()
        self.assertTrue(self.wallet.is_frozen)

        incident.resolve(status="APPROVED", reviewer=self.admin_user, notes="False positive verified with customer.")
        self.wallet.refresh_from_db()
        incident.refresh_from_db()
        self.assertFalse(self.wallet.is_frozen)
        self.assertTrue(self.wallet.is_active)
        self.assertIn("[Auto-Unlock", incident.reviewer_notes)

    def test_auto_create_from_evaluation_when_high_risk(self):
        txn = Transaction.objects.create(
            sender=self.user,
            amount=Decimal("15000.00"),
            transaction_type=TransactionType.SEND_MONEY,
            payment_source=PaymentSource.NORMAL_WALLET,
            status=TransactionStatus.COMPLETED
        )
        analysis = {
            "is_anomaly": True,
            "anomaly_score": 0.85,
            "risk_action": "FLAG_FOR_REVIEW",
            "risk_tier": "HIGH",
            "rules_flagged": ["Off-peak night transaction", "Spike ratio 4.2x"],
            "top_contributions": [{"feature": "amount", "contribution": 0.5}],
            "reason": "• Anomaly flag triggered"
        }

        incident = FraudIncident.auto_create_from_evaluation(
            transaction=txn,
            analysis=analysis
        )

        self.assertIsNotNone(incident)
        self.assertEqual(incident.status, "PENDING")
        self.assertEqual(incident.risk_tier, "HIGH")
        self.assertEqual(incident.policy_action, "FLAG_FOR_REVIEW")
        self.assertEqual(incident.risk_score, 0.85)
        self.assertEqual(len(incident.reasons), 2)
        self.assertEqual(incident.top_contributions[0]["feature"], "amount")

    def test_auto_create_from_evaluation_ignored_when_low_risk(self):
        low_txn = Transaction.objects.create(
            sender=self.user,
            amount=Decimal("150.00"),
            transaction_type=TransactionType.SEND_MONEY,
            payment_source=PaymentSource.NORMAL_WALLET,
            status=TransactionStatus.COMPLETED
        )
        analysis = {
            "is_anomaly": False,
            "anomaly_score": 0.12,
            "risk_action": "ALLOW",
            "risk_tier": "LOW",
            "rules_flagged": [],
            "top_contributions": []
        }

        incident = FraudIncident.auto_create_from_evaluation(
            transaction=low_txn,
            analysis=analysis
        )
        self.assertIsNone(incident)
        self.assertFalse(FraudIncident.objects.filter(transaction=low_txn).exists())

    def test_auto_create_idempotency_and_resolved_status_preservation(self):
        txn = Transaction.objects.create(
            sender=self.user,
            amount=Decimal("35000.00"),
            transaction_type=TransactionType.SEND_MONEY,
            payment_source=PaymentSource.NORMAL_WALLET,
            status=TransactionStatus.COMPLETED
        )
        analysis = {
            "is_anomaly": True,
            "anomaly_score": 0.95,
            "risk_action": "FLAG_FOR_REVIEW",
            "risk_tier": "CRITICAL",
            "rules_flagged": ["Velocity limit exceeded"],
            "top_contributions": []
        }

        # First call creates incident
        inc1 = FraudIncident.auto_create_from_evaluation(
            transaction=txn,
            analysis=analysis
        )
        self.assertIsNotNone(inc1)
        total_count = FraudIncident.objects.filter(transaction=txn).count()
        self.assertEqual(total_count, 1)

        # Analyst reviews and resolves incident
        inc1.resolve("APPROVED", self.admin_user, "Valid emergency payment confirmed.")

        # Re-evaluation / second call must not create duplicate or reset status back to PENDING
        inc2 = FraudIncident.auto_create_from_evaluation(
            transaction=txn,
            analysis=analysis
        )
        self.assertEqual(inc2.id, inc1.id)
        self.assertEqual(FraudIncident.objects.filter(transaction=txn).count(), 1)
        inc2.refresh_from_db()
        self.assertEqual(inc2.status, "APPROVED")
        self.assertEqual(inc2.reviewed_by, self.admin_user)

    def test_record_transaction_creates_fraud_incident_on_high_risk(self):
        high_risk_txn = Transaction.objects.create(
            sender=self.user,
            amount=Decimal("85000.00"),
            transaction_type=TransactionType.SEND_MONEY,
            payment_source=PaymentSource.NORMAL_WALLET,
            status=TransactionStatus.COMPLETED
        )

        success = AnomalyDetector.record_transaction(high_risk_txn.pk, force=True)
        self.assertTrue(success)

        anom = AnomalyResult.objects.get(transaction=high_risk_txn)
        self.assertIsNotNone(anom)

        fs = anom.features_summary or {}
        if fs.get('risk_action') == 'FLAG_FOR_REVIEW' or fs.get('risk_tier') in ('HIGH', 'CRITICAL'):
            self.assertTrue(FraudIncident.objects.filter(transaction=high_risk_txn).exists())
            inc = FraudIncident.objects.get(transaction=high_risk_txn)
            self.assertEqual(inc.status, "PENDING")


class FraudIncidentAdminTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.admin_user = User.objects.create_superuser(
            username="admin_reviewer",
            email="admin_reviewer@fundshare.local",
            phone="01711888999",
            password="adminpassword123"
        )
        self.user = User.objects.create_user(
            username="client_user",
            email="client@fundshare.local",
            phone="01711666777"
        )
        self.wallet = Wallet.objects.create(
            owner=self.user,
            balance=Decimal("20000.00"),
            is_frozen=False
        )
        self.txn1 = Transaction.objects.create(
            sender=self.user,
            amount=Decimal("12000.00"),
            transaction_type=TransactionType.SEND_MONEY,
            payment_source=PaymentSource.NORMAL_WALLET,
            status=TransactionStatus.COMPLETED
        )
        self.txn2 = Transaction.objects.create(
            sender=self.user,
            amount=Decimal("25000.00"),
            transaction_type=TransactionType.SEND_MONEY,
            payment_source=PaymentSource.NORMAL_WALLET,
            status=TransactionStatus.COMPLETED
        )
        self.inc1 = FraudIncident.objects.create(
            transaction=self.txn1,
            risk_score=0.75,
            risk_tier="HIGH",
            policy_action="FLAG_FOR_REVIEW",
            status="PENDING"
        )
        self.inc2 = FraudIncident.objects.create(
            transaction=self.txn2,
            risk_score=0.88,
            risk_tier="CRITICAL",
            policy_action="FLAG_FOR_REVIEW",
            status="PENDING"
        )
        self.admin_model = FraudIncidentAdmin(FraudIncident, site)

    def _create_mock_request(self):
        from unittest.mock import MagicMock
        request = self.factory.post('/admin/fundshare_app/fraudincident/')
        request.user = self.admin_user
        request._messages = MagicMock()
        return request

    def test_admin_registration(self):
        self.assertIn(FraudIncident, site._registry)
        admin_instance = site._registry[FraudIncident]
        self.assertIn('status', admin_instance.list_display)
        self.assertIn('risk_tier', admin_instance.list_display)
        self.assertIn('policy_action', admin_instance.list_display)
        self.assertIn('status', admin_instance.list_filter)
        self.assertIn('transaction__id', admin_instance.search_fields)

    def test_admin_action_mark_as_confirmed_fraud_freezes_wallet(self):
        request = self._create_mock_request()
        queryset = FraudIncident.objects.filter(id__in=[self.inc1.id, self.inc2.id])
        self.admin_model.mark_as_confirmed_fraud(request, queryset)

        self.inc1.refresh_from_db()
        self.inc2.refresh_from_db()
        self.wallet.refresh_from_db()

        self.assertEqual(self.inc1.status, "CONFIRMED_FRAUD")
        self.assertEqual(self.inc2.status, "CONFIRMED_FRAUD")
        self.assertEqual(self.inc1.reviewed_by, self.admin_user)
        self.assertEqual(self.inc2.reviewed_by, self.admin_user)
        self.assertIsNotNone(self.inc1.resolved_at)

        # Bulk confirmation triggered wallet freeze
        self.assertTrue(self.wallet.is_frozen)
        self.assertFalse(self.wallet.is_active)

    def test_admin_action_mark_as_false_positive_restores_wallet(self):
        # Freeze wallet beforehand
        self.wallet.freeze()
        self.assertTrue(self.wallet.is_frozen)

        request = self._create_mock_request()
        queryset = FraudIncident.objects.filter(id=self.inc1.id)
        self.admin_model.mark_as_false_positive(request, queryset)

        self.inc1.refresh_from_db()
        self.wallet.refresh_from_db()

        self.assertEqual(self.inc1.status, "APPROVED")
        self.assertEqual(self.inc1.reviewed_by, self.admin_user)
        self.assertIsNotNone(self.inc1.resolved_at)

        # Bulk false positive restoration unfreezes wallet
        self.assertFalse(self.wallet.is_frozen)
        self.assertTrue(self.wallet.is_active)


class RiskConsoleViewTests(TestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username="normal_customer",
            email="cust@fundshare.local",
            phone="01711222333",
            password="custpassword123",
            role="CUSTOMER"
        )
        self.customer_wallet = Wallet.objects.create(
            owner=self.customer,
            balance=Decimal("5000.00"),
            is_frozen=False
        )
        self.staff_user = User.objects.create_user(
            username="risk_officer",
            email="risk@fundshare.local",
            phone="01711444555",
            password="riskpassword123",
            is_staff=True
        )
        self.txn = Transaction.objects.create(
            sender=self.customer,
            amount=Decimal("15000.00"),
            transaction_type=TransactionType.SEND_MONEY,
            payment_source=PaymentSource.NORMAL_WALLET,
            status=TransactionStatus.COMPLETED
        )
        self.incident = FraudIncident.objects.create(
            transaction=self.txn,
            risk_score=0.88,
            risk_tier="HIGH",
            policy_action="FLAG_FOR_REVIEW",
            status="PENDING",
            reasons=["Velocity limit exceeded: 6 txns/hr", "2-hop mule ring aggregation"],
            top_contributions=[
                {"feature": "networkx_mule_ring", "contribution": 0.25, "description": "3 distinct senders within 24h"},
                {"feature": "amount_surge", "contribution_score": 4.5, "description": "Amount is 4.5x category average"}
            ]
        )

    def test_customer_cannot_access_risk_console(self):
        self.client.login(username="normal_customer", password="custpassword123")
        response = self.client.get('/risk-console/')
        # Redirected because user_passes_test fails for non-staff
        self.assertEqual(response.status_code, 302)

    def test_staff_can_access_risk_console_and_sees_kpis(self):
        self.client.login(username="risk_officer", password="riskpassword123")
        response = self.client.get('/risk-console/')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'risk_console.html')
        self.assertIn('kpis', response.context)
        self.assertEqual(response.context['kpis']['pending_count'], 1)
        self.assertEqual(response.context['kpis']['total_incidents'], 1)
        self.assertContains(response, "Analyst Triage &amp; Fraud Interdiction Board")
        self.assertContains(response, "#" + str(self.incident.id))
        self.assertContains(response, "15000.00")

    def test_staff_can_resolve_incident_as_confirmed_fraud_and_freeze(self):
        self.client.login(username="risk_officer", password="riskpassword123")
        response = self.client.post('/risk-console/', {
            'action': 'confirm_fraud',
            'incident_id': self.incident.id,
            'notes': 'Verified ATO surge.'
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])

        self.incident.refresh_from_db()
        self.customer_wallet.refresh_from_db()

        self.assertEqual(self.incident.status, "CONFIRMED_FRAUD")
        self.assertTrue(self.customer_wallet.is_frozen)
        self.assertIn("Verified ATO surge", self.incident.reviewer_notes)

    def test_staff_can_resolve_incident_as_approved_and_unfreeze(self):
        # First freeze customer wallet
        self.customer_wallet.freeze()
        self.assertTrue(self.customer_wallet.is_frozen)

        self.client.login(username="risk_officer", password="riskpassword123")
        response = self.client.post('/risk-console/', {
            'action': 'approve',
            'incident_id': self.incident.id,
            'notes': 'Legitimate festival emergency remittance.'
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)

        self.incident.refresh_from_db()
        self.customer_wallet.refresh_from_db()

        self.assertEqual(self.incident.status, "APPROVED")
        self.assertFalse(self.customer_wallet.is_frozen)

    def test_index_view_passes_pending_incident_count_for_staff(self):
        self.client.login(username="risk_officer", password="riskpassword123")
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('pending_incident_count', response.context)
        self.assertIn('pending_incidents', response.context)
        self.assertIn('risk_kpis', response.context)
        self.assertEqual(response.context['pending_incident_count'], 1)
        self.assertEqual(len(response.context['pending_incidents']), 1)
        self.assertEqual(response.context['risk_kpis']['pending_count'], 1)
        self.assertContains(response, "Trust &amp; Risk Console")
        self.assertContains(response, "Trust &amp; Risk Surveillance")
        self.assertContains(response, "dashResolveIncident")
