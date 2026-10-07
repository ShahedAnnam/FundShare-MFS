import datetime
import importlib
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, RequestFactory, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from fundshare_app.models import Contact, FamilyPass, PurposeFund, Transaction, User, UserRole, Wallet
from fundshare_app.serializers.api_serializers import ContactSerializer
from fundshare_app.services.phone_utils import find_user_by_phone, find_user_by_phone_or_username
from fundshare_app.services.recipient_service import RecipientService
from fundshare_app.services.security_service import (
    SecurityError, check_login_rate, login_rate_keys, record_login_failure, verify_pin,
)
from fundshare_app.test_security import SecurityFixtures


class GlobalPhoneRecipientTests(SecurityFixtures, TestCase):
    def send(self, phone, **kwargs):
        return self.post('/api/wallet/send/', {'receiver_phone': phone, 'amount': '10', 'pin': '482951'}, **kwargs)

    def test_send_money_without_contacts_and_retry_deducts_once(self):
        self.assertEqual(Contact.objects.count(), 0)
        first = self.send(self.other.phone, key='phone-transfer-001')
        replay = self.send(self.other.phone, key='phone-transfer-001')
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json(), replay.json())
        self.assertEqual(replay['Idempotency-Replayed'], 'true')
        self.assertEqual(Wallet.objects.get(owner=self.owner).balance, Decimal('990'))
        self.assertEqual(Wallet.objects.get(owner=self.other).balance, Decimal('1010'))
        self.assertEqual(Transaction.objects.count(), 1)
        self.assertFalse(Contact.objects.exists())

    def test_send_money_accepts_normalized_country_formats(self):
        for phone in ['+880 1750-000003', '008801750000003', '8801750000003', '1750000003', '(01750) 000-003']:
            with self.subTest(phone=phone):
                self.assertEqual(self.send(phone).status_code, 200)
        self.assertEqual(Wallet.objects.get(owner=self.other).balance, Decimal('1050'))

    def test_legacy_receiver_field_accepts_phone_but_not_username(self):
        result = self.post('/api/wallet/send-money/', {'receiver': self.other.phone, 'amount': '10', 'pin': '482951'})
        self.assertEqual(result.status_code, 200)
        result = self.post('/api/wallet/send-money/', {'receiver': self.other.username, 'amount': '10', 'pin': '482951'})
        self.assertEqual(result.json()['code'], 'RECIPIENT_PHONE_INVALID')

    def test_username_looking_like_a_phone_does_not_override_phone_owner(self):
        alias = User.objects.create_user(username=self.other.phone, phone='01750000006')
        Wallet.objects.create(owner=alias)
        self.assertEqual(find_user_by_phone_or_username(alias.username).pk, alias.pk)
        self.assertEqual(find_user_by_phone(alias.username).pk, self.other.pk)
        self.assertEqual(self.send(alias.username).status_code, 200)
        self.assertEqual(Wallet.objects.get(owner=alias).balance, Decimal('0'))
        self.assertEqual(Wallet.objects.get(owner=self.other).balance, Decimal('1010'))

    def test_unknown_phone_rejected_in_all_sharing_flows(self):
        unknown = '01999999999'
        requests = [
            ('/api/wallet/send/', {'receiver_phone': unknown, 'amount': '10', 'pin': '482951'}),
            ('/api/family-pass/', {'recipient_phone': unknown, 'limit_amount': '100', 'purpose': 'Grocery'}),
            ('/api/funds/', {'name': 'Phone Fund', 'category': 'Grocery', 'recipient': unknown, 'allocated_amount': '10', 'pin': '482951'}),
        ]
        for path, payload in requests:
            with self.subTest(path=path):
                result = self.post(path, payload)
                self.assertEqual(result.status_code, 400)
                self.assertEqual(result.json()['error'], 'This account is not registered yet.')
                self.assertEqual(result.json()['code'], 'RECIPIENT_NOT_REGISTERED')
        result = self.client.patch(f'/api/funds/{self.fund.pk}/', {'recipient': unknown}, content_type='application/json')
        self.assertEqual(result.json()['error'], 'This account is not registered yet.')
        self.assertEqual(result.json()['code'], 'RECIPIENT_NOT_REGISTERED')
        self.assertEqual(Wallet.objects.get(owner=self.owner).balance, Decimal('1000'))
        self.assertEqual(FamilyPass.objects.count(), 1)
        self.assertFalse(Transaction.objects.exists())

    def test_invalid_phone_types_usernames_and_account_ids_rejected(self):
        for phone in [None, '', 1750000003, [], {}, self.other.username, str(self.other.pk), '+101750000003', '017500000003', '01750000003\nextra', '০১৭৫০০০০০০৩']:
            with self.subTest(phone=phone):
                result = self.send(phone)
                self.assertEqual(result.status_code, 400)
                self.assertEqual(result.json()['code'], 'RECIPIENT_PHONE_INVALID')
        self.assertFalse(Transaction.objects.exists())

    def test_family_pass_is_shared_by_phone_without_contacts_or_role_changes(self):
        result = self.post('/api/family-pass/', {'recipient_phone': '+8801750000003', 'limit_amount': '50', 'purpose': 'Grocery'})
        self.assertEqual(result.status_code, 201, result.json())
        family_pass = FamilyPass.objects.get(member=self.other)
        self.assertEqual(family_pass.owner_id, self.owner.pk)
        issued = self.client.get('/api/family-pass/').json()['issued_passes']
        self.assertEqual(next(item for item in issued if item['id'] == family_pass.pk)['member_phone'], self.other.phone)
        self.assertEqual(User.objects.get(pk=self.other.pk).role, UserRole.CUSTOMER)
        self.assertFalse(Contact.objects.exists())

    def test_family_pass_legacy_member_field_is_phone_only(self):
        result = self.post('/api/family-pass/', {'member': self.other.username, 'limit_amount': '50', 'purpose': 'Grocery'})
        self.assertEqual(result.json()['code'], 'RECIPIENT_PHONE_INVALID')
        result = self.post('/api/family-pass/', {'member': self.other.phone, 'limit_amount': '50', 'purpose': 'Grocery'})
        self.assertEqual(result.status_code, 201)

    def test_fund_create_edit_and_remove_recipient_without_contacts(self):
        result = self.post('/api/funds/', {'name': 'Phone Fund', 'category': 'Grocery', 'recipient': '+8801750000003', 'allocated_amount': '10', 'pin': '482951'})
        self.assertEqual(result.status_code, 201, result.json())
        fund = PurposeFund.objects.get(name='Phone Fund')
        self.assertEqual(fund.recipient_id, self.other.pk)
        self.assertEqual(result.json()['recipient_phone'], self.other.phone)
        path = f'/api/funds/{fund.pk}/'
        result = self.client.patch(path, {'recipient': self.member.phone}, content_type='application/json')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()['fund']['recipient_phone'], self.member.phone)
        result = self.client.patch(path, {'recipient': ''}, content_type='application/json')
        self.assertEqual(result.status_code, 200)
        fund.refresh_from_db()
        self.assertIsNone(fund.recipient_id)
        self.assertFalse(Contact.objects.exists())

    def test_inactive_account_rejected_for_transfer_and_family_pass(self):
        self.other.is_active = False
        self.other.save(update_fields=['is_active'])
        self.assertEqual(self.send(self.other.phone).json()['code'], 'RECIPIENT_INACTIVE')
        result = self.post('/api/family-pass/', {'recipient_phone': self.other.phone, 'limit_amount': '50'})
        self.assertEqual(result.json()['code'], 'RECIPIENT_INACTIVE')
        self.assertFalse(Transaction.objects.exists())

    def test_invalid_optional_fund_recipient_is_not_silently_cleared(self):
        for phone in [[], {}, 0, False, self.other.username]:
            with self.subTest(phone=phone):
                result = self.post('/api/funds/', {'name': 'Invalid Recipient', 'category': 'Grocery', 'recipient': phone, 'pin': '482951'})
                self.assertEqual(result.json()['code'], 'RECIPIENT_PHONE_INVALID')
                result = self.client.patch(f'/api/funds/{self.fund.pk}/', {'recipient': phone}, content_type='application/json')
                self.assertEqual(result.json()['code'], 'RECIPIENT_PHONE_INVALID')
        self.assertFalse(PurposeFund.objects.filter(name='Invalid Recipient').exists())

    def test_resolver_get_post_and_legacy_route_are_global_and_private(self):
        expected = None
        for path in ['/api/recipients/resolve/', '/api/contacts/resolve/']:
            for method in ['get', 'post']:
                result = getattr(self.client, method)(path, {'phone': '+8801750000003', 'feature': 'FAMILY_PASS'})
                self.assertEqual(result.status_code, 200)
                body = result.json()
                self.assertTrue(body['is_eligible'])
                self.assertEqual(body['normalized_phone'], self.other.phone)
                self.assertEqual(body['user']['id'], self.other.pk)
                for private in ['password', 'transaction_pin', 'wallet_balance', 'pin_failed_attempts']:
                    self.assertNotIn(private, body['user'])
                expected = expected or body
                self.assertEqual(body, expected)
        self.assertFalse(Contact.objects.exists())

    def test_resolver_requires_authentication_and_csrf(self):
        for path in ['/api/recipients/resolve/', '/api/contacts/resolve/']:
            self.assertEqual(Client().get(path, {'phone': self.other.phone}).status_code, 401)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        self.assertEqual(client.post('/api/recipients/resolve/', {'phone': self.other.phone}).status_code, 403)

    def test_unknown_resolver_and_invalid_json_have_clear_errors(self):
        result = self.client.get('/api/recipients/resolve/', {'phone': '01999999999'})
        self.assertFalse(result.json()['is_registered'])
        self.assertIsNone(result.json()['user'])
        self.assertEqual(result.json()['error_message'], 'This account is not registered yet.')
        self.assertEqual(self.client.post('/api/recipients/resolve/', [], content_type='application/json').status_code, 400)

    def test_contacts_are_optional_and_username_never_matches_another_phone(self):
        contact = Contact.objects.create(owner=self.owner, name='Wrong alias', phone='01999999999', username=self.other.username)
        self.assertFalse(contact.is_registered)
        self.assertFalse(ContactSerializer(contact).data['allowed_features']['send_money'])
        contact.phone = self.other.phone
        contact.save()
        self.assertTrue(contact.is_registered)
        contact.delete()
        self.assertTrue(RecipientService.check_recipient_eligibility(self.other.phone)[0])
        self.assertEqual(self.send(self.other.phone).status_code, 200)

    def test_contact_permissions_match_inactive_and_non_customer_recipients(self):
        for account, active, expected in [(self.other, False, False), (self.merchant_user, True, False), (self.member, True, True)]:
            account.is_active = active
            account.save(update_fields=['is_active'])
            contact = Contact.objects.create(owner=self.owner, name=account.username, phone=account.phone)
            features = ContactSerializer(contact).data['allowed_features']
            self.assertEqual(features['send_money'], active)
            self.assertEqual(features['family_pass'], expected)

    def test_registration_creates_no_contact_and_new_customer_is_globally_resolvable(self):
        client = Client()
        response = client.post('/api/auth/register/', {
            'username': 'fresh_customer', 'full_name': 'Fresh Customer', 'phone': '+8801812345678',
            'password1': 'QuietRiver!53927', 'password2': 'QuietRiver!53927',
        }, content_type='application/json')
        self.assertEqual(response.status_code, 201)
        self.assertFalse(Contact.objects.exists())
        result = self.client.get('/api/recipients/resolve/', {'phone': '01812345678'})
        self.assertTrue(result.json()['is_eligible'])
        self.assertEqual(result.json()['user']['id'], response.json()['user']['id'])


