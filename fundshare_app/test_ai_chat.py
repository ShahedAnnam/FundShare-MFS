import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.test import TestCase, override_settings
from django.utils import timezone
from fundshare_app.models import User, Wallet, PurposeFund, FamilyPass, Transaction, AIInsight
from fundshare_app.ml.ai_coach import FinancialAIService
from fundshare_app.ml.demo_qa import DEMO_QA, find_demo_answer
from fundshare_app.ml.support_context import get_support_context, SUPPORT_INSTRUCTION


@override_settings(GEMINI_API_KEY='')
class HybridChatTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='chat-customer', phone='01745000001', password='SecretPassword729!')
        self.other = User.objects.create_user(username='private-other', phone='01745000002', password='PrivatePassword381!')
        Wallet.objects.create(owner=self.user, balance=Decimal('1000'))
        Wallet.objects.create(owner=self.other, balance=Decimal('987654'))
        self.client.force_login(self.user)

    def test_all_predefined_questions_bypass_gemini_and_ledger(self):
        with patch.object(FinancialAIService, 'generate_online_response') as online, patch.object(FinancialAIService, 'get_user_financial_context') as context:
            for entry in DEMO_QA:
                result = FinancialAIService.answer_query(self.user, entry['question'])
                self.assertEqual(result['answer'], entry['answer'])
                self.assertEqual(result['intent'], 'DEMO_QA')
                self.assertFalse(result['online'])
            online.assert_not_called()
            context.assert_not_called()

    def test_normalized_match_is_exact_not_broad_keyword_matching(self):
        self.assertEqual(find_demo_answer('  WHAT IS FamilyPass!!!  ')['id'], 'pass')
        self.assertEqual(find_demo_answer('What is Family Pass?')['id'], 'pass')
        self.assertIsNone(find_demo_answer('Why did my FamilyPass payment fail yesterday?'))

    def test_frontend_receives_only_public_catalog(self):
        response = self.client.get('/')
        self.assertContains(response, 'id="demoQACatalog"')
        self.assertContains(response, 'demoQuestionTopic')
        self.assertContains(response, 'How do I send money?')
        self.assertNotContains(response, 'SecretPassword729!')

    def test_matching_typed_question_api_uses_offline_answer(self):
        with patch.object(FinancialAIService, 'generate_online_response') as online:
            response = self.client.post('/api/ai/query/', {'question': 'Why do transactions need a PIN?'}, content_type='application/json')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['intent'], 'DEMO_QA')
            online.assert_not_called()

    def test_new_questions_route_to_gemini(self):
        generated = {'answer': 'A useful support answer.', 'ai_powered': True, 'online': True}
        with patch.object(FinancialAIService, 'generate_online_response', return_value=generated) as online:
            self.assertEqual(FinancialAIService.answer_query(self.user, 'Explain my recent spending trend.'), generated)
            self.assertEqual(online.call_args.args[0], self.user)

    def test_missing_key_keeps_financial_fallback(self):
        with patch('google.genai.Client') as client:
            response = FinancialAIService.answer_query(self.user, 'How much did I spend this month?')
            self.assertFalse(response['online'])
            self.assertTrue(response['fallback'])
            self.assertIn('0.00', response['answer'])
            self.assertIn('unavailable', response['notice'])
            client.assert_not_called()

    @override_settings(GEMINI_API_KEY='unit-test-secret', GEMINI_MODEL='gemini-3.1-flash-lite')
    def test_gemini_uses_requested_model_support_rules_and_private_context(self):
        with patch('google.genai.Client') as client:
            instance = client.return_value.__enter__.return_value
            instance.models.generate_content.return_value = MagicMock(text='Review your Grocery budget.')
            response = FinancialAIService.answer_query(self.user, 'Explain my wallet please.')
            self.assertTrue(response['online'])
            kwargs = instance.models.generate_content.call_args.kwargs
            self.assertEqual(kwargs['model'], 'gemini-3.1-flash-lite')
            self.assertIn('READ-ONLY', kwargs['config'].system_instruction)
            self.assertIsNone(kwargs['config'].tools)
            context = json.loads(kwargs['contents'])['authorized_context']
            self.assertEqual(Decimal(context['wallet_balance']), Decimal('1000'))
            for sensitive in ['unit-test-secret', 'SecretPassword729!', '01745000001', 'chat-customer', 'private-other']:
                self.assertNotIn(sensitive, kwargs['contents'])
                self.assertNotIn(sensitive, json.dumps(response))
            http_options = client.call_args.kwargs['http_options']
            self.assertEqual(http_options.timeout, 15000)
            self.assertEqual(http_options.retry_options.attempts, 1)

    @override_settings(GEMINI_API_KEY='unit-test-secret')
    def test_provider_failure_never_exposes_error_or_key(self):
        with patch('google.genai.Client') as client:
            instance = client.return_value.__enter__.return_value
            instance.models.generate_content.side_effect = RuntimeError('secret provider error unit-test-secret')
            response = self.client.post('/api/ai/query/', {'question': 'How much did I spend?'}, content_type='application/json')
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()['fallback'])
            self.assertNotContains(response, 'unit-test-secret')
            self.assertNotContains(response, 'secret provider error')
            self.assertEqual(instance.models.generate_content.call_count, 1)
            for entry in DEMO_QA:
                self.assertEqual(FinancialAIService.answer_query(self.user, entry['question'])['answer'], entry['answer'])
            self.assertEqual(instance.models.generate_content.call_count, 1)

    @override_settings(GEMINI_API_KEY='unit-test-secret')
    def test_empty_or_blocked_gemini_response_uses_fallback(self):
        with patch('google.genai.Client') as client:
            client.return_value.__enter__.return_value.models.generate_content.return_value = MagicMock(text=None)
            self.assertTrue(FinancialAIService.answer_query(self.user, 'My spending summary')['fallback'])

    def test_context_is_bounded_and_does_not_include_other_users_records(self):
        for index in range(10):
            PurposeFund.objects.create(owner=self.user, name=f'My Fund {index}', category='Grocery', current_balance='10', allocated_amount='10', recipient=self.other)
            Transaction.objects.create(sender=self.user, amount='1', transaction_type='SEND_MONEY', reference='private phone and receipt')
        PurposeFund.objects.create(owner=self.other, name='Private Hidden Fund', category='Medicine', current_balance='5678', allocated_amount='5678')
        Transaction.objects.create(sender=self.other, amount='54321', transaction_type='SEND_MONEY')
        AIInsight.objects.create(user=self.other, title='Hidden Insight', description='Private details', insight_type='BUDGET_OVERRUN')
        context = get_support_context(self.user)
        self.assertEqual(len(context['active_funds']), 6)
        self.assertEqual(len(context['recent_transactions']), 8)
        self.assertTrue(context['active_funds'][0]['shared_by_you'])
        encoded = json.dumps(context, default=str)
        for forbidden in ['Private Hidden Fund', '54321', '987654', 'private phone', 'Hidden Insight', '01745000002']:
            self.assertNotIn(forbidden, encoded)

    def test_received_pass_context_cannot_see_owners_other_finances(self):
        family_pass = FamilyPass.objects.create(owner=self.other, member=self.user, limit_amount='100', used_amount='10', expiry_date=timezone.localdate() + timedelta(days=2))
        Transaction.objects.create(sender=self.user, amount='10', transaction_type='MERCHANT_PAYMENT', payment_source='FAMILY_PASS', family_pass=family_pass)
        context = get_support_context(self.user)
        self.assertEqual(context['family_passes_received'][0]['remaining'], '90.00')
        self.assertNotIn('987654', json.dumps(context, default=str))
        self.assertNotIn('owner_name', context['family_passes_received'][0])

    def test_support_instruction_prohibits_financial_execution(self):
        self.assertIn('never execute', SUPPORT_INSTRUCTION)
        self.assertIn('bypass security', SUPPORT_INSTRUCTION)

    def test_api_validates_input(self):
        for question in ['', '   ', None, 123, ['bad'], 'x' * 2001]:
            response = self.client.post('/api/ai/query/', {'question': question}, content_type='application/json')
            self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.post('/api/ai/query/', {'question': 'hello', 'lang': 'xx'}, content_type='application/json').status_code, 400)

    def test_chat_still_requires_authentication(self):
        self.client.logout()
        response = self.client.post('/api/ai/query/', {'question': DEMO_QA[0]['question']}, content_type='application/json')
        self.assertIn(response.status_code, [401, 403])
