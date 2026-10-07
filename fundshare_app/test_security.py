import datetime
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch

from django.core.cache import cache
from django.db import DatabaseError, close_old_connections, connections
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from fundshare_app.models import (
    FamilyPass, FamilyPassStatus, FinancialRequest, FundStatus, Merchant,
    PurposeFund, Transaction, User, UserRole, Wallet,
)
from fundshare_app.services.transaction_service import TransactionService


class SecurityFixtures:
    def setUp(self):
        cache.clear()
        self.owner = User.objects.create_user(username='secure-owner', phone='01750000001', password='Owner-password-71!')
        self.member = User.objects.create_user(username='secure-member', phone='01750000002', password='Member-password-71!', role=UserRole.CUSTOMER)
        self.other = User.objects.create_user(username='secure-other', phone='01750000003', password='Other-password-71!')
        self.admin = User.objects.create_user(username='secure-admin', phone='01750000004', password='Admin-password-71!', role=UserRole.ADMIN, is_staff=True)
        self.merchant_user = User.objects.create_user(username='secure-merchant', phone='01750000005', password='Merchant-password-71!', role=UserRole.MERCHANT)
        for user in (self.owner, self.member, self.other, self.admin, self.merchant_user):
            user.set_transaction_pin('482951')
            user.save(update_fields=['transaction_pin'])
            Wallet.objects.create(owner=user, balance=Decimal('1000.00'))
        self.merchant = Merchant.objects.create(business_name='Secure Grocery', category='Grocery', account_number='SEC-001', user=self.merchant_user)
        self.fund = PurposeFund.objects.create(owner=self.owner, name='Grocery', category='Grocery', current_balance=Decimal('100.00'), allocated_amount=Decimal('100.00'))
        self.destination = PurposeFund.objects.create(owner=self.owner, name='Medicine', category='Medicine')
        self.family_pass = FamilyPass.objects.create(owner=self.owner, member=self.member, limit_amount=Decimal('100.00'), expiry_date=timezone.localdate() + datetime.timedelta(days=7), allowed_categories=['Grocery'])
        self.client.force_login(self.owner)
        self.anomaly_patch = patch.object(TransactionService, '_check_anomaly_and_record')
        self.anomaly_patch.start()
        self.addCleanup(self.anomaly_patch.stop)

    def post(self, path='/api/pay/', payload=None, key=None, client=None):
        data = {'merchant_id': self.merchant.pk, 'amount': '25.00', 'pin': '482951'}
        if payload is not None:
            data = payload
        return (client or self.client).post(path, data, content_type='application/json', HTTP_IDEMPOTENCY_KEY=key or str(uuid.uuid4()))


