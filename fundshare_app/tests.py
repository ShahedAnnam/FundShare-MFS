from decimal import Decimal
import datetime
from django.test import TestCase, Client
from django.utils import timezone
from django.contrib.auth import get_user_model
from fundshare_app.models import (
    UserRole, BusinessCategory, Wallet, Merchant, PurposeFund,
    FamilyPass, FamilyPassStatus, FamilyPassAction,
    Transaction, TransactionItem, FamilyPassTransaction,
    TransactionType, PaymentSource, TransactionStatus,
    Notification, Contact, FundStatus
)
from fundshare_app.services.transaction_service import TransactionService, TransactionValidationError
from fundshare_app.services.contact_service import ContactService
from fundshare_app.services.phone_utils import normalize_phone, find_user_by_phone_or_username, is_valid_bd_phone
from fundshare_app.ml.anomaly_detector import AnomalyDetector
from fundshare_app.ml.budget_forecaster import BudgetForecaster

User = get_user_model()



class FundShareCoreBusinessRulesTest(TestCase):
    def setUp(self):
        # Create Owner
        self.owner = User.objects.create_user(
            username='shahed_test',
            email='shahed@test.com',
            phone='01700000001',
            role=UserRole.CUSTOMER,
            password='password123'
        )
        self.owner_wallet = Wallet.objects.create(owner=self.owner, balance=Decimal('20000.00'))

        # Create Family Member
        self.member = User.objects.create_user(
            username='rahim_test',
            full_name='Rahim Ahmed',
            email='rahim@test.com',
            phone='01800000002',
            role=UserRole.MEMBER,
            password='password123'
        )
        self.member_wallet = Wallet.objects.create(owner=self.member, balance=Decimal('500.00'))

        # Create Imposter User
        self.imposter = User.objects.create_user(
            username='imposter_test',
            phone='01900000003',
            role=UserRole.MEMBER,
            password='password123'
        )

        # Create Purpose Funds for Owner
        self.grocery_fund = PurposeFund.objects.create(
            owner=self.owner,
            name='Grocery',
            category=BusinessCategory.GROCERY,
            allocated_amount=Decimal('15000.00'),
            current_balance=Decimal('8000.00'),
            monthly_budget=Decimal('15000.00')
        )

        self.education_fund = PurposeFund.objects.create(
            owner=self.owner,
            name='Education',
            category=BusinessCategory.EDUCATION,
            allocated_amount=Decimal('10000.00'),
            current_balance=Decimal('10000.00'),
            monthly_budget=Decimal('10000.00')
        )

        # Create Merchants
        self.grocery_merchant = Merchant.objects.create(
            business_name='Agora Super Shop Test',
            category=BusinessCategory.GROCERY,
            account_number='AGR-TEST-01',
            balance=Decimal('0.00')
        )

        self.education_merchant = Merchant.objects.create(
            business_name='Scholastica Test',
            category=BusinessCategory.EDUCATION,
            account_number='SCH-TEST-01',
            balance=Decimal('0.00')
        )

        # Create FamilyPass for Rahim
        today = timezone.localdate() if timezone.is_aware(timezone.now()) else timezone.now().date()
        self.family_pass = FamilyPass.objects.create(
            owner=self.owner,
            member=self.member,
            limit_amount=Decimal('3000.00'),
            used_amount=Decimal('1000.00'),
            start_date=today - datetime.timedelta(days=5),
            expiry_date=today + datetime.timedelta(days=25),
            allowed_action=FamilyPassAction.MERCHANT_PAYMENT,
            status=FamilyPassStatus.ACTIVE,
            purpose_label='Monthly Allowance'
        )

    # ------------------ TEST 1: CATEGORY RESTRICTION ------------------
    def test_purpose_fund_matching_category_allowed(self):
        """
        Paying a Grocery Merchant using a Grocery Fund must succeed and debit the purpose fund.
        """
        initial_fund_bal = self.grocery_fund.current_balance
        amt = Decimal('1200.00')

        txn = TransactionService.execute_transaction(
            sender=self.owner,
            merchant=self.grocery_merchant,
            amount=amt,
            transaction_type=TransactionType.MERCHANT_PAYMENT,
            payment_source=PaymentSource.PURPOSE_FUND,
            purpose_fund=self.grocery_fund
        )

        self.assertEqual(txn.status, TransactionStatus.COMPLETED)
        self.grocery_fund.refresh_from_db()
        self.assertEqual(self.grocery_fund.current_balance, initial_fund_bal - amt)
        self.grocery_merchant.refresh_from_db()
        self.assertEqual(self.grocery_merchant.balance, amt)

    def test_purpose_fund_category_mismatch_denied(self):
        """
        Paying a Grocery Merchant using an Education Fund must be strictly REJECTED by backend business rules.
        """
        with self.assertRaises(TransactionValidationError) as ctx:
            TransactionService.execute_transaction(
                sender=self.owner,
                merchant=self.grocery_merchant,
                amount=Decimal('1500.00'),
                transaction_type=TransactionType.MERCHANT_PAYMENT,
                payment_source=PaymentSource.PURPOSE_FUND,
                purpose_fund=self.education_fund
            )

        self.assertEqual(ctx.exception.code, "CATEGORY_RESTRICTION_ERROR")
        self.assertIn("Category Restriction Mismatch", ctx.exception.message)

        # Verify fund was NOT debited
        self.education_fund.refresh_from_db()
        self.assertEqual(self.education_fund.current_balance, Decimal('10000.00'))

        # Verify rejected transaction was logged for audit
        rejected_txn = Transaction.objects.filter(sender=self.owner, status=TransactionStatus.REJECTED).first()
        self.assertIsNotNone(rejected_txn)
        self.assertIn("Agora Super Shop Test", rejected_txn.rejection_reason)

    # ------------------ TEST 2: FAMILYPASS SECURITY ------------------
    def test_familypass_authorized_spending_success(self):
        """
        Member spends within remaining limit:
        - Owner's wallet balance debited
        - FamilyPass used_amount incremented
        - Member does NOT use owner's PIN or credentials
        - Simulated alert triggered to owner
        """
        amt = Decimal('450.00')
        owner_initial_wallet = self.owner_wallet.balance
        fp_initial_used = self.family_pass.used_amount

        txn = TransactionService.execute_transaction(
            sender=self.member,
            merchant=self.grocery_merchant,
            amount=amt,
            transaction_type=TransactionType.MERCHANT_PAYMENT,
            payment_source=PaymentSource.FAMILY_PASS,
            family_pass=self.family_pass
        )

        self.assertEqual(txn.status, TransactionStatus.COMPLETED)

        # Check owner wallet was debited
        self.owner_wallet.refresh_from_db()
        self.assertEqual(self.owner_wallet.balance, owner_initial_wallet - amt)

        # Check FamilyPass used_amount incremented
        self.family_pass.refresh_from_db()
        self.assertEqual(self.family_pass.used_amount, fp_initial_used + amt)
        self.assertEqual(self.family_pass.remaining_limit, Decimal('3000.00') - (fp_initial_used + amt))

        # Verify instant owner notification
        owner_notif = Notification.objects.filter(user=self.owner, notification_type='FAMILY_PASS').first()
        self.assertIsNotNone(owner_notif)
        self.assertIn("Rahim", owner_notif.message)
        self.assertIn("450", owner_notif.message)

    def test_familypass_limit_exceeded_denied(self):
        """
        Member attempting to spend more than remaining limit must be denied.
        """
        # Remaining limit is 2,000 (3,000 limit - 1,000 used)
        excess_amt = Decimal('2500.00')

        with self.assertRaises(TransactionValidationError) as ctx:
            TransactionService.execute_transaction(
                sender=self.member,
                merchant=self.grocery_merchant,
                amount=excess_amt,
                transaction_type=TransactionType.MERCHANT_PAYMENT,
                payment_source=PaymentSource.FAMILY_PASS,
                family_pass=self.family_pass
            )

        self.assertEqual(ctx.exception.code, "FAMILYPASS_LIMIT_EXCEEDED")

    def test_familypass_unauthorized_member_denied(self):
        """
        An imposter member attempting to spend from another person's FamilyPass must be rejected.
        """
        with self.assertRaises(TransactionValidationError) as ctx:
            TransactionService.execute_transaction(
                sender=self.imposter,
                merchant=self.grocery_merchant,
                amount=Decimal('200.00'),
                transaction_type=TransactionType.MERCHANT_PAYMENT,
                payment_source=PaymentSource.FAMILY_PASS,
                family_pass=self.family_pass
            )

        self.assertEqual(ctx.exception.code, "FAMILYPASS_UNAUTHORIZED")

    def test_familypass_revoked_denied(self):
        """
        A revoked FamilyPass must immediately block any further spending.
        """
        self.family_pass.status = FamilyPassStatus.REVOKED
        self.family_pass.save()

        with self.assertRaises(TransactionValidationError) as ctx:
            TransactionService.execute_transaction(
                sender=self.member,
                merchant=self.grocery_merchant,
                amount=Decimal('100.00'),
                transaction_type=TransactionType.MERCHANT_PAYMENT,
                payment_source=PaymentSource.FAMILY_PASS,
                family_pass=self.family_pass
            )

        self.assertEqual(ctx.exception.code, "FAMILYPASS_INACTIVE")

    # ------------------ TEST 3: INTER-FUND TRANSFER ------------------
    def test_interfund_transfer_explicit_action(self):
        """
        Customer explicitly moves ৳1,000 between their own purpose funds.
        """
        transfer = TransactionService.transfer_between_funds(
            user=self.owner,
            source_fund=self.education_fund,
            destination_fund=self.grocery_fund,
            amount=Decimal('1000.00'),
            reason="Balancing budget"
        )

        self.education_fund.refresh_from_db()
        self.grocery_fund.refresh_from_db()

        self.assertEqual(self.education_fund.current_balance, Decimal('9000.00'))
        self.assertEqual(self.grocery_fund.current_balance, Decimal('9000.00'))
        self.assertEqual(transfer.amount, Decimal('1000.00'))

    # ------------------ TEST 4: ANOMALY DETECTION ML ------------------
    def test_anomaly_detection_flags_outlier(self):
        """
        Anomalously high grocery transaction (৳8,500 vs normal ~৳850) should be flagged.
        """
        detector = AnomalyDetector.get_instance()

        normal_txn = Transaction.objects.create(
            sender=self.owner,
            merchant=self.grocery_merchant,
            amount=Decimal('650.00'),
            category=BusinessCategory.GROCERY,
            transaction_type=TransactionType.MERCHANT_PAYMENT
        )
        normal_analysis = detector.analyze_transaction(normal_txn)
        self.assertFalse(normal_analysis['is_anomaly'])

        unusual_txn = Transaction.objects.create(
            sender=self.owner,
            merchant=self.grocery_merchant,
            amount=Decimal('8500.00'),
            category=BusinessCategory.GROCERY,
            transaction_type=TransactionType.MERCHANT_PAYMENT
        )
        unusual_analysis = detector.analyze_transaction(unusual_txn)
        self.assertTrue(unusual_analysis['is_anomaly'])
        self.assertIn("higher than your typical", unusual_analysis['reason'])