class CanonicalPhoneTests(TestCase):
    def test_model_save_and_clean_normalize_phones(self):
        for index, raw in enumerate(['+880 1712-345678', '008801712345678', '8801712345678', '1712345678']):
            account = User(username=f'variant-{index}', phone=raw)
            account.clean()
            self.assertEqual(account.phone, '01712345678')
            account.phone = raw
            account.save()
            account.refresh_from_db()
            self.assertEqual(account.phone, '01712345678')
            account.delete()

    def test_blank_phones_become_null_without_false_duplicates(self):
        for index, phone in enumerate([None, '', '  ']):
            User.objects.create_user(username=f'blank-{index}', phone=phone)
        self.assertEqual(User.objects.filter(phone__isnull=True).count(), 3)

    def test_malformed_phone_is_rejected_by_model_and_database(self):
        account = User.objects.create_user(username='canonical', phone='01712345678')
        for phone in ['01212345678', '+101712345678', '01712345678\nextra', '+8801712345678', '']:
            with self.subTest(phone=phone), self.assertRaises(IntegrityError), transaction.atomic():
                User.objects.filter(pk=account.pk).update(phone=phone)
        account.phone = 'invalid'
        with self.assertRaises(ValidationError):
            account.save()

    def test_normalized_number_is_unique(self):
        User.objects.create_user(username='canonical', phone='01712345678')
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user(username='duplicate', phone='+8801712345678')