@override_settings(ENABLE_SIMULATED_CASH_IN=True)
class AuthenticationAndPaymentSecurityTests(SecurityFixtures, TestCase):
    def test_anonymous_requests_cannot_impersonate_users(self):
        client = Client()
        for path in ['/api/auth/me/', '/api/merchants/', '/api/familypass/members-list/', '/api/evaluation/metrics/', '/api/evaluation/experiments/']:
            response = client.get(path, HTTP_X_DEMO_USER=self.owner.username)
            self.assertEqual(response.status_code, 401, path)
        for path in ['/api/seed/', '/api/admin/seed-data/']:
            self.assertEqual(client.post(path, {'wipe': True}, HTTP_X_DEMO_USER=self.admin.username).status_code, 401)
        self.assertEqual(client.post('/api/auth/switch-role/', {'username': self.admin.username}).status_code, 404)

    def test_admin_endpoints_reject_wallet_users_and_staff_without_admin_role(self):
        for user in (self.owner, self.member):
            self.client.force_login(user)
            for path in ['/api/evaluation/metrics/', '/api/evaluation/experiments/']:
                self.assertEqual(self.client.get(path).status_code, 403)
            self.assertEqual(self.client.post('/api/seed/', {'wipe': True}).status_code, 403)
        self.owner.is_staff = True
        self.owner.save(update_fields=['is_staff'])
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get('/admin/').status_code, 302)

    def test_admin_access_and_reset_environment_guard(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get('/api/evaluation/experiments/').status_code, 200)
        with override_settings(ENABLE_DEMO_RESET=False):
            self.assertEqual(self.client.post('/api/seed/', {'wipe': True}).json()['code'], 'RESET_DISABLED')
        with override_settings(ENABLE_DEMO_RESET=True), patch('fundshare_app.views.api_views.SyntheticDataGenerator.populate_database', return_value={}) as seed, patch('fundshare_app.views.api_views.AnomalyDetector.get_instance'):
            self.assertEqual(self.client.post('/api/admin/seed-data/', {'wipe': False}, content_type='application/json').status_code, 200)
            seed.assert_called_once_with(wipe_existing=False)

    def test_login_requires_csrf_and_real_password(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post('/api/auth/login/', {'username': self.owner.username, 'password': 'Owner-password-71!'}).status_code, 403)
        client.get('/login/')
        csrf = client.cookies['csrftoken'].value
        response = client.post('/api/auth/login/', {'username': self.owner.username, 'password': 'wrong'}, HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(response.status_code, 401)
        response = client.post('/api/auth/login/', {'username': self.owner.username, 'password': 'Owner-password-71!'}, HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['user']['id'], self.owner.pk)
        self.assertNotIn('transaction_pin', response.json()['user'])

    def test_login_throttle_is_shared_by_page_and_api(self):
        client = Client()
        for _ in range(10):
            client.post('/login/', {'username': self.owner.username, 'password': 'wrong'})
        self.assertEqual(client.post('/api/auth/login/', {'username': self.owner.username, 'password': 'Owner-password-71!'}).status_code, 429)

    def test_safe_login_redirect_and_post_only_logout(self):
        client = Client()
        result = client.post('/login/?next=https://attacker.example/', {'username': self.owner.username, 'password': 'Owner-password-71!'})
        self.assertEqual(result.url, '/')
        self.assertEqual(client.get('/logout/').status_code, 405)
        self.assertEqual(client.get('/api/auth/me/').status_code, 200)
        self.assertEqual(client.post('/logout/').status_code, 302)
        self.assertEqual(client.get('/api/auth/me/').status_code, 401)

    def test_transactions_require_session_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        response = self.post(client=client)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Transaction.objects.count(), 0)

    def test_missing_or_incorrect_pin_never_moves_money(self):
        for pin, code in [(None, 'PIN_REQUIRED'), ('999999', 'PIN_INVALID')]:
            result = self.post(payload={'merchant_id': self.merchant.pk, 'amount': '25.00', 'pin': pin})
            self.assertEqual(result.json()['code'], code)
        self.assertEqual(Wallet.objects.get(owner=self.owner).balance, Decimal('1000.00'))
        self.assertEqual(Transaction.objects.count(), 0)
        self.assertEqual(FinancialRequest.objects.count(), 0)

    def test_every_money_moving_route_requires_pin(self):
        routes = [
            ('/api/wallet/cash-in/', {'amount': '10'}),
            ('/api/wallet/send/', {'amount': '10', 'receiver': self.other.phone}),
            ('/api/wallet/send-money/', {'amount': '10', 'receiver': self.other.phone}),
            ('/api/wallet/utility/', {'amount': '10', 'action_type': 'RECHARGE'}),
            ('/api/pay/', {'amount': '10', 'merchant_id': self.merchant.pk}),
            ('/api/payments/merchant/', {'amount': '10', 'merchant_id': self.merchant.pk}),
            ('/api/funds/', {'name': 'New', 'category': 'Grocery', 'allocated_amount': '10'}),
            (f'/api/funds/{self.fund.pk}/allocate/', {'amount': '10'}),
            ('/api/funds/transfer/', {'source_fund_id': self.fund.pk, 'destination_fund_id': self.destination.pk, 'amount': '10'}),
        ]
        for path, payload in routes:
            self.assertEqual(self.post(path, payload).json()['code'], 'PIN_REQUIRED', path)
        result = self.client.delete(f'/api/funds/{self.fund.pk}/', {}, content_type='application/json', HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))
        self.assertEqual(result.json()['code'], 'PIN_REQUIRED')
        self.assertEqual(Transaction.objects.count(), 0)

    def test_pin_lockout_persists_and_expires(self):
        for _ in range(5):
            self.post(payload={'pin': '999999'})
        self.assertEqual(self.post().json()['code'], 'PIN_LOCKED')
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.pin_failed_attempts, 5)
        self.owner.pin_locked_until = timezone.now() - datetime.timedelta(seconds=1)
        self.owner.save(update_fields=['pin_locked_until'])
        self.assertEqual(self.post().status_code, 200)
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.pin_failed_attempts, 0)

    def test_pin_setup_change_and_hash_storage(self):
        self.owner.transaction_pin = ''
        self.owner.save(update_fields=['transaction_pin'])
        self.assertEqual(self.post().json()['code'], 'PIN_NOT_SET')
        result = self.post('/api/auth/pin/', {'password': 'wrong', 'new_pin': '729485'})
        self.assertEqual(result.status_code, 403)
        result = self.post('/api/auth/pin/', {'password': 'Owner-password-71!', 'new_pin': '123456'})
        self.assertEqual(result.json()['code'], 'WEAK_PIN')
        result = self.post('/api/auth/pin/', {'password': 'Owner-password-71!', 'new_pin': '729485'})
        self.assertEqual(result.status_code, 200)

        self.owner.refresh_from_db()
        self.assertNotEqual(self.owner.transaction_pin, '729485')
        self.assertTrue(self.owner.check_transaction_pin('729485'))
        result = self.post('/api/auth/pin/', {'password': 'Owner-password-71!', 'current_pin': '482951', 'new_pin': '615829'})
        self.assertEqual(result.json()['code'], 'PIN_INVALID')
        result = self.post('/api/auth/pin/', {'password': 'Owner-password-71!', 'current_pin': '729485', 'new_pin': '615829'})
        self.assertEqual(result.status_code, 200)

    @override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.PBKDF2PasswordHasher'])
    def test_pin_uses_production_password_hashing(self):
        account = User(username='hash-check')
        account.set_transaction_pin('482951')
        self.assertTrue(account.transaction_pin.startswith('pbkdf2_sha256$'))
        self.assertTrue(account.check_transaction_pin('482951'))
        self.assertFalse(account.check_transaction_pin('999999'))

    def test_same_request_replays_original_response_including_alias(self):
        key = str(uuid.uuid4())
        first = self.post(key=key)
        second = self.post('/api/payments/merchant/', key=key)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json(), second.json())
        self.assertEqual(second['Idempotency-Replayed'], 'true')
        self.assertEqual(Transaction.objects.count(), 1)
        self.assertEqual(Wallet.objects.get(owner=self.owner).balance, Decimal('975.00'))
        self.assertEqual(FinancialRequest.objects.count(), 1)
        self.assertNotIn('482951', str(FinancialRequest.objects.get().response))

    def test_same_key_with_changed_payload_is_rejected(self):
        key = str(uuid.uuid4())
        self.post(key=key)
        result = self.post(payload={'merchant_id': self.merchant.pk, 'amount': '35.00', 'pin': '482951'}, key=key)
        self.assertEqual(result.status_code, 409)
        self.assertEqual(result.json()['code'], 'IDEMPOTENCY_CONFLICT')
        self.assertEqual(Transaction.objects.count(), 1)

    def test_missing_idempotency_key_is_rejected(self):
        self.assertEqual(self.client.post('/api/pay/', {'pin': '482951'}, content_type='application/json').json()['code'], 'IDEMPOTENCY_KEY_REQUIRED')

    def test_fund_creation_rolls_back_on_invalid_recipient_or_insufficient_balance(self):
        for payload in [
            {'name': 'Invalid', 'category': 'Grocery', 'allocated_amount': '100', 'recipient': 'not-registered', 'pin': '482951'},
            {'name': 'Invalid', 'category': 'Grocery', 'allocated_amount': '10000', 'pin': '482951'},
        ]:
            self.assertEqual(self.post('/api/funds/', payload).status_code, 400)
        self.assertEqual(PurposeFund.objects.count(), 2)
        self.assertEqual(Wallet.objects.get(owner=self.owner).balance, Decimal('1000.00'))
        self.assertEqual(Transaction.objects.count(), 0)

    def test_invalid_amounts_and_sources_are_rejected(self):
        for amount in ['NaN', 'Infinity', '-1', '0', '1.001', '10000000000', 'bad']:
            self.assertEqual(self.post(payload={'amount': amount, 'merchant_id': self.merchant.pk, 'pin': '482951'}).status_code, 400)
        result = self.post(payload={'amount': '10', 'merchant_id': self.merchant.pk, 'payment_source': 'FAKE', 'pin': '482951'})
        self.assertEqual(result.json()['code'], 'INVALID_PAYMENT_SOURCE')
        self.assertEqual(Transaction.objects.count(), 0)

    def test_permission_checks_cannot_be_bypassed_with_pin(self):
        self.client.force_login(self.other)
        for path in [f'/api/funds/{self.fund.pk}/', f'/api/funds/{self.fund.pk}/details/']:
            self.assertEqual(self.client.get(path).status_code, 404)
        self.assertEqual(self.post(f'/api/funds/{self.fund.pk}/allocate/', {'amount': '10', 'pin': '482951'}).status_code, 404)
        result = self.post(payload={'merchant_id': self.merchant.pk, 'amount': '10', 'pin': '482951', 'payment_source': 'PURPOSE_FUND', 'purpose_fund_id': self.fund.pk})
        self.assertEqual(result.status_code, 400)
        self.assertEqual(self.client.get(f'/api/family-pass/{self.family_pass.pk}/activity/').status_code, 403)
        self.assertEqual(self.client.post(f'/api/family-pass/{self.family_pass.pk}/revoke/').status_code, 403)
        self.assertEqual(self.client.get('/api/merchant/dashboard/').status_code, 403)
        self.client.force_login(self.merchant_user)
        self.assertEqual(self.post().status_code, 403)
        self.assertEqual(self.client.get('/api/merchant/dashboard/').status_code, 200)

    def test_family_pass_rejections_and_member_own_pin(self):
        self.client.force_login(self.member)
        payload = {'merchant_id': self.merchant.pk, 'amount': '25', 'payment_source': 'FAMILY_PASS', 'family_pass_id': self.family_pass.pk, 'pin': '482951'}
        for field, value, code in [
            ('status', FamilyPassStatus.REVOKED, 'FAMILYPASS_INACTIVE'),
            ('expiry_date', timezone.localdate() - datetime.timedelta(days=1), 'FAMILYPASS_EXPIRED'),
            ('start_date', timezone.localdate() + datetime.timedelta(days=1), 'FAMILYPASS_NOT_STARTED'),
            ('allowed_categories', ['Education'], 'FAMILYPASS_CATEGORY_MISMATCH'),
        ]:
            original = getattr(self.family_pass, field)
            FamilyPass.objects.filter(pk=self.family_pass.pk).update(**{field: value})
            self.assertEqual(self.post(payload=payload).json()['code'], code)
            FamilyPass.objects.filter(pk=self.family_pass.pk).update(**{field: original})
        Merchant.objects.filter(pk=self.merchant.pk).update(is_active=False)
        self.assertEqual(self.post(payload=payload).json()['code'], 'MERCHANT_INACTIVE')
        Merchant.objects.filter(pk=self.merchant.pk).update(is_active=True)
        self.owner.set_transaction_pin('615829')
        self.owner.save(update_fields=['transaction_pin'])
        self.assertEqual(self.post(payload=payload).status_code, 200)
        self.assertEqual(Wallet.objects.get(owner=self.owner).balance, Decimal('975.00'))
        self.assertEqual(Wallet.objects.get(owner=self.member).balance, Decimal('1000.00'))

    def test_archived_fund_and_bill_category_spoofing_are_rejected(self):
        PurposeFund.objects.filter(pk=self.fund.pk).update(status=FundStatus.ARCHIVED)
        result = self.post(payload={'merchant_id': self.merchant.pk, 'amount': '10', 'payment_source': 'PURPOSE_FUND', 'purpose_fund_id': self.fund.pk, 'pin': '482951'})
        self.assertEqual(result.json()['code'], 'FUND_INACTIVE')
        self.client.force_login(self.member)
        result = self.post('/api/wallet/utility/', {'action_type': 'BILL', 'amount': '10', 'payment_source': 'FAMILY_PASS', 'family_pass_id': self.family_pass.pk, 'category': 'Grocery', 'bill_type': 'Grocery', 'provider': 'DESCO', 'pin': '482951'})
        self.assertEqual(result.json()['code'], 'FAMILYPASS_CATEGORY_MISMATCH')

    def test_bill_provider_registry_matches_visible_options(self):
        for provider, category in TransactionService.BILL_PROVIDER_CATEGORIES.items():
            result = self.post('/api/wallet/utility/', {'action_type': 'BILL', 'amount': '1', 'provider': provider, 'category': 'Grocery', 'pin': '482951'})
            self.assertEqual(result.status_code, 200, provider)
            self.assertEqual(result.json()['transaction']['category'], category)
        result = self.post('/api/wallet/utility/', {'action_type': 'BILL', 'amount': '1', 'provider': 'Unregistered provider', 'pin': '482951'})
        self.assertEqual(result.json()['code'], 'PROVIDER_UNAUTHORIZED')

    def test_simulated_cash_in_is_disabled_when_configured(self):
        with override_settings(ENABLE_SIMULATED_CASH_IN=False):
            self.assertEqual(self.post('/api/wallet/cash-in/', {'amount': '10', 'pin': '482951'}).json()['code'], 'CASH_IN_DISABLED')

    def test_fund_refund_is_idempotent(self):
        key = str(uuid.uuid4())
        url = f'/api/funds/{self.fund.pk}/'
        args = dict(data={'pin': '482951'}, content_type='application/json', HTTP_IDEMPOTENCY_KEY=key)
        first = self.client.delete(url, **args)
        second = self.client.delete(url, **args)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json(), second.json())
        self.assertEqual(Wallet.objects.get(owner=self.owner).balance, Decimal('1100.00'))

    def test_all_financial_operations_replay_without_second_balance_change(self):
        operations = [
            ('/api/wallet/cash-in/', {'amount': '10', 'pin': '482951'}),
            ('/api/wallet/send/', {'amount': '10', 'receiver': self.other.phone, 'pin': '482951'}),
            ('/api/wallet/utility/', {'amount': '10', 'action_type': 'CASHOUT', 'pin': '482951'}),
            (f'/api/funds/{self.fund.pk}/allocate/', {'amount': '10', 'pin': '482951'}),
            ('/api/funds/transfer/', {'amount': '10', 'source_fund_id': self.fund.pk, 'destination_fund_id': self.destination.pk, 'pin': '482951'}),
            ('/api/funds/', {'name': 'New Fund', 'category': 'Education', 'allocated_amount': '10', 'pin': '482951'}),
        ]
        for path, payload in operations:
            key = str(uuid.uuid4())
            first = self.post(path, payload, key)
            self.assertLess(first.status_code, 300, first.json())
            balances = list(Wallet.objects.order_by('pk').values_list('balance', flat=True))
            funds = list(PurposeFund.objects.order_by('pk').values_list('current_balance', flat=True))
            transactions = Transaction.objects.count()
            second = self.post(path, payload, key)
            self.assertEqual(second.json(), first.json(), path)
            self.assertEqual(list(Wallet.objects.order_by('pk').values_list('balance', flat=True)), balances)
            self.assertEqual(list(PurposeFund.objects.order_by('pk').values_list('current_balance', flat=True)), funds)
            self.assertEqual(Transaction.objects.count(), transactions)

    def test_failure_after_debit_rolls_back_and_same_key_can_retry(self):
        key = str(uuid.uuid4())
        with patch('fundshare_app.services.transaction_service.Notification.objects.create', side_effect=DatabaseError('Injected write failure')):
            self.assertEqual(self.post(key=key).status_code, 503)
        self.assertEqual(Wallet.objects.get(owner=self.owner).balance, Decimal('1000.00'))
        self.assertEqual(Merchant.objects.get(pk=self.merchant.pk).balance, Decimal('0.00'))
        self.assertEqual(Transaction.objects.count(), 0)
        self.assertEqual(FinancialRequest.objects.count(), 0)
        self.assertEqual(self.post(key=key).status_code, 200)

    def test_rejection_audit_is_preserved_without_duplicate_on_retry(self):
        self.client.force_login(self.member)
        FamilyPass.objects.filter(pk=self.family_pass.pk).update(allowed_categories=['Education'])
        key = str(uuid.uuid4())
        payload = {'merchant_id': self.merchant.pk, 'amount': '25', 'pin': '482951', 'payment_source': 'FAMILY_PASS', 'family_pass_id': self.family_pass.pk}
        result = self.post(payload=payload, key=key)
        self.assertEqual(result.status_code, 400)
        self.assertEqual(self.post(payload=payload, key=key).json(), result.json())
        self.assertEqual(Transaction.objects.filter(status='REJECTED').count(), 1)
        self.assertEqual(Transaction.objects.filter(status='COMPLETED').count(), 0)

    def test_ledger_and_balances_are_read_only_in_admin(self):
        self.admin.is_superuser = True
        self.admin.save(update_fields=['is_superuser'])
        self.client.force_login(self.admin)
        for model, instance in [('wallet', self.owner.wallet), ('purposefund', self.fund), ('familypass', self.family_pass)]:
            self.assertEqual(self.client.post(f'/admin/fundshare_app/{model}/{instance.pk}/change/', {'balance': '999999'}).status_code, 403)

    def test_admin_profile_update_preserves_concurrent_pin_changes(self):
        from django.contrib import admin
        stale_user = User.objects.get(pk=self.owner.pk)
        current_user = User.objects.get(pk=self.owner.pk)
        current_user.set_transaction_pin('615829')
        current_user.pin_failed_attempts = 4
        current_user.save(update_fields=['transaction_pin', 'pin_failed_attempts'])
        stale_user.full_name = 'Updated name'
        admin.site._registry[User].save_model(None, stale_user, None, change=True)
        current_user.refresh_from_db()
        self.assertTrue(current_user.check_transaction_pin('615829'))
        self.assertEqual(current_user.pin_failed_attempts, 4)
        self.assertEqual(current_user.full_name, 'Updated name')