class ContactBookAndRecipientEligibilityTest(TestCase):
    def setUp(self):
        # 1. User A (Mimmi)
        self.user_a = User.objects.create_user(
            username='mimmi',
            email='mimmi@test.com',
            phone='01711111100',
            full_name='Mimmi Khan',
            role=UserRole.CUSTOMER,
            password='password123'
        )
        self.wallet_a = Wallet.objects.create(owner=self.user_a, balance=Decimal('10000.00'))

        # 2. User B (Huma - Registered account)
        self.user_b = User.objects.create_user(
            username='huma',
            email='huma@test.com',
            phone='01711111111',
            full_name='Huma Akter',
            role=UserRole.CUSTOMER,
            password='password123'
        )
        self.wallet_b = Wallet.objects.create(owner=self.user_b, balance=Decimal('2000.00'))

        # 3. User C (Independent User)
        self.user_c = User.objects.create_user(
            username='karim_user',
            email='karim@test.com',
            phone='01822222222',
            full_name='Karim User',
            role=UserRole.CUSTOMER,
            password='password123'
        )
        self.wallet_c = Wallet.objects.create(owner=self.user_c, balance=Decimal('1000.00'))

        # Unregistered phone (Husa)
        self.unregistered_phone = '01933333333'

        # Clients
        self.client_a = Client()
        self.client_a.force_login(self.user_a)

        self.client_b = Client()
        self.client_b.force_login(self.user_b)

    # 1. User can create contact
    def test_01_user_can_create_contact(self):
        resp = self.client_a.post('/api/contacts/', {
            'name': 'Huma',
            'phone': '01711111111',
            'username': 'huma'
        }, content_type='application/json')
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(Contact.objects.filter(owner=self.user_a, phone='01711111111').exists())
        self.assertEqual(resp.data['account_status'], 'REGISTERED')

    # 2. User can list own contacts
    def test_02_user_can_list_own_contacts(self):
        Contact.objects.create(owner=self.user_a, name='Huma', phone='01711111111')
        Contact.objects.create(owner=self.user_a, name='Husa', phone=self.unregistered_phone)
        Contact.objects.create(owner=self.user_b, name='Other Contact', phone='01800000000')

        resp = self.client_a.get('/api/contacts/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 2)
        phones = [c['phone'] for c in resp.data]
        self.assertIn('01711111111', phones)
        self.assertIn('01933333333', phones)
        self.assertNotIn('01800000000', phones)

    # 3. User can edit own contact
    def test_03_user_can_edit_own_contact(self):
        c = Contact.objects.create(owner=self.user_a, name='Huma', phone='01711111111')
        resp = self.client_a.patch(f'/api/contacts/{c.id}/', {
            'name': 'Huma Sister',
            'phone': '01711111112'
        }, content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        c.refresh_from_db()
        self.assertEqual(c.name, 'Huma Sister')
        self.assertEqual(c.phone, '01711111112')

    # 4. User can delete own contact
    def test_04_user_can_delete_own_contact(self):
        c = Contact.objects.create(owner=self.user_a, name='Huma', phone='01711111111')
        resp = self.client_a.delete(f'/api/contacts/{c.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Contact.objects.filter(id=c.id).exists())

    # 5. User cannot access another user's contact
    def test_05_user_cannot_access_another_users_contact(self):
        c_a = Contact.objects.create(owner=self.user_a, name='Private A', phone='01711111111')
        resp = self.client_b.get(f'/api/contacts/{c_a.id}/')
        self.assertEqual(resp.status_code, 404)

    # 6. User cannot edit another user's contact
    def test_06_user_cannot_edit_another_users_contact(self):
        c_a = Contact.objects.create(owner=self.user_a, name='Private A', phone='01711111111')
        resp = self.client_b.patch(f'/api/contacts/{c_a.id}/', {'name': 'Hacked'}, content_type='application/json')
        self.assertEqual(resp.status_code, 404)
        c_a.refresh_from_db()
        self.assertEqual(c_a.name, 'Private A')

    # 7. User cannot delete another user's contact
    def test_07_user_cannot_delete_another_users_contact(self):
        c_a = Contact.objects.create(owner=self.user_a, name='Private A', phone='01711111111')
        resp = self.client_b.delete(f'/api/contacts/{c_a.id}/')
        self.assertEqual(resp.status_code, 404)
        self.assertTrue(Contact.objects.filter(id=c_a.id).exists())

    # 8. Contact correctly identifies registered account
    def test_08_contact_correctly_identifies_registered_account(self):
        c = Contact.objects.create(owner=self.user_a, name='Huma', phone='01711111111')
        info = ContactService.get_contact_account_info(c)
        self.assertTrue(info['is_registered'])
        self.assertEqual(info['account_status'], 'REGISTERED')
        self.assertEqual(info['username'], 'huma')
        self.assertEqual(info['account_id'], self.user_b.id)
        self.assertTrue(info['allowed_features']['send_money'])
        self.assertTrue(info['allowed_features']['fund_share'])
        self.assertTrue(info['allowed_features']['mobile_recharge'])

    # 9. Contact correctly identifies unregistered phone
    def test_09_contact_correctly_identifies_unregistered_phone(self):
        c = Contact.objects.create(owner=self.user_a, name='Husa', phone=self.unregistered_phone)
        info = ContactService.get_contact_account_info(c)
        self.assertFalse(info['is_registered'])
        self.assertEqual(info['account_status'], 'NOT_REGISTERED')
        self.assertIsNone(info['account_id'])
        self.assertFalse(info['allowed_features']['send_money'])
        self.assertFalse(info['allowed_features']['fund_share'])
        self.assertTrue(info['allowed_features']['mobile_recharge'])

    # 10. Registered contact can receive Send Money
    def test_10_registered_contact_can_receive_send_money(self):
        resp = self.client_a.post('/api/wallet/send/', {
            'receiver': '01711111111',
            'amount': '500.00',
            'reference': 'Gift for Huma'
        }, content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        self.wallet_a.refresh_from_db()
        self.wallet_b.refresh_from_db()
        self.assertEqual(self.wallet_a.balance, Decimal('9500.00'))
        self.assertEqual(self.wallet_b.balance, Decimal('2500.00'))

    # 11. Unregistered contact cannot receive Send Money
    def test_11_unregistered_contact_cannot_receive_send_money(self):
        resp = self.client_a.post('/api/wallet/send/', {
            'receiver': self.unregistered_phone,
            'amount': '500.00',
            'reference': 'To Unregistered'
        }, content_type='application/json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn("registered account", resp.data['error'].lower())

    # 12. Backend rejects Send Money to unregistered recipient
    def test_12_backend_rejects_send_money_to_unregistered_recipient(self):
        is_eligible, err_msg, matched_user = ContactService.check_recipient_eligibility(
            self.unregistered_phone,
            feature='SEND_MONEY'
        )
        self.assertFalse(is_eligible)
        self.assertIn("registered account", err_msg.lower())
        self.assertIsNone(matched_user)

    # 13. Registered contact can be selected for FundShare
    def test_13_registered_contact_can_be_selected_for_fundshare(self):
        resp = self.client_a.post('/api/funds/', {
            'name': 'Huma Grocery Fund',
            'category': 'Grocery',
            'allocated_amount': '1000.00',
            'monthly_budget': '2000.00',
            'recipient': '01711111111'
        }, content_type='application/json')
        self.assertEqual(resp.status_code, 201)
        fund = PurposeFund.objects.get(name='Huma Grocery Fund')
        self.assertEqual(fund.recipient, self.user_b)

    # 14. Unregistered contact cannot receive FundShare
    def test_14_unregistered_contact_cannot_receive_fundshare(self):
        resp = self.client_a.post('/api/funds/', {
            'name': 'Husa Fund',
            'category': 'Grocery',
            'allocated_amount': '500.00',
            'monthly_budget': '1000.00',
            'recipient': self.unregistered_phone
        }, content_type='application/json')
        self.assertEqual(resp.status_code, 400)
        self.assertIn("registered account", resp.data['error'].lower())

    # 15. Backend rejects FundShare to unregistered recipient
    def test_15_backend_rejects_fundshare_to_unregistered_recipient(self):
        is_eligible, err_msg, matched_user = ContactService.check_recipient_eligibility(
            self.unregistered_phone,
            feature='FUND_SHARE'
        )
        self.assertFalse(is_eligible)
        self.assertIn("registered account", err_msg.lower())

    # 16. Registered contact can be recharged
    def test_16_registered_contact_can_be_recharged(self):
        resp = self.client_a.post('/api/wallet/utility/', {
            'action_type': 'RECHARGE',
            'amount': '100.00',
            'reference': 'Recharge for Huma: 01711111111'
        }, content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        self.wallet_a.refresh_from_db()
        self.assertEqual(self.wallet_a.balance, Decimal('9900.00'))

    # 17. Unregistered contact can also be recharged
    def test_17_unregistered_contact_can_also_be_recharged(self):
        is_eligible, err_msg, _ = ContactService.check_recipient_eligibility(
            self.unregistered_phone,
            feature='MOBILE_RECHARGE'
        )
        self.assertTrue(is_eligible)
        self.assertIsNone(err_msg)

        resp = self.client_a.post('/api/wallet/utility/', {
            'action_type': 'RECHARGE',
            'amount': '50.00',
            'reference': f'Recharge for Husa: {self.unregistered_phone}'
        }, content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        self.wallet_a.refresh_from_db()
        self.assertEqual(self.wallet_a.balance, Decimal('9950.00'))

    # 18. Owner can edit own fund
    def test_18_owner_can_edit_own_fund(self):
        fund = PurposeFund.objects.create(
            owner=self.user_a,
            name='Original Fund',
            category='Education',
            allocated_amount=Decimal('3000.00'),
            current_balance=Decimal('3000.00'),
            monthly_budget=Decimal('3000.00')
        )
        resp = self.client_a.patch(f'/api/funds/{fund.id}/', {
            'name': 'Updated Education Fund',
            'monthly_budget': '5000.00'
        }, content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        fund.refresh_from_db()
        self.assertEqual(fund.name, 'Updated Education Fund')
        self.assertEqual(fund.monthly_budget, Decimal('5000.00'))

    # 19. Owner can delete/archive own fund
    def test_19_owner_can_delete_archive_own_fund(self):
        fund = PurposeFund.objects.create(
            owner=self.user_a,
            name='Temporary Fund',
            category='Shopping',
            allocated_amount=Decimal('1000.00'),
            current_balance=Decimal('1000.00'),
            monthly_budget=Decimal('1000.00')
        )
        initial_wallet = self.wallet_a.balance
        resp = self.client_a.delete(f'/api/funds/{fund.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(PurposeFund.objects.filter(id=fund.id).exists())
        self.wallet_a.refresh_from_db()
        # Remaining balance returned to wallet
        self.assertEqual(self.wallet_a.balance, initial_wallet + Decimal('1000.00'))

    # 20. Another user cannot edit/delete the fund
    def test_20_another_user_cannot_edit_delete_fund(self):
        fund_a = PurposeFund.objects.create(
            owner=self.user_a,
            name='User A Private Fund',
            category='Rent',
            allocated_amount=Decimal('5000.00'),
            current_balance=Decimal('5000.00'),
            monthly_budget=Decimal('5000.00')
        )
        resp_edit = self.client_b.patch(f'/api/funds/{fund_a.id}/', {'name': 'Hacked Fund'}, content_type='application/json')
        self.assertEqual(resp_edit.status_code, 404)

        resp_del = self.client_b.delete(f'/api/funds/{fund_a.id}/')
        self.assertEqual(resp_del.status_code, 404)
        self.assertTrue(PurposeFund.objects.filter(id=fund_a.id).exists())

    # 21. Existing transaction history is not accidentally destroyed
    def test_21_existing_transaction_history_is_not_accidentally_destroyed(self):
        fund = PurposeFund.objects.create(
            owner=self.user_a,
            name='Medical Fund With History',
            category='Medicine',
            allocated_amount=Decimal('4000.00'),
            current_balance=Decimal('3500.00'),
            monthly_budget=Decimal('4000.00')
        )
        # Create a transaction associated with this fund
        txn = Transaction.objects.create(
            transaction_id='TXN-HIST-001',
            sender=self.user_a,
            amount=Decimal('500.00'),
            transaction_type=TransactionType.MERCHANT_PAYMENT,
            payment_source=PaymentSource.PURPOSE_FUND,
            purpose_fund=fund,
            category='Medicine',
            status=TransactionStatus.COMPLETED
        )

        resp = self.client_a.delete(f'/api/funds/{fund.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['status'], 'archived')

        # Fund must NOT be deleted from DB; it must be ARCHIVED to preserve FK integrity
        fund.refresh_from_db()
        self.assertEqual(fund.status, FundStatus.ARCHIVED)

        # Transaction MUST still exist and point to the fund
        txn.refresh_from_db()
        self.assertEqual(txn.purpose_fund, fund)
        self.assertEqual(txn.amount, Decimal('500.00'))

    # 22. Equivalent normalized phone representations resolve to the same account
    def test_22_phone_normalization_equivalent_representations(self):
        # User B's phone is '01711111111'
        self.assertEqual(normalize_phone('+8801711111111'), '01711111111')
        self.assertEqual(normalize_phone('8801711111111'), '01711111111')
        self.assertEqual(normalize_phone('+880 1711-111111'), '01711111111')
        self.assertEqual(normalize_phone('01711 111111'), '01711111111')

        self.assertEqual(find_user_by_phone_or_username('+8801711111111'), self.user_b)
        self.assertEqual(find_user_by_phone_or_username('8801711111111'), self.user_b)
        self.assertEqual(find_user_by_phone_or_username('+880 1711-111111'), self.user_b)
        self.assertEqual(find_user_by_phone_or_username('huma'), self.user_b)


class FamilyPassActivityAndItemTrackingTest(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username='owner_shahed',
            full_name='Shahed Annam',
            phone='01710000001',
            role=UserRole.CUSTOMER,
            password='password123'
        )
        self.owner_wallet = Wallet.objects.create(owner=self.owner, balance=Decimal('15000.00'))

        self.member = User.objects.create_user(
            username='member_karim',
            full_name='Karim Hossain',
            phone='01810000002',
            role=UserRole.MEMBER,
            password='password123'
        )
        self.member_wallet = Wallet.objects.create(owner=self.member, balance=Decimal('500.00'))

        self.unrelated_user = User.objects.create_user(
            username='unrelated_rahim',
            full_name='Rahim Uddin',
            phone='01910000003',
            role=UserRole.CUSTOMER,
            password='password123'
        )
        self.unrelated_wallet = Wallet.objects.create(owner=self.unrelated_user, balance=Decimal('2000.00'))

        self.grocery_merchant = Merchant.objects.create(
            business_name='Swapno Super Shop',
            category=BusinessCategory.GROCERY,
            account_number='SWP-DHAKA-01',
            address='Dhanmondi, Dhaka',
            balance=Decimal('0.00'),
            is_active=True
        )

        self.medicine_merchant = Merchant.objects.create(
            business_name='Lazz Pharma',
            category=BusinessCategory.MEDICINE,
            account_number='LAZZ-DHAKA-02',
            address='Panthapath, Dhaka',
            balance=Decimal('0.00'),
            is_active=True
        )

        self.education_merchant = Merchant.objects.create(
            business_name='Nilkhet Book Center',
            category=BusinessCategory.EDUCATION,
            account_number='NLK-BOOK-03',
            address='Nilkhet, Dhaka',
            balance=Decimal('0.00'),
            is_active=True
        )

        today = timezone.localdate() if timezone.is_aware(timezone.now()) else timezone.now().date()
        self.family_pass = FamilyPass.objects.create(
            owner=self.owner,
            member=self.member,
            limit_amount=Decimal('1000.00'),
            used_amount=Decimal('0.00'),
            start_date=today,
            expiry_date=today + datetime.timedelta(days=30),
            allowed_action=FamilyPassAction.MERCHANT_PAYMENT,
            status=FamilyPassStatus.ACTIVE,
            purpose_label='Weekly Emergency Pocket Allowance'
        )

        self.client_owner = Client()
        self.client_owner.force_login(self.owner)
        session = self.client_owner.session
        session['user_id'] = self.owner.id
        session.save()

        self.client_member = Client()
        self.client_member.force_login(self.member)
        session = self.client_member.session
        session['user_id'] = self.member.id
        session.save()

        self.client_unrelated = Client()
        self.client_unrelated.force_login(self.unrelated_user)
        session = self.client_unrelated.session
        session['user_id'] = self.unrelated_user.id
        session.save()

    # 1. Merchant payment with one item
    def test_01_merchant_payment_with_one_item(self):
        items = [{'item_name': 'Rice (Miniket 2kg)', 'quantity': 2, 'unit_price': 100}]
        txn = TransactionService.execute_transaction(
            sender=self.owner,
            transaction_type=TransactionType.MERCHANT_PAYMENT,
            merchant=self.grocery_merchant,
            payment_source=PaymentSource.NORMAL_WALLET,
            items=items
        )
        self.assertEqual(txn.amount, Decimal('200.00'))
        self.assertEqual(txn.items.count(), 1)
        item = txn.items.first()
        self.assertEqual(item.name, 'Rice (Miniket 2kg)')
        self.assertEqual(item.quantity, Decimal('2.00'))
        self.assertEqual(item.unit_price, Decimal('100.00'))
        self.assertEqual(item.total, Decimal('200.00'))
        self.owner_wallet.refresh_from_db()
        self.assertEqual(self.owner_wallet.balance, Decimal('14800.00'))

    # 2. Merchant payment with multiple items
    def test_02_merchant_payment_with_multiple_items(self):
        items = [
            {'item_name': 'Rice', 'quantity': 2, 'unit_price': 80},
            {'item_name': 'Milk', 'quantity': 1, 'unit_price': 90},
            {'item_name': 'Oil', 'quantity': 1, 'unit_price': 180}
        ]
        txn = TransactionService.execute_transaction(
            sender=self.owner,
            transaction_type=TransactionType.MERCHANT_PAYMENT,
            merchant=self.grocery_merchant,
            payment_source=PaymentSource.NORMAL_WALLET,
            items=items
        )
        self.assertEqual(txn.amount, Decimal('430.00'))
        self.assertEqual(txn.items.count(), 3)
        self.assertEqual(sum(it.total for it in txn.items.all()), Decimal('430.00'))

    # 3. Correct line-total calculation
    def test_03_correct_line_total_calculation(self):
        items = [{'item_name': 'Medicine', 'quantity': 3, 'unit_price': 50, 'discount': 10, 'tax': 5}]
        txn = TransactionService.execute_transaction(
            sender=self.owner,
            transaction_type=TransactionType.MERCHANT_PAYMENT,
            merchant=self.medicine_merchant,
            payment_source=PaymentSource.NORMAL_WALLET,
            items=items
        )
        # (3 * 50) - 10 + 5 = 145.00
        self.assertEqual(txn.amount, Decimal('145.00'))
        item = txn.items.first()
        self.assertEqual(item.total, Decimal('145.00'))

    # 4. Correct transaction-total calculation
    def test_04_correct_transaction_total_calculation(self):
        items = [
            {'item_name': 'Item A', 'quantity': 2, 'unit_price': 50},
            {'item_name': 'Item B', 'quantity': 3, 'unit_price': 30}
        ]
        # Call without amount; backend auto-calculates total
        txn = TransactionService.execute_transaction(
            sender=self.owner,
            transaction_type=TransactionType.MERCHANT_PAYMENT,
            merchant=self.grocery_merchant,
            items=items
        )
        self.assertEqual(txn.amount, Decimal('190.00'))

    # 5. Invalid quantity is rejected
    def test_05_invalid_quantity_is_rejected(self):
        items = [{'item_name': 'Bad Item', 'quantity': -2, 'unit_price': 50}]
        with self.assertRaises(TransactionValidationError):
            TransactionService.execute_transaction(
                sender=self.owner,
                transaction_type=TransactionType.MERCHANT_PAYMENT,
                merchant=self.grocery_merchant,
                items=items
            )

    # 6. Invalid price is rejected
    def test_06_invalid_price_is_rejected(self):
        items = [{'item_name': 'Bad Item', 'quantity': 1, 'unit_price': -50}]
        with self.assertRaises(TransactionValidationError):
            TransactionService.execute_transaction(
                sender=self.owner,
                transaction_type=TransactionType.MERCHANT_PAYMENT,
                merchant=self.grocery_merchant,
                items=items
            )

    # 7. Frontend-supplied total cannot override backend calculation
    def test_07_frontend_supplied_total_cannot_override_backend_calculation(self):
        items = [{'item_name': 'Rice', 'quantity': 2, 'unit_price': 100}]  # Total 200
        with self.assertRaises(TransactionValidationError) as ctx:
            TransactionService.execute_transaction(
                sender=self.owner,
                transaction_type=TransactionType.MERCHANT_PAYMENT,
                amount=Decimal('50.00'),
                merchant=self.grocery_merchant,
                items=items
            )
        self.assertEqual(ctx.exception.code, 'AMOUNT_MISMATCH')

    # 8. Item records are linked to the correct transaction
    def test_08_item_records_are_linked_to_correct_transaction(self):
        txn1 = TransactionService.execute_transaction(
            sender=self.owner,
            transaction_type=TransactionType.MERCHANT_PAYMENT,
            merchant=self.grocery_merchant,
            items=[{'item_name': 'Apple', 'quantity': 1, 'unit_price': 100}]
        )
        txn2 = TransactionService.execute_transaction(
            sender=self.owner,
            transaction_type=TransactionType.MERCHANT_PAYMENT,
            merchant=self.grocery_merchant,
            items=[{'item_name': 'Banana', 'quantity': 2, 'unit_price': 30}]
        )
        self.assertEqual(list(txn1.items.values_list('name', flat=True)), ['Apple'])
        self.assertEqual(list(txn2.items.values_list('name', flat=True)), ['Banana'])

    # 9. Successful payment updates the allowance correctly
    def test_09_familypass_successful_payment_updates_allowance_correctly(self):
        items = [{'item_name': 'Medicine', 'quantity': 2, 'unit_price': 200}]
        txn = TransactionService.execute_transaction(
            sender=self.member,
            transaction_type=TransactionType.MERCHANT_PAYMENT,
            merchant=self.medicine_merchant,
            payment_source=PaymentSource.FAMILY_PASS,
            family_pass=self.family_pass,
            items=items
        )
        self.assertEqual(txn.amount, Decimal('400.00'))
        self.family_pass.refresh_from_db()
        self.assertEqual(self.family_pass.used_amount, Decimal('400.00'))
        self.assertEqual(self.family_pass.remaining_limit, Decimal('600.00'))
        self.owner_wallet.refresh_from_db()
        self.assertEqual(self.owner_wallet.balance, Decimal('14600.00'))

    # 10. Insufficient allowance rejects the payment
    def test_10_familypass_insufficient_allowance_rejects_payment(self):
        items = [{'item_name': 'Expensive Goods', 'quantity': 1, 'unit_price': 1500}]
        with self.assertRaises(TransactionValidationError) as ctx:
            TransactionService.execute_transaction(
                sender=self.member,
                transaction_type=TransactionType.MERCHANT_PAYMENT,
                merchant=self.grocery_merchant,
                payment_source=PaymentSource.FAMILY_PASS,
                family_pass=self.family_pass,
                items=items
            )
        self.assertEqual(ctx.exception.code, 'FAMILYPASS_LIMIT_EXCEEDED')

    # 11. Expired FamilyPass cannot be used
    def test_11_expired_familypass_cannot_be_used(self):
        yesterday = (timezone.localdate() if timezone.is_aware(timezone.now()) else timezone.now().date()) - datetime.timedelta(days=1)
        self.family_pass.expiry_date = yesterday
        self.family_pass.save()
        items = [{'item_name': 'Rice', 'quantity': 1, 'unit_price': 100}]
        with self.assertRaises(TransactionValidationError) as ctx:
            TransactionService.execute_transaction(
                sender=self.member,
                transaction_type=TransactionType.MERCHANT_PAYMENT,
                merchant=self.grocery_merchant,
                payment_source=PaymentSource.FAMILY_PASS,
                family_pass=self.family_pass,
                items=items
            )
        self.assertEqual(ctx.exception.code, 'FAMILYPASS_EXPIRED')

    # 12. Unauthorized action is rejected
    def test_12_unauthorized_action_is_rejected(self):
        self.family_pass.allowed_action = 'OTHER_RESTRICTED'
        self.family_pass.save()
        items = [{'item_name': 'Rice', 'quantity': 1, 'unit_price': 100}]
        with self.assertRaises(TransactionValidationError) as ctx:
            TransactionService.execute_transaction(
                sender=self.member,
                transaction_type=TransactionType.MERCHANT_PAYMENT,
                merchant=self.grocery_merchant,
                payment_source=PaymentSource.FAMILY_PASS,
                family_pass=self.family_pass,
                items=items
            )
        self.assertEqual(ctx.exception.code, 'FAMILYPASS_ACTION_DENIED')

    # 13. Item records appear in FamilyPass activity
    def test_13_item_records_appear_in_familypass_activity(self):
        items = [
            {'item_name': 'Rice', 'quantity': 2, 'unit_price': 80},
            {'item_name': 'Milk', 'quantity': 1, 'unit_price': 90}
        ]
        resp = self.client_member.post('/api/pay/', {
            'merchant_id': self.grocery_merchant.id,
            'payment_source': 'FAMILY_PASS',
            'family_pass_id': self.family_pass.id,
            'items': items
        }, content_type='application/json')
        self.assertEqual(resp.status_code, 200)

        # Owner fetches activity
        act_resp = self.client_owner.get(f'/api/family-pass/{self.family_pass.id}/activity/')
        self.assertEqual(act_resp.status_code, 200)
        activities = act_resp.data['activities']
        self.assertEqual(len(activities), 1)
        first_act = activities[0]
        self.assertTrue(first_act['has_items'])
        self.assertEqual(len(first_act['items']), 2)
        self.assertEqual(first_act['items'][0]['item_name'], 'Rice')
        self.assertEqual(Decimal(str(first_act['items'][0]['line_total'])), Decimal('160.00'))

    # 14. FamilyPass owner can view detailed activity
    def test_14_familypass_owner_can_view_detailed_activity(self):
        resp = self.client_owner.get(f'/api/family-pass/{self.family_pass.id}/activity/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('family_pass', resp.data)
        self.assertIn('activities', resp.data)
        self.assertEqual(resp.data['family_pass']['id'], self.family_pass.id)

    # 15. Unrelated user cannot view another owner's activity
    def test_15_unrelated_user_cannot_view_another_owners_activity(self):
        resp = self.client_unrelated.get(f'/api/family-pass/{self.family_pass.id}/activity/')
        self.assertEqual(resp.status_code, 403)

    # 16. Old transactions without item records remain visible
    def test_16_old_transactions_without_item_records_remain_visible(self):
        old_txn = Transaction.objects.create(
            transaction_id='TXN-HISTORICAL-001',
            sender=self.member,
            merchant=self.grocery_merchant,
            amount=Decimal('400.00'),
            transaction_type=TransactionType.MERCHANT_PAYMENT,
            payment_source=PaymentSource.FAMILY_PASS,
            family_pass=self.family_pass,
            status=TransactionStatus.COMPLETED
        )
        FamilyPassTransaction.objects.create(
            family_pass=self.family_pass,
            transaction=old_txn,
            member=self.member,
            amount=Decimal('400.00'),
            remaining_limit_after=Decimal('600.00')
        )
        resp = self.client_owner.get(f'/api/family-pass/{self.family_pass.id}/activity/')
        self.assertEqual(resp.status_code, 200)
        activities = resp.data['activities']
        self.assertEqual(len(activities), 1)
        self.assertEqual(activities[0]['items'], [])
        self.assertFalse(activities[0]['has_items'])

    # 17. Missing item details are displayed honestly
    def test_17_missing_item_details_are_displayed_honestly(self):
        old_txn = Transaction.objects.create(
            transaction_id='TXN-HISTORICAL-002',
            sender=self.member,
            merchant=self.grocery_merchant,
            amount=Decimal('250.00'),
            transaction_type=TransactionType.MERCHANT_PAYMENT,
            payment_source=PaymentSource.FAMILY_PASS,
            family_pass=self.family_pass,
            status=TransactionStatus.COMPLETED
        )
        FamilyPassTransaction.objects.create(
            family_pass=self.family_pass,
            transaction=old_txn,
            member=self.member,
            amount=Decimal('250.00'),
            remaining_limit_after=Decimal('750.00')
        )
        resp = self.client_owner.get(f'/api/family-pass/{self.family_pass.id}/activity/')
        act = resp.data['activities'][0]
        self.assertEqual(len(act['items']), 0)
        self.assertFalse(act['has_items'])

    # 18. No fake item records are created during migration
    def test_18_no_fake_item_records_are_created_during_migration(self):
        old_txn = Transaction.objects.create(
            transaction_id='TXN-HISTORICAL-003',
            sender=self.member,
            merchant=self.medicine_merchant,
            amount=Decimal('150.00'),
            transaction_type=TransactionType.MERCHANT_PAYMENT,
            payment_source=PaymentSource.FAMILY_PASS,
            family_pass=self.family_pass,
            status=TransactionStatus.COMPLETED
        )
        self.assertEqual(TransactionItem.objects.filter(transaction=old_txn).count(), 0)

    # 19. Existing merchant payments still work
    def test_19_existing_merchant_payments_without_items_still_work(self):
        txn = TransactionService.execute_transaction(
            sender=self.owner,
            transaction_type=TransactionType.MERCHANT_PAYMENT,
            amount=Decimal('250.00'),
            merchant=self.grocery_merchant,
            payment_source=PaymentSource.NORMAL_WALLET
        )
        self.assertEqual(txn.amount, Decimal('250.00'))
        self.assertEqual(txn.items.count(), 0)

    # 20. Existing wallet transfers and other non-item transactions still work
    def test_20_existing_wallet_transfers_and_recharge_still_work(self):
        txn_send = TransactionService.execute_transaction(
            sender=self.owner,
            transaction_type=TransactionType.SEND_MONEY,
            amount=Decimal('300.00'),
            receiver=self.unrelated_user
        )
        self.assertEqual(txn_send.amount, Decimal('300.00'))
        self.assertEqual(txn_send.status, TransactionStatus.COMPLETED)

        txn_recharge = TransactionService.execute_transaction(
            sender=self.owner,
            transaction_type=TransactionType.MOBILE_RECHARGE,
            amount=Decimal('100.00')
        )
        self.assertEqual(txn_recharge.amount, Decimal('100.00'))
        self.assertEqual(txn_recharge.status, TransactionStatus.COMPLETED)

    # 21. Existing FamilyPass creation, revoke, and limit behavior still works
    def test_21_existing_familypass_create_revoke_limit_behavior_still_works(self):
        # Revoke pass
        resp = self.client_owner.post(f'/api/family-pass/{self.family_pass.id}/revoke/')
        self.assertEqual(resp.status_code, 200)
        self.family_pass.refresh_from_db()
        self.assertEqual(self.family_pass.status, FamilyPassStatus.REVOKED)

        # Attempt to spend from revoked pass
        with self.assertRaises(TransactionValidationError) as ctx:
            TransactionService.execute_transaction(
                sender=self.member,
                transaction_type=TransactionType.MERCHANT_PAYMENT,
                amount=Decimal('100.00'),
                merchant=self.grocery_merchant,
                payment_source=PaymentSource.FAMILY_PASS,
                family_pass=self.family_pass
            )
        self.assertEqual(ctx.exception.code, 'FAMILYPASS_INACTIVE')


class UnicodeAndConsoleEncodingSafetyTest(TestCase):
    """
    Verifies that the Bangladeshi Taka symbol (৳), Bengali text, and Unicode
    are preserved everywhere in UI/API/models, while console streams and loggers
    are guarded against charmap UnicodeEncodeErrors.
    """
    def setUp(self):
        self.user = User.objects.create_user(
            username='bengali_user',
            password='password123',
            full_name='আহমেদ জামান',
            phone='01712999888'
        )
        self.wallet = Wallet.objects.create(owner=self.user, balance=Decimal('1500.00'))

    def test_01_taka_symbol_and_bengali_in_model_str(self):
        wallet_str = str(self.wallet)
        self.assertIn('৳', wallet_str)
        self.assertIn('1500.00', wallet_str)
        self.assertEqual(self.user.full_name, 'আহমেদ জামান')

    def test_02_bdt_replace_codec_error_handler(self):
        from fundshare_app.encoding import _bdt_encode_error_handler
        import codecs
        text = 'Total: ৳500.00'
        # Encoding to cp1252 using bdt_replace should replace ৳ with BDT without error
        encoded = text.encode('cp1252', errors='bdt_replace')
        decoded = encoded.decode('cp1252')
        self.assertEqual(decoded, 'Total: BDT 500.00')

    def test_03_safe_console_text_preserves_taka_on_utf8(self):
        from fundshare_app.encoding import safe_console_text
        import io
        utf8_stream = io.TextIOWrapper(io.BytesIO(), encoding='utf-8')
        result_utf8 = safe_console_text('Amount: ৳750.00', stream=utf8_stream)
        self.assertIn('৳', result_utf8)

        cp1252_stream = io.TextIOWrapper(io.BytesIO(), encoding='cp1252')
        result_cp1252 = safe_console_text('Amount: ৳750.00', stream=cp1252_stream)
        self.assertIn('BDT', result_cp1252)
        self.assertNotIn('৳', result_cp1252)

    def test_04_safe_console_formatter_handles_taka(self):
        import logging
        from fundshare_app.encoding import SafeConsoleFormatter
        formatter = SafeConsoleFormatter(fmt='%(message)s')
        record = logging.LogRecord(
            name='test',
            level=logging.INFO,
            pathname='',
            lineno=0,
            msg='Transaction completed: ৳2,000.00',
            args=(),
            exc_info=None
        )
        output = formatter.format(record)
        # Must format cleanly without exception
        self.assertTrue('৳2,000.00' in output or 'BDT 2,000.00' in output)

    def test_05_api_responses_preserve_taka_symbol(self):
        client = Client()
        client.force_login(self.user)
        # Attempt to allocate more than balance to trigger validation error containing ৳
        fund = PurposeFund.objects.create(
            owner=self.user,
            name='Education Fund',
            category='Education',
            allocated_amount=Decimal('0.00'),
            current_balance=Decimal('0.00'),
            monthly_budget=Decimal('2000.00')
        )
        resp = client.post(
            f'/api/funds/{fund.id}/allocate/',
            {'amount': '99999.00'},
            content_type='application/json'
        )
        self.assertEqual(resp.status_code, 400)
        content_text = resp.content.decode('utf-8')
        # Response should contain the ৳ character
        self.assertIn('৳', content_text)


