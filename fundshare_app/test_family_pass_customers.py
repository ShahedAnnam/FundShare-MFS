import datetime
from decimal import Decimal

from django.contrib.auth.hashers import make_password
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, TestCase, TransactionTestCase
from django.utils import timezone

from fundshare_app.admin import CustomUserCreationForm
from fundshare_app.models import (
    Contact, FamilyPass, FamilyPassStatus, FamilyPassTransaction, PurposeFund,
    Transaction, User, UserRole, Wallet,
)
from fundshare_app.services.contact_service import ContactService
from fundshare_app.services.transaction_service import TransactionService, TransactionValidationError
from fundshare_app.test_security import SecurityFixtures


class CustomerFamilyPassTests(SecurityFixtures, TestCase):
    def test_supported_account_roles_and_admin_choices(self):
        expected = {'CUSTOMER', 'MERCHANT', 'ADMIN'}
        self.assertEqual(set(UserRole.values), expected)
        self.assertEqual(set(dict(CustomUserCreationForm().fields['role'].choices)) - {''}, expected)
        with transaction.atomic():
            with self.assertRaises(IntegrityError):
                User.objects.filter(pk=self.other.pk).update(role='UNSUPPORTED')

    def test_role_is_static_and_does_not_query_family_passes(self):
        with self.assertNumQueries(0):
            self.assertEqual(self.member.effective_role, UserRole.CUSTOMER)
        self.assertEqual(User.objects.get(pk=self.member.pk).role, UserRole.CUSTOMER)
        self.member.is_superuser = True
        self.assertEqual(self.member.effective_role, UserRole.ADMIN)
        self.assertEqual(self.merchant_user.effective_role, UserRole.MERCHANT)
        self.assertEqual(self.admin.effective_role, UserRole.ADMIN)

    def test_customer_can_share_receive_manage_own_funds_and_use_both_balances(self):
        self.client.force_login(self.member)
        issued = self.post('/api/family-pass/', {
            'member': self.owner.phone, 'limit_amount': '80', 'purpose': 'Grocery',
        })
        self.assertEqual(issued.status_code, 201, issued.content)
        data = self.client.get('/api/family-pass/').json()
        self.assertEqual([p['id'] for p in data['issued_passes']], [issued.json()['id']])
        self.assertEqual([p['id'] for p in data['received_passes']], [self.family_pass.pk])
        self.assertEqual(data['effective_role'], UserRole.CUSTOMER)

        created = self.post('/api/funds/', {
            'name': 'My own grocery fund', 'category': 'Grocery', 'allocated_amount': '100', 'pin': '482951',
        })
        self.assertEqual(created.status_code, 201, created.content)
        own_fund = PurposeFund.objects.get(pk=created.json()['id'])
        self.assertEqual(own_fund.owner_id, self.member.pk)
        edited = self.client.patch(f'/api/funds/{own_fund.pk}/', {'name': 'My renamed fund'}, content_type='application/json')
        self.assertEqual(edited.status_code, 200, edited.content)
        own_payment = self.post('/api/pay/', {
            'merchant_id': self.merchant.pk, 'amount': '20', 'payment_source': 'PURPOSE_FUND',
            'purpose_fund_id': own_fund.pk, 'pin': '482951',
        })
        self.assertEqual(own_payment.status_code, 200, own_payment.content)
        own_fund.refresh_from_db()
        self.assertEqual(own_fund.current_balance, Decimal('80.00'))

        received_payment = self.post('/api/pay/', {
            'merchant_id': self.merchant.pk, 'amount': '25', 'payment_source': 'FAMILY_PASS',
            'family_pass_id': self.family_pass.pk, 'pin': '482951',
        })
        self.assertEqual(received_payment.status_code, 200, received_payment.content)
        self.assertEqual(Wallet.objects.get(owner=self.member).balance, Decimal('900.00'))
        self.assertEqual(Wallet.objects.get(owner=self.owner).balance, Decimal('975.00'))

        self.client.force_login(self.owner)
        reciprocal_payment = self.post('/api/pay/', {
            'merchant_id': self.merchant.pk, 'amount': '40', 'payment_source': 'FAMILY_PASS',
            'family_pass_id': issued.json()['id'], 'pin': '482951',
        })
        self.assertEqual(reciprocal_payment.status_code, 200, reciprocal_payment.content)
        self.assertEqual(Wallet.objects.get(owner=self.member).balance, Decimal('860.00'))
        self.assertEqual(Wallet.objects.get(owner=self.owner).balance, Decimal('975.00'))
        for user in [self.owner, self.member]:
            user.refresh_from_db()
            self.assertEqual(user.role, UserRole.CUSTOMER)
            self.assertEqual(user.effective_role, UserRole.CUSTOMER)

    def test_pass_lifecycle_never_changes_role_or_normal_wallet_access(self):
        self.client.force_login(self.member)
        for index, status in enumerate([FamilyPassStatus.ACTIVE, FamilyPassStatus.REVOKED, FamilyPassStatus.EXPIRED]):
            with self.subTest(status=status):
                self.family_pass.status = status
                self.family_pass.save(update_fields=['status'])
                self.assertEqual(User.objects.get(pk=self.member.pk).role, UserRole.CUSTOMER)
                me = self.client.get('/api/auth/me/').json()
                self.assertEqual(me['role'], UserRole.CUSTOMER)
                self.assertEqual(me['user']['role'], UserRole.CUSTOMER)
                result = self.post('/api/funds/', {
                    'name': f'Own fund {index}', 'category': 'Grocery', 'allocated_amount': '10', 'pin': '482951',
                })
                self.assertEqual(result.status_code, 201, result.content)
        self.family_pass.delete()
        self.assertEqual(self.client.get('/api/auth/me/').json()['role'], UserRole.CUSTOMER)
        self.assertEqual(self.client.get('/api/funds/').status_code, 200)

    def test_revocation_response_and_notifications_do_not_describe_role_changes(self):
        response = self.post(f'/api/family-pass/{self.family_pass.pk}/revoke/', {})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('member_effective_role', response.json())
        self.assertNotIn('member_new_role', self.member.notifications.latest('pk').metadata)
        self.assertEqual(User.objects.get(pk=self.member.pk).role, UserRole.CUSTOMER)

    def test_non_customer_and_inactive_accounts_cannot_receive_a_pass(self):
        self.other.is_active = False
        self.other.save(update_fields=['is_active'])
        for recipient in [self.admin, self.merchant_user, self.other]:
            with self.subTest(recipient=recipient.username):
                result = self.post('/api/family-pass/', {'member': recipient.phone, 'limit_amount': '100', 'purpose': 'Grocery'})
                self.assertEqual(result.status_code, 400)
                expected = 'active customer' if recipient.is_active else 'inactive'
                self.assertIn(expected, result.json()['error'])
                self.assertFalse(FamilyPass.objects.filter(member=recipient).exists())
        self.assertEqual(FamilyPass.objects.count(), 1)

    def test_only_customers_have_family_pass_endpoints(self):
        for user in [self.admin, self.merchant_user]:
            self.client.force_login(user)
            for path in ['/api/family-pass/', '/api/familypass/recipients/', f'/api/family-pass/{self.family_pass.pk}/', f'/api/family-pass/{self.family_pass.pk}/activity/']:
                self.assertEqual(self.client.get(path).status_code, 403, path)
            self.assertEqual(self.post('/api/family-pass/', {'member': self.member.phone, 'limit_amount': '10'}).status_code, 403)
        self.assertEqual(self.admin.effective_role, UserRole.ADMIN)
        self.assertEqual(self.merchant_user.effective_role, UserRole.MERCHANT)

    def test_recipient_list_uses_role_not_username_and_keeps_legacy_url_compatible(self):
        self.other.is_active = False
        self.other.save(update_fields=['is_active'])
        customer_named_admin = User.objects.create_user(username='admin', role=UserRole.CUSTOMER)
        hidden_superuser = User.objects.create_user(username='root', role=UserRole.CUSTOMER, is_superuser=True)
        response = self.client.get('/api/familypass/recipients/')
        identifiers = {user['id'] for user in response.json()}
        self.assertEqual(identifiers, {self.member.pk, customer_named_admin.pk})
        self.assertNotIn(hidden_superuser.pk, identifiers)
        self.assertEqual(self.client.get('/api/familypass/members-list/').json(), response.json())

    def test_contact_eligibility_agrees_with_family_pass_permissions(self):
        self.member.phone = '01712345001'
        self.member.save(update_fields=['phone'])
        self.merchant_user.phone = '01712345002'
        self.merchant_user.save(update_fields=['phone'])
        for recipient, expected in [(self.member, True), (self.merchant_user, False)]:
            contact = Contact.objects.create(owner=self.owner, name=recipient.username, phone=recipient.phone)
            data = ContactService.get_contact_account_info(contact)
            self.assertEqual(data['allowed_features']['family_pass'], expected)
            is_eligible, _, matched = ContactService.check_recipient_eligibility(recipient.phone, 'FAMILY_PASS')
            self.assertEqual(is_eligible, expected)
            self.assertEqual(matched.pk, recipient.pk)

    def test_pass_owner_must_remain_an_active_customer_to_fund_payments(self):
        for role, active in [(UserRole.MERCHANT, True), (UserRole.ADMIN, True), (UserRole.CUSTOMER, False)]:
            with self.subTest(role=role, active=active):
                User.objects.filter(pk=self.owner.pk).update(role=role, is_active=active)
                with self.assertRaises(TransactionValidationError) as error:
                    TransactionService.execute_transaction(
                        sender=self.member, transaction_type='MERCHANT_PAYMENT', amount=Decimal('10'),
                        merchant=self.merchant, payment_source='FAMILY_PASS', family_pass=self.family_pass,
                    )
                self.assertEqual(error.exception.code, 'FAMILYPASS_ACCOUNT_INELIGIBLE')
        self.assertEqual(Wallet.objects.get(owner=self.owner).balance, Decimal('1000.00'))
        self.assertEqual(Transaction.objects.count(), 0)

    def test_future_pass_is_a_permission_not_an_active_role(self):
        self.family_pass.start_date = timezone.localdate() + datetime.timedelta(days=1)
        self.family_pass.save(update_fields=['start_date'])
        self.client.force_login(self.member)
        me = self.client.get('/api/auth/me/').json()
        self.assertEqual(me['received_family_passes_count'], 0)
        self.assertEqual(me['role'], UserRole.CUSTOMER)
        result = self.post('/api/pay/', {
            'merchant_id': self.merchant.pk, 'amount': '10', 'payment_source': 'FAMILY_PASS',
            'family_pass_id': self.family_pass.pk, 'pin': '482951',
        })
        self.assertEqual(result.json()['code'], 'FAMILYPASS_NOT_STARTED')