class ConcurrentTransactionTests(SecurityFixtures, TransactionTestCase):
    def run_parallel(self, jobs):
        barrier = Barrier(len(jobs))

        def work(job):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return job()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=len(jobs)) as executor:
            futures = [executor.submit(work, job) for job in jobs]
            return [future.result(timeout=40) for future in futures]

    def payment_job(self, user, key, source='NORMAL_WALLET'):
        client = Client()
        client.force_login(user)
        payload = {'merchant_id': self.merchant.pk, 'amount': '75.00', 'pin': '482951', 'payment_source': source}
        if source == 'PURPOSE_FUND':
            payload['purpose_fund_id'] = self.fund.pk
        if source == 'FAMILY_PASS':
            payload['family_pass_id'] = self.family_pass.pk
        return lambda: self.post(payload=payload, key=key, client=client)

    def test_concurrent_identical_request_deducts_once(self):
        key = str(uuid.uuid4())
        jobs = [self.payment_job(self.owner, key) for _ in range(2)]
        results = self.run_parallel(jobs)
        # A transient database failure is retried with the original idempotency key.
        for i, result in enumerate(results):
            if result.status_code == 503:
                results[i] = jobs[i]()
        self.assertEqual([response.status_code for response in results], [200, 200])
        self.assertEqual(results[0].json(), results[1].json())
        self.assertEqual(Transaction.objects.filter(status='COMPLETED').count(), 1)
        self.assertEqual(Wallet.objects.get(owner=self.owner).balance, Decimal('925.00'))

    def test_concurrent_fund_payments_cannot_overspend(self):
        jobs = [self.payment_job(self.owner, str(uuid.uuid4()), 'PURPOSE_FUND') for _ in range(2)]
        results = self.run_parallel(jobs)
        for i, result in enumerate(results):
            if result.status_code == 503:
                results[i] = jobs[i]()
        self.assertEqual(sorted(response.status_code for response in results), [200, 400])
        self.assertEqual(PurposeFund.objects.get(pk=self.fund.pk).current_balance, Decimal('25.00'))
        self.assertEqual(Merchant.objects.get(pk=self.merchant.pk).balance, Decimal('75.00'))

    def test_concurrent_family_pass_payments_cannot_exceed_limit(self):
        jobs = [self.payment_job(self.member, str(uuid.uuid4()), 'FAMILY_PASS') for _ in range(2)]
        results = self.run_parallel(jobs)
        for i, result in enumerate(results):
            if result.status_code == 503:
                results[i] = jobs[i]()
        self.assertEqual(sorted(response.status_code for response in results), [200, 400])
        self.assertEqual(FamilyPass.objects.get(pk=self.family_pass.pk).used_amount, Decimal('75.00'))
        self.assertEqual(Wallet.objects.get(owner=self.owner).balance, Decimal('925.00'))

    def test_concurrent_different_wallets_credit_merchant_without_lost_updates(self):
        jobs = [self.payment_job(user, str(uuid.uuid4())) for user in (self.owner, self.other)]
        results = self.run_parallel(jobs)
        for i, result in enumerate(results):
            if result.status_code == 503:
                results[i] = jobs[i]()
        self.assertEqual([response.status_code for response in results], [200, 200])
        self.assertEqual(Merchant.objects.get(pk=self.merchant.pk).balance, Decimal('150.00'))

    def test_concurrent_allocations_cannot_overspend_wallet(self):
        clients = [Client(), Client()]
        for client in clients:
            client.force_login(self.owner)
        keys = [str(uuid.uuid4()), str(uuid.uuid4())]
        jobs = [lambda i=i: self.post(f'/api/funds/{self.fund.pk}/allocate/', {'amount': '700', 'pin': '482951'}, keys[i], clients[i]) for i in range(2)]
        results = self.run_parallel(jobs)
        for i, result in enumerate(results):
            if result.status_code == 503:
                results[i] = jobs[i]()
        self.assertEqual(sorted(response.status_code for response in results), [200, 400])
        self.assertEqual(Wallet.objects.get(owner=self.owner).balance, Decimal('300.00'))
        self.assertEqual(PurposeFund.objects.get(pk=self.fund.pk).current_balance, Decimal('800.00'))

    def test_concurrent_interfund_transfers_cannot_overspend_source(self):
        clients = [Client(), Client()]
        for client in clients:
            client.force_login(self.owner)
        keys = [str(uuid.uuid4()), str(uuid.uuid4())]
        payload = {'source_fund_id': self.fund.pk, 'destination_fund_id': self.destination.pk, 'amount': '75', 'pin': '482951'}
        jobs = [lambda i=i: self.post('/api/funds/transfer/', payload, keys[i], clients[i]) for i in range(2)]
        results = self.run_parallel(jobs)
        for i, result in enumerate(results):
            if result.status_code == 503:
                results[i] = jobs[i]()
        self.assertEqual(sorted(response.status_code for response in results), [200, 400])
        self.assertEqual(PurposeFund.objects.get(pk=self.fund.pk).current_balance, Decimal('25.00'))
        self.assertEqual(PurposeFund.objects.get(pk=self.destination.pk).current_balance, Decimal('75.00'))

    def test_revoke_and_spend_are_serialized(self):
        owner_client = Client()
        owner_client.force_login(self.owner)
        jobs = [
            self.payment_job(self.member, str(uuid.uuid4()), 'FAMILY_PASS'),
            lambda: owner_client.post(f'/api/family-pass/{self.family_pass.pk}/revoke/', {}, content_type='application/json'),
        ]
        results = self.run_parallel(jobs)
        for i, result in enumerate(results):
            if result.status_code == 503:
                results[i] = jobs[i]()
        self.assertEqual(results[1].status_code, 200)
        self.assertIn(results[0].status_code, [200, 400])
        family_pass = FamilyPass.objects.get(pk=self.family_pass.pk)
        self.assertEqual(family_pass.status, FamilyPassStatus.REVOKED)
        expected = Decimal('75.00') if results[0].status_code == 200 else Decimal('0.00')
        self.assertEqual(family_pass.used_amount, expected)
        self.assertEqual(Wallet.objects.get(owner=self.owner).balance, Decimal('1000.00') - expected)
        result = self.payment_job(self.member, str(uuid.uuid4()), 'FAMILY_PASS')()
        self.assertEqual(result.json()['code'], 'FAMILYPASS_INACTIVE')