class OneMinuteLockoutTests(SecurityFixtures, TestCase):
    def test_pin_lockout_is_exactly_one_minute_and_does_not_extend(self):
        now = timezone.now()
        with patch('fundshare_app.services.security_service.timezone.now', return_value=now):
            for _ in range(5):
                result = self.send_wrong_pin()
                self.assertEqual(result.json()['code'], 'PIN_INVALID')
        self.owner.refresh_from_db()
        deadline = now + datetime.timedelta(seconds=60)
        self.assertEqual(self.owner.pin_locked_until, deadline)
        with patch('fundshare_app.services.security_service.timezone.now', return_value=now + datetime.timedelta(seconds=59)):
            self.assertEqual(self.post().json()['code'], 'PIN_LOCKED')
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.pin_locked_until, deadline)
        self.assertFalse(Transaction.objects.exists())
        with patch('fundshare_app.services.security_service.timezone.now', return_value=deadline):
            self.assertEqual(self.post().status_code, 200)
        self.owner.refresh_from_db()
        self.assertIsNone(self.owner.pin_locked_until)
        self.assertEqual(self.owner.pin_failed_attempts, 0)

    def send_wrong_pin(self):
        return self.post('/api/wallet/send/', {'receiver_phone': self.other.phone, 'amount': '10', 'pin': '999999'})

    def test_login_lockout_begins_at_threshold_and_expires_in_one_minute(self):
        client = Client()
        now = timezone.now()
        with patch('fundshare_app.services.security_service.timezone.now', return_value=now):
            for _ in range(9):
                self.assertEqual(client.post('/api/auth/login/', {'username': self.owner.username, 'password': 'wrong'}).status_code, 401)
        threshold = now + datetime.timedelta(seconds=20)
        with patch('fundshare_app.services.security_service.timezone.now', return_value=threshold):
            self.assertEqual(client.post('/api/auth/login/', {'username': '+8801750000001', 'password': 'wrong'}).status_code, 401)
        deadline = threshold + datetime.timedelta(seconds=60)
        request = RequestFactory().get('/')
        for key in login_rate_keys(request, self.owner.username):
            self.assertEqual(cache.get(key + ':locked'), deadline.timestamp())
        with patch('fundshare_app.services.security_service.timezone.now', return_value=deadline - datetime.timedelta(seconds=1)):
            result = client.post('/api/auth/login/', {'username': self.owner.username, 'password': 'Owner-password-71!'})
            self.assertEqual(result.status_code, 429)
            self.assertIn('one minute', result.json()['error'])
        with patch('fundshare_app.services.security_service.timezone.now', return_value=deadline):
            self.assertEqual(client.post('/api/auth/login/', {'username': self.owner.username, 'password': 'Owner-password-71!'}).status_code, 200)

    def test_successful_logins_are_not_failed_attempts(self):
        client = Client()
        for _ in range(12):
            self.assertEqual(client.post('/api/auth/login/', {'username': self.owner.username, 'password': 'Owner-password-71!'}).status_code, 200)
        for key in login_rate_keys(RequestFactory().get('/'), self.owner.username):
            self.assertIsNone(cache.get(key + ':failures'))
            self.assertIsNone(cache.get(key + ':locked'))

    def test_success_clears_account_failures_but_not_ip_failures(self):
        client = Client()
        client.post('/api/auth/login/', {'username': self.owner.username, 'password': 'wrong'})
        client.post('/api/auth/login/', {'username': self.owner.username, 'password': 'Owner-password-71!'})
        account_key, ip_key = login_rate_keys(RequestFactory().get('/'), self.owner.username)
        self.assertIsNone(cache.get(account_key + ':failures'))
        self.assertEqual(cache.get(ip_key + ':failures'), 1)

    @override_settings(LOGIN_MAX_FAILED_ATTEMPTS=2, TRANSACTION_PIN_MAX_FAILED_ATTEMPTS=2)
    def test_configured_attempt_thresholds_are_preserved(self):
        request = RequestFactory().get('/')
        record_login_failure(request, self.owner.username)
        check_login_rate(request, self.owner.username)
        record_login_failure(request, self.owner.username)
        with self.assertRaises(SecurityError):
            check_login_rate(request, self.owner.username)
        for _ in range(2):
            with self.assertRaises(SecurityError):
                verify_pin(self.owner, '999999')
        with self.assertRaises(SecurityError) as error:
            verify_pin(self.owner, '482951')
        self.assertEqual(error.exception.code, 'PIN_LOCKED')