class CustomerRoleMigrationTests(TransactionTestCase):
    migrate_from = [('fundshare_app', '0007_authentication_and_transaction_safety')]
    migrate_to = [('fundshare_app', '0008_customer_roles')]

    def setUp(self):
        self.addCleanup(self.restore_schema)
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        self.old_apps = executor.loader.project_state(self.migrate_from).apps

    def restore_schema(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    def test_legacy_customer_conversion_preserves_credentials_balances_and_delegations(self):
        OldUser = self.old_apps.get_model('fundshare_app', 'User')
        OldWallet = self.old_apps.get_model('fundshare_app', 'Wallet')
        OldPass = self.old_apps.get_model('fundshare_app', 'FamilyPass')
        OldFund = self.old_apps.get_model('fundshare_app', 'PurposeFund')
        OldTransaction = self.old_apps.get_model('fundshare_app', 'Transaction')
        OldPassTransaction = self.old_apps.get_model('fundshare_app', 'FamilyPassTransaction')
        password = make_password('Migration-password-71!')
        pin = make_password('482951')
        recipient = OldUser.objects.create(username='legacy-recipient', role='MEMBER', password=password, transaction_pin=pin, phone='01711112222')
        owner = OldUser.objects.create(username='legacy-owner', role='CUSTOMER')
        merchant = OldUser.objects.create(username='legacy-merchant', role='MERCHANT')
        admin = OldUser.objects.create(username='legacy-admin', role='ADMIN', is_staff=True)
        wallet = OldWallet.objects.create(owner=recipient, balance=Decimal('1234.56'))
        fund = OldFund.objects.create(owner=recipient, name='Personal Grocery', category='Grocery', current_balance=Decimal('50.00'))
        family_pass = OldPass.objects.create(owner=owner, member=recipient, limit_amount=Decimal('100.00'), used_amount=Decimal('25.00'), expiry_date=timezone.localdate() + datetime.timedelta(days=30))
        payment = OldTransaction.objects.create(sender=recipient, amount=Decimal('25.00'), transaction_type='MERCHANT_PAYMENT', payment_source='FAMILY_PASS', family_pass=family_pass, transaction_id='migration-payment')
        activity = OldPassTransaction.objects.create(member=recipient, family_pass=family_pass, transaction=payment, amount=Decimal('25.00'), remaining_limit_after=Decimal('75.00'))

        MigrationExecutor(connection).migrate(self.migrate_to)

        migrated = User.objects.get(pk=recipient.pk)
        self.assertEqual(migrated.role, UserRole.CUSTOMER)
        self.assertEqual(migrated.password, password)
        self.assertEqual(migrated.transaction_pin, pin)
        self.assertEqual(migrated.phone, '01711112222')
        self.assertEqual(Wallet.objects.get(pk=wallet.pk).balance, Decimal('1234.56'))
        self.assertEqual(PurposeFund.objects.get(pk=fund.pk).owner_id, recipient.pk)
        self.assertEqual(PurposeFund.objects.get(pk=fund.pk).current_balance, Decimal('50.00'))
        migrated_pass = FamilyPass.objects.get(pk=family_pass.pk)
        self.assertEqual(migrated_pass.member_id, recipient.pk)
        self.assertEqual(migrated_pass.used_amount, Decimal('25.00'))
        self.assertEqual(migrated_pass.remaining_limit, Decimal('75.00'))
        self.assertEqual(Transaction.objects.get(pk=payment.pk).family_pass_id, family_pass.pk)
        self.assertEqual(FamilyPassTransaction.objects.get(pk=activity.pk).transaction_id, payment.pk)
        self.assertEqual(User.objects.get(pk=merchant.pk).role, UserRole.MERCHANT)
        self.assertEqual(User.objects.get(pk=admin.pk).role, UserRole.ADMIN)
