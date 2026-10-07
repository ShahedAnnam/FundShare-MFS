import json
from decimal import Decimal
from unittest.mock import patch, MagicMock
from django.utils import timezone
from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient
from rest_framework import status

from fundshare_app.models import (
    UserRole, Wallet, PurposeFund, Transaction, TransactionType,
    PaymentSource, TransactionStatus, AnomalyResult, FamilyPass, FamilyPassStatus
)
from fundshare_app.ml.context_builder import MLContextBuilder
from fundshare_app.ml.recommendation_engine import RecommendationEngine
from fundshare_app.ml.ai_coach import AICoach, FinancialAIService

User = get_user_model()


class GroundedAILayerTests(TestCase):
    def setUp(self):
        self.client = APIClient()

        # Create User A
        self.user_a = User.objects.create_user(
            username='ai_test_alice',
            phone='01711000001',
            full_name='Alice Ahmed',
            password='Password123!',
            role=UserRole.CUSTOMER
        )
        self.wallet_a = Wallet.objects.create(owner=self.user_a, balance=Decimal('15000.00'))

        # Create User B
        self.user_b = User.objects.create_user(
            username='ai_test_bob',
            phone='01711000002',
            full_name='Bob Barua',
            password='Password123!',
            role=UserRole.CUSTOMER
        )
        self.wallet_b = Wallet.objects.create(owner=self.user_b, balance=Decimal('5000.00'))

        # User A funds & transactions
        self.fund_a = PurposeFund.objects.create(
            owner=self.user_a,
            name='Alice Grocery',
            category='Grocery',
            allocated_amount=Decimal('6000.00'),
            current_balance=Decimal('1200.00'),
            status='ACTIVE'
        )

        self.txn_a = Transaction.objects.create(
            sender=self.user_a,
            amount=Decimal('4800.00'),
            transaction_type=TransactionType.MERCHANT_PAYMENT,
            payment_source=PaymentSource.PURPOSE_FUND,
            purpose_fund=self.fund_a,
            category='Grocery',
            status=TransactionStatus.COMPLETED
        )

        # Anomaly for Alice's transaction
        self.anomaly_a = AnomalyResult.objects.create(
            user=self.user_a,
            transaction=self.txn_a,
            anomaly_score=Decimal('0.87'),
            is_anomaly=True,
            model_version='isoforest_v2_202610',
            reason='Higher-than-usual amount for this time slot'
        )

        # User B funds & transactions
        self.fund_b = PurposeFund.objects.create(
            owner=self.user_b,
            name='Bob Medicine',
            category='Medicine',
            allocated_amount=Decimal('4000.00'),
            current_balance=Decimal('3500.00'),
            status='ACTIVE'
        )

        self.txn_b = Transaction.objects.create(
            sender=self.user_b,
            amount=Decimal('500.00'),
            transaction_type=TransactionType.MERCHANT_PAYMENT,
            payment_source=PaymentSource.PURPOSE_FUND,
            purpose_fund=self.fund_b,
            category='Medicine',
            status=TransactionStatus.COMPLETED
        )

    # 1. AUTHENTICATION TESTS
    def test_unauthenticated_access_denied(self):
        """Unauthenticated requests must be rejected with 401 across all AI endpoints."""
        endpoints = [
            ('get', '/api/ai/recommendations/'),
            ('post', '/api/ai/coach/'),
            ('get', '/api/ai/forecast/'),
            ('get', f'/api/ai/transaction/{self.txn_a.id}/explain/'),
        ]
        for method, url in endpoints:
            if method == 'get':
                resp = self.client.get(url)
            else:
                resp = self.client.post(url, {'question': 'hello'})
            self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED, f"Failed on {url}")

    # 2. USER ISOLATION TESTS
    def test_context_strict_user_isolation(self):
        """MLContextBuilder must never leak another user's funds, wallet or transactions."""
        ctx_a = MLContextBuilder.build_user_context(self.user_a)
        ctx_b = MLContextBuilder.build_user_context(self.user_b)

        # User A check
        self.assertEqual(ctx_a['user']['username'], 'ai_test_alice')
        self.assertEqual(ctx_a['wallet']['balance'], 15000.0)
        fund_names_a = [f['name'] for f in ctx_a['purpose_funds']]
        self.assertIn('Alice Grocery', fund_names_a)
        self.assertNotIn('Bob Medicine', fund_names_a)

        # User B check
        self.assertEqual(ctx_b['user']['username'], 'ai_test_bob')
        self.assertEqual(ctx_b['wallet']['balance'], 5000.0)
        fund_names_b = [f['name'] for f in ctx_b['purpose_funds']]
        self.assertIn('Bob Medicine', fund_names_b)
        self.assertNotIn('Alice Grocery', fund_names_b)

    def test_cross_user_transaction_explain_forbidden(self):
        """User A must not be allowed to explain User B's transaction (HTTP 403)."""
        self.client.force_authenticate(user=self.user_a)

        # Attempt to explain User B's transaction
        resp = self.client.get(f'/api/ai/transaction/{self.txn_b.id}/explain/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        self.assertIn('Access denied', resp.data.get('error', ''))

        # Explain own transaction should succeed
        resp_own = self.client.get(f'/api/ai/transaction/{self.txn_a.id}/explain/')
        self.assertEqual(resp_own.status_code, status.HTTP_200_OK)
        self.assertIn('explanation', resp_own.data)

    # 3. RECOMMENDATION GROUNDING & NO HARDCODING
    def test_recommendation_grounding_real_database_values(self):
        """Recommendations must be computed from actual database values without hardcoded fake constants."""
        recs = RecommendationEngine.generate_recommendations(self.user_a)
        self.assertIsInstance(recs, list)
        self.assertTrue(len(recs) > 0)

        # Every recommendation must have required schema keys
        for r in recs:
            self.assertIn('type', r)
            self.assertIn('priority', r)
            self.assertIn('title', r)
            self.assertIn('message', r)
            self.assertIn('evidence', r)
            self.assertIn('source', r)
            self.assertIn('action', r)
            self.assertIn(r['source'], ['anomaly_model', 'forecast_model', 'deterministic_rule', 'spending_analysis', 'family_pass_rule'])

        # Verify evidence uses real values
        low_fund_recs = [r for r in recs if r['type'] == 'low_fund_balance']
        if low_fund_recs:
            rec = low_fund_recs[0]
            self.assertEqual(rec['evidence']['current_balance'], 1200.0)

    # 4. ANOMALY EXPLANATION & WORDING (unusual != fraudulent)
    def test_anomaly_explanation_language_and_ml_output(self):
        """Anomaly explanation must cite Isolation Forest and avoid declaring fraud."""
        explanation_data = AICoach.explain_transaction(self.user_a, self.txn_a)
        self.assertTrue(explanation_data['is_anomaly'])
        self.assertEqual(explanation_data['anomaly_score'], 0.87)
        self.assertIn('Isolation Forest', explanation_data['explanation'])
        self.assertIn('unusual', explanation_data['explanation'].lower())
        self.assertIn('fraud', explanation_data['explanation'].lower())
        # Confirms the distinction statement is present
        self.assertIn('does NOT mean', explanation_data['explanation'])

    # 5. AUTONOMOUS ACTION REFUSAL
    def test_ai_coach_refuses_financial_actions(self):
        """AI Coach must refuse autonomous financial actions and must NOT execute money movements."""
        action_queries = [
            "Transfer ৳2,000 from my Grocery Fund to my main wallet",
            "Send money ৳500 to 01711000002 immediately",
            "Pay merchant ৳1000 for groceries",
            "Change my FamilyPass limit to 10000"
        ]

        self.client.force_authenticate(user=self.user_a)
        balance_before = Wallet.objects.get(owner=self.user_a).balance

        for query in action_queries:
            resp = self.client.post('/api/ai/coach/', {'question': query})
            self.assertEqual(resp.status_code, status.HTTP_200_OK)
            data = resp.data
            self.assertTrue(data.get('is_action_refusal', False), f"Failed to refuse action query: {query}")
            self.assertIn('advisory', data.get('answer', '').lower())

        # Verify wallet balance is strictly unmodified
        balance_after = Wallet.objects.get(owner=self.user_a).balance
        self.assertEqual(balance_before, balance_after)

    # 6. GEMINI FAILURE FALLBACK
    def test_gemini_failure_deterministic_fallback(self):
        """When Gemini API call fails or key is missing, AI Coach falls back safely without crashing."""
        with patch.object(FinancialAIService, 'generate_online_response', return_value=None):
            resp = AICoach.answer_query(self.user_a, "Which fund needs attention?", lang="en")
            self.assertIn("answer", resp)
            self.assertFalse(resp.get("ai_powered", True))
            self.assertIn("Offline", resp.get("source", ""))
            # Contains actual financial insight from fallback
            self.assertTrue(len(resp["answer"]) > 10)

    # 7. GEMINI PROMPT GROUNDING STRICTNESS
    def test_gemini_prompt_contains_only_current_user_data(self):
        """When calling Gemini, prompt context contains ONLY current user data."""
        captured_facts = []

        def mock_generate_online(user, question, intent, facts, lang='en'):
            captured_facts.append(facts)
            return {
                "question": question,
                "answer": "Your grocery spending is on track.",
                "source": "gemini-2.5-flash (AI-Grounded)",
                "ai_powered": True,
                "online": True
            }

        with patch.object(FinancialAIService, 'generate_online_response', side_effect=mock_generate_online):
            resp = AICoach.answer_query(self.user_a, "How is my grocery fund?", lang="en")

        self.assertTrue(len(captured_facts) > 0)
        facts = captured_facts[0]
        # Current user check
        self.assertEqual(facts['user']['username'], 'ai_test_alice')
        fund_names = [f['name'] for f in facts['purpose_funds']]
        self.assertIn('Alice Grocery', fund_names)
        self.assertNotIn('Bob Medicine', fund_names)
        self.assertNotIn('ai_test_bob', str(facts))
