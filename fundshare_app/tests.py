from decimal import Decimal
import datetime
from django.test import TestCase
from django.utils import timezone
from django.contrib.auth import get_user_model
from fundshare_app.models import (
    UserRole, BusinessCategory, Wallet, Merchant, PurposeFund,
    FamilyPass, FamilyPassStatus, FamilyPassAction,
    Transaction, TransactionType, PaymentSource, TransactionStatus,
    Notification
)
from fundshare_app.services.transaction_service import TransactionService, TransactionValidationError
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