class CanonicalPhoneMigrationTests(TransactionTestCase):
    migrate_from = [('fundshare_app', '0008_customer_roles')]

    def setUp(self):
        self.addCleanup(self.restore_schema)
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        self.old_apps = executor.loader.project_state(self.migrate_from).apps
        self.old_user = self.old_apps.get_model('fundshare_app', 'User')

    def restore_schema(self):
        # Remove only this test's legacy fixtures before restoring constraints.
        self.old_user.objects.filter(username__startswith='phone-migration-').delete()
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    def run_normalization(self):
        migration = importlib.import_module('fundshare_app.migrations.0009_canonical_phones_and_lockouts')
        migration.normalize_accounts(self.old_apps, SimpleNamespace(connection=connection))

    def test_migration_preserves_account_identity_credentials_and_wallet(self):
        now = timezone.now()
        account = self.old_user.objects.create(username='phone-migration-valid', phone='+8801712345678', password='existing-hash', transaction_pin='existing-pin', pin_locked_until=now + datetime.timedelta(minutes=5))
        wallet = self.old_apps.get_model('fundshare_app', 'Wallet').objects.create(owner=account, balance=Decimal('123.45'))
        migration = importlib.import_module('fundshare_app.migrations.0009_canonical_phones_and_lockouts')
        with patch.object(migration.timezone, 'now', return_value=now):
            self.run_normalization()
        account.refresh_from_db()
        wallet.refresh_from_db()
        self.assertEqual(account.phone, '01712345678')
        self.assertEqual(account.password, 'existing-hash')
        self.assertEqual(account.transaction_pin, 'existing-pin')
        self.assertEqual(account.pin_locked_until, now + datetime.timedelta(seconds=60))
        self.assertEqual(wallet.balance, Decimal('123.45'))

    def test_duplicate_variants_abort_without_merging_or_partial_updates(self):
        first = self.old_user.objects.create(username='phone-migration-one', phone='+8801712345678')
        second = self.old_user.objects.create(username='phone-migration-two', phone='01712345678')
        with self.assertRaisesRegex(RuntimeError, 'Resolve ownership'):
            self.run_normalization()
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.phone, '+8801712345678')
        self.assertEqual(second.phone, '01712345678')

    def test_invalid_legacy_phone_aborts_without_partial_updates(self):
        first = self.old_user.objects.create(username='phone-migration-one', phone='+8801712345678')
        self.old_user.objects.create(username='phone-migration-invalid', phone='0171110001')
        with self.assertRaisesRegex(RuntimeError, 'invalid phone'):
            self.run_normalization()
        first.refresh_from_db()
        self.assertEqual(first.phone, '+8801712345678')

    def test_blank_legacy_phone_becomes_null(self):
        account = self.old_user.objects.create(username='phone-migration-blank', phone='')
        self.run_normalization()
        account.refresh_from_db()
        self.assertIsNone(account.phone)
