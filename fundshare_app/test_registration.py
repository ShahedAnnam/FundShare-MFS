from decimal import Decimal
from unittest.mock import patch

from django.core.cache import cache
from django.test import Client, TestCase, override_settings

from fundshare_app.forms import RegistrationForm
from fundshare_app.models import User, UserRole, Wallet
from fundshare_app.services.security_service import SecurityError


class RegistrationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.details = {
            'full_name': 'New Wallet Owner', 'username': 'new_owner', 'phone': '01712345678',
            'password1': 'QuietRiver!53927', 'password2': 'QuietRiver!53927',
        }

    def register_api(self, details=None, client=None, **kwargs):
        return (client or self.client).post(
            '/api/auth/register/', self.details if details is None else details,
            content_type='application/json', **kwargs,
        )

    def test_login_links_to_registration_and_registration_links_back(self):
        self.assertContains(self.client.get('/login/'), 'href="/register/"')
        response = self.client.get('/register/')
        self.assertContains(response, 'Create your account')
        self.assertContains(response, 'href="/login/"')
        self.assertIn('csrftoken', self.client.cookies)

    def test_page_creates_account_wallet_and_session(self):
        result = self.client.post('/register/', self.details)
        self.assertRedirects(result, '/', fetch_redirect_response=False)
        user = User.objects.get(username='new_owner')
        self.assertEqual(user.full_name, self.details['full_name'])
        self.assertTrue(user.check_password(self.details['password1']))
        self.assertNotEqual(user.password, self.details['password1'])
        self.assertEqual(user.wallet.balance, Decimal('0.00'))
        self.assertEqual(int(self.client.session['_auth_user_id']), user.pk)
        self.assertEqual(self.client.get('/api/auth/me/').json()['user']['id'], user.pk)

    def test_api_creates_account_without_exposing_credentials(self):
        result = self.register_api()
        self.assertEqual(result.status_code, 201)
        data = result.json()
        self.assertEqual(data['wallet_balance'], 0)
        self.assertEqual(data['role'], UserRole.CUSTOMER)
        self.assertFalse(data['user']['has_transaction_pin'])
        self.assertNotIn('password', data['user'])
        self.assertNotIn('transaction_pin', data['user'])
        self.assertNotIn(self.details['password1'], result.content.decode())
        self.assertEqual(self.client.get('/api/auth/me/').status_code, 200)

    def test_phone_and_username_are_normalized(self):
        result = self.register_api({**self.details, 'username': ' New_Owner ', 'phone': '+880 1712-345678'})
        self.assertEqual(result.status_code, 201)
        user = User.objects.get()
        self.assertEqual(user.username, 'new_owner')
        self.assertEqual(user.phone, '01712345678')

    def test_case_insensitive_existing_username_is_rejected(self):
        User.objects.create_user(username='New_Owner')
        result = self.register_api()
        self.assertEqual(result.status_code, 400)
        self.assertIn('username', result.json()['errors'])
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(Wallet.objects.count(), 0)

    def test_phone_variants_cannot_create_duplicate_accounts(self):
        for existing_phone in ['01712345678', '+8801712345678', '8801712345678', '1712345678']:
            with self.subTest(phone=existing_phone):
                cache.clear()
                existing = User.objects.create_user(username='existing_owner', phone=existing_phone)
                result = self.register_api()
                self.assertEqual(result.status_code, 400)
                self.assertIn('phone', result.json()['errors'])
                self.assertEqual(User.objects.count(), 1)
                existing.delete()

    def test_invalid_or_ambiguous_identifiers_are_rejected(self):
        for field, value in [('phone', '01212345678'), ('phone', 'not-a-phone'), ('username', '01712345678'), ('username', 'invalid user')]:
            with self.subTest(field=field, value=value):
                result = self.register_api({**self.details, field: value})
                self.assertEqual(result.status_code, 400)
                self.assertIn(field, result.json()['errors'])
        self.assertEqual(User.objects.count(), 0)

    def test_password_validation_rejects_short_common_numeric_and_similar_passwords(self):
        for password in ['tiny', 'password123', '239472849', 'new_owner']:
            with self.subTest(password=password):
                result = self.register_api({**self.details, 'password1': password, 'password2': password})
                self.assertEqual(result.status_code, 400)
                self.assertIn('password1', result.json()['errors'])
        self.assertEqual(User.objects.count(), 0)

    def test_password_confirmation_is_required_and_must_match(self):
        for confirmation in ['', 'DifferentPassword!927']:
            result = self.register_api({**self.details, 'password2': confirmation})
            self.assertEqual(result.status_code, 400)
            self.assertIn('password2', result.json()['errors'])
        self.assertEqual(User.objects.count(), 0)

    def test_invalid_page_preserves_only_non_secret_fields(self):
        result = self.client.post('/register/', {**self.details, 'password2': 'DifferentPassword!927'})
        self.assertContains(result, 'The passwords do not match.', status_code=400)
        self.assertContains(result, 'value="new_owner"', status_code=400)
        self.assertContains(result, 'value="01712345678"', status_code=400)
        self.assertNotContains(result, self.details['password1'], status_code=400)
        self.assertNotContains(result, 'DifferentPassword!927', status_code=400)

    def test_signup_cannot_assign_elevated_roles_or_initial_money(self):
        result = self.register_api({
            **self.details, 'role': 'ADMIN', 'is_staff': True, 'is_superuser': True,
            'balance': '1000000', 'transaction_pin': '123456',
        })
        self.assertEqual(result.status_code, 201)
        user = User.objects.get()
        self.assertEqual(user.role, UserRole.CUSTOMER)
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertEqual(user.transaction_pin, '')
        self.assertEqual(user.wallet.balance, Decimal('0.00'))
        self.assertEqual(self.client.get('/api/evaluation/metrics/').status_code, 403)

    def test_account_and_wallet_are_created_atomically(self):
        form = RegistrationForm(self.details)
        self.assertTrue(form.is_valid(), form.errors)
        with patch('fundshare_app.forms.Wallet.objects.create', side_effect=RuntimeError('Wallet unavailable')):
            with self.assertRaises(RuntimeError):
                form.save()
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(Wallet.objects.count(), 0)

    def test_identifier_claimed_after_validation_returns_conflict(self):
        form = RegistrationForm(self.details)
        self.assertTrue(form.is_valid())
        User.objects.create_user(username='new_owner')
        with self.assertRaises(SecurityError) as context:
            form.save()
        self.assertEqual(context.exception.code, 'REGISTRATION_CONFLICT')
        self.assertEqual(context.exception.status, 409)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(Wallet.objects.count(), 0)

    def test_api_conflict_has_clear_message_and_does_not_sign_in(self):
        with patch('fundshare_app.views.api_views.RegistrationForm.save', side_effect=SecurityError('Account already registered.', 'REGISTRATION_CONFLICT', 409)):
            result = self.register_api()
        self.assertEqual(result.status_code, 409)
        self.assertEqual(result.json()['code'], 'REGISTRATION_CONFLICT')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_registration_requires_csrf_on_page_and_api(self):
        for path in ['/register/', '/api/auth/register/']:
            with self.subTest(path=path):
                cache.clear()
                client = Client(enforce_csrf_checks=True)
                self.assertEqual(client.post(path, self.details).status_code, 403)
                client.get('/register/')
                response = client.post(path, self.details, HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
                self.assertIn(response.status_code, [201, 302])
                User.objects.all().delete()

    def test_rate_limit_is_shared_across_page_and_api(self):
        for _ in range(5):
            self.assertEqual(self.client.post('/register/', {}).status_code, 400)
        result = self.register_api()
        self.assertEqual(result.status_code, 429)
        self.assertEqual(result.json()['code'], 'REGISTRATION_RATE_LIMITED')
        self.assertContains(self.client.post('/register/', self.details), 'Too many signup attempts', status_code=429)
        self.assertEqual(User.objects.count(), 0)

    def test_api_rejects_non_object_and_non_text_input(self):
        for payload in [[], {'username': ['new_owner']}, {**self.details, 'phone': 1712345678}, {**self.details, 'password1': None}]:
            self.assertEqual(self.register_api(payload).status_code, 400)
        self.assertEqual(User.objects.count(), 0)

    def test_authenticated_users_cannot_create_or_switch_accounts(self):
        existing = User.objects.create_user(username='existing_owner')
        self.client.force_login(existing)
        self.assertRedirects(self.client.get('/register/'), '/', fetch_redirect_response=False)
        self.assertRedirects(self.client.post('/register/', self.details), '/', fetch_redirect_response=False)
        self.assertEqual(self.register_api().status_code, 409)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(int(self.client.session['_auth_user_id']), existing.pk)

    def test_retrying_signup_cannot_create_a_second_wallet(self):
        self.assertEqual(self.register_api().status_code, 201)
        result = self.register_api(client=Client())
        self.assertEqual(result.status_code, 400)
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(Wallet.objects.count(), 1)

    def test_new_account_can_login_by_username_and_phone(self):
        self.register_api()
        for identifier in ['NEW_OWNER', '+8801712345678']:
            client = Client()
            result = client.post('/api/auth/login/', {'username': identifier, 'password': self.details['password1']})
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()['user']['username'], 'new_owner')

    @override_settings(ENABLE_SIMULATED_CASH_IN=True)
    def test_new_account_must_set_pin_before_financial_actions(self):
        self.register_api()
        result = self.client.post('/api/wallet/cash-in/', {'amount': '10', 'pin': '729485'}, content_type='application/json', HTTP_IDEMPOTENCY_KEY='new-account-cash-in')
        self.assertEqual(result.status_code, 403)
        self.assertEqual(result.json()['code'], 'PIN_NOT_SET')
        self.assertEqual(User.objects.get().wallet.balance, Decimal('0.00'))
        result = self.client.post('/api/auth/pin/', {'password': self.details['password1'], 'new_pin': '729485'}, content_type='application/json')
        self.assertEqual(result.status_code, 200)
        self.assertTrue(User.objects.get().check_transaction_pin('729485'))

    @override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.PBKDF2PasswordHasher'])
    def test_registration_uses_production_password_hasher(self):
        self.assertEqual(self.register_api().status_code, 201)
        user = User.objects.get()
        self.assertTrue(user.password.startswith('pbkdf2_sha256$'))
        self.assertTrue(user.check_password(self.details['password1']))
