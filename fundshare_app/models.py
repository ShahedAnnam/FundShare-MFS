import uuid
from decimal import Decimal
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils import timezone
from django.contrib.auth.hashers import make_password, check_password
from django.core.exceptions import ValidationError


class UserRole(models.TextChoices):
    CUSTOMER = 'CUSTOMER', 'Customer / Wallet Owner'
    MERCHANT = 'MERCHANT', 'Merchant'
    ADMIN = 'ADMIN', 'Admin / Hackathon Evaluator'


class BusinessCategory(models.TextChoices):
    GROCERY = 'Grocery', 'Grocery'
    MEDICINE = 'Medicine', 'Medicine'
    TREATMENT = 'Treatment', 'Treatment'
    EDUCATION = 'Education', 'Education'
    ELECTRICITY = 'Electricity', 'Electricity'
    RESTAURANT = 'Restaurant/Food', 'Restaurant / Food'
    TRANSPORT = 'Transport', 'Transport'
    RENT = 'Rent', 'Rent'
    SHOPPING = 'Shopping', 'Shopping'
    OTHER = 'Other', 'Other'


class User(AbstractUser):
    role = models.CharField(max_length=20, choices=UserRole.choices, default=UserRole.CUSTOMER)
    phone = models.CharField(max_length=20, unique=True, null=True, blank=True)
    full_name = models.CharField(max_length=150, blank=True)
    avatar_url = models.CharField(max_length=255, blank=True, default='')
    transaction_pin = models.CharField(max_length=128, blank=True, default='')
    pin_failed_attempts = models.PositiveSmallIntegerField(default=0)
    pin_locked_until = models.DateTimeField(null=True, blank=True)

    class Meta(AbstractUser.Meta):
        abstract = False
        constraints = [
            models.CheckConstraint(condition=models.Q(role__in=UserRole.values), name='user_supported_role'),
            models.CheckConstraint(condition=models.Q(phone__isnull=True) | models.Q(phone__regex=r'\A01[3-9][0-9]{8}\Z'), name='user_canonical_phone'),
        ]

    def normalize_account_phone(self):
        from fundshare_app.services.phone_utils import normalize_phone, is_valid_bd_phone
        self.phone = normalize_phone(self.phone) or None
        if self.phone and not is_valid_bd_phone(self.phone):
            raise ValidationError({'phone': 'Enter a valid Bangladesh mobile phone number.'})

    def clean(self):
        super().clean()
        self.normalize_account_phone()

    def save(self, *args, **kwargs):
        self.normalize_account_phone()
        super().save(*args, **kwargs)

    def set_transaction_pin(self, pin):
        self.transaction_pin = make_password(pin)

    def check_transaction_pin(self, pin):
        return bool(self.transaction_pin) and check_password(pin, self.transaction_pin)

    @property
    def effective_role(self):
        """FamilyPass permissions never determine an account's role."""
        if self.is_superuser:
            return UserRole.ADMIN
        return self.role

    def get_effective_role_display(self):
        role_val = self.effective_role
        try:
            return UserRole(role_val).label
        except (ValueError, KeyError):
            return role_val

    def __str__(self):
        return f"{self.username} ({self.get_effective_role_display()})"


class Wallet(models.Model):
    owner = models.OneToOneField(User, on_delete=models.CASCADE, related_name='wallet')
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(balance__gte=0), name='wallet_nonnegative')]

    def __str__(self):
        return f"Wallet of {self.owner.username} (৳{self.balance})"


class Merchant(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='merchant_profile', null=True, blank=True)
    business_name = models.CharField(max_length=150)
    category = models.CharField(max_length=50, choices=BusinessCategory.choices, default=BusinessCategory.OTHER)
    account_number = models.CharField(max_length=30, unique=True)
    contact_phone = models.CharField(max_length=20, blank=True)
    address = models.CharField(max_length=255, blank=True)
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(balance__gte=0), name='merchant_nonnegative')]

    def __str__(self):
        return f"{self.business_name} [{self.category}]"


class FundStatus(models.TextChoices):
    ACTIVE = 'ACTIVE', 'Active'
    ARCHIVED = 'ARCHIVED', 'Archived'


class PurposeFund(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='purpose_funds')
    name = models.CharField(max_length=100)
    category = models.CharField(max_length=50, choices=BusinessCategory.choices)
    allocated_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    current_balance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    monthly_budget = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    icon = models.CharField(max_length=50, default='wallet')
    color = models.CharField(max_length=30, default='#10B981')
    status = models.CharField(max_length=20, choices=FundStatus.choices, default=FundStatus.ACTIVE)
    recipient = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_purpose_funds')
    created_at = models.DateTimeField(auto_now_add=True)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['owner', 'status'], name='fund_owner_status_idx'), models.Index(fields=['recipient', 'status'], name='fund_recipient_status_idx')]
        constraints = [
            models.CheckConstraint(condition=models.Q(current_balance__gte=0), name='fund_nonnegative'),
            models.CheckConstraint(condition=models.Q(allocated_amount__gte=0), name='fund_allocation_nonnegative'),
            models.CheckConstraint(condition=models.Q(monthly_budget__gte=0), name='fund_budget_nonnegative'),
        ]

    def __str__(self):
        return f"{self.name} (৳{self.current_balance}/৳{self.allocated_amount}) - {self.owner.username}"


class FundTransfer(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='fund_transfers')
    source_fund = models.ForeignKey(PurposeFund, on_delete=models.CASCADE, related_name='transfers_out')
    destination_fund = models.ForeignKey(PurposeFund, on_delete=models.CASCADE, related_name='transfers_in')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.CharField(max_length=255, blank=True, default='')
    timestamp = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(amount__gt=0), name='transfer_amount_positive')]

    def __str__(self):
        return f"Transfer ৳{self.amount}: {self.source_fund.name} -> {self.destination_fund.name} ({self.owner.username})"


class FamilyPassStatus(models.TextChoices):
    ACTIVE = 'ACTIVE', 'Active'
    REVOKED = 'REVOKED', 'Revoked'
    EXPIRED = 'EXPIRED', 'Expired'


class FamilyPassAction(models.TextChoices):
    MERCHANT_PAYMENT = 'MERCHANT_PAYMENT', 'Merchant Payment Only'
    ALL_ACTIONS = 'ALL', 'All Actions'
    GROCERY_AND_MEDICINE = 'GROCERY_MEDICINE', 'Grocery & Medicine Only'


class FamilyPassPurpose(models.TextChoices):
    GROCERY = 'Grocery', 'Grocery'
    EDUCATION = 'Education', 'Education'
    MEDICAL = 'Medical', 'Medical'
    SHOPPING = 'Shopping', 'Shopping'
    DINING = 'Dining', 'Dining'
    TRANSPORT = 'Transport', 'Transport'
    BILLS_UTILITIES = 'Bills & Utilities', 'Bills & Utilities'
    EMERGENCY = 'Emergency', 'Emergency'
    OTHER = 'Other', 'Other'


# Canonical mapping: FamilyPassPurpose -> BusinessCategory values.
# Emergency and Other are intentionally unrestricted (allowed_categories == []).
PURPOSE_TO_CATEGORIES = {
    "Grocery": ["Grocery"],
    "Medical": ["Medicine", "Treatment"],
    "Dining": ["Restaurant/Food"],
    "Bills & Utilities": ["Electricity", "Rent"],
    "Education": ["Education"],
    "Transport": ["Transport"],
    "Shopping": ["Shopping"],
    "Emergency": [],  # unrestricted: usable at any merchant category
    "Other": [],      # unrestricted: usable at any merchant category
}


class FamilyPass(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='issued_family_passes')
    member = models.ForeignKey(User, on_delete=models.CASCADE, related_name='received_family_passes')
    limit_amount = models.DecimalField(max_digits=12, decimal_places=2)
    used_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    start_date = models.DateField(default=timezone.now)
    expiry_date = models.DateField()
    allowed_action = models.CharField(max_length=50, choices=FamilyPassAction.choices, default=FamilyPassAction.MERCHANT_PAYMENT)
    status = models.CharField(max_length=20, choices=FamilyPassStatus.choices, default=FamilyPassStatus.ACTIVE)
    purpose = models.CharField(max_length=50, choices=FamilyPassPurpose.choices, default=FamilyPassPurpose.OTHER)
    custom_purpose = models.CharField(max_length=150, blank=True, default='')
    allowed_categories = models.JSONField(default=list, blank=True)
    purpose_label = models.CharField(max_length=150, blank=True, default='Family Spending')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=['owner', 'status', 'expiry_date'], name='pass_owner_status_exp_idx'), models.Index(fields=['member', 'status', 'expiry_date'], name='pass_member_status_exp_idx')]
        constraints = [
            models.CheckConstraint(condition=models.Q(used_amount__gte=0), name='pass_used_nonnegative'),
            models.CheckConstraint(condition=models.Q(limit_amount__gt=0), name='pass_limit_positive'),
            models.CheckConstraint(condition=models.Q(used_amount__lte=models.F('limit_amount')), name='pass_within_limit'),
        ]

    @property
    def remaining_limit(self):
        rem = self.limit_amount - self.used_amount
        return max(Decimal('0.00'), rem)

    @property
    def is_active(self):
        return self.status == FamilyPassStatus.ACTIVE

    @property
    def is_expired(self):
        today = timezone.localdate() if timezone.is_aware(timezone.now()) else timezone.now().date()
        return self.expiry_date < today

    @property
    def is_valid_and_active(self):
        if self.status != FamilyPassStatus.ACTIVE:
            return False
        today = timezone.localdate() if timezone.is_aware(timezone.now()) else timezone.now().date()
        if self.expiry_date < today:
            return False
        return self.start_date <= today and self.remaining_limit > Decimal('0.00')

    def get_allowed_categories(self):
        """
        Returns the list of allowed BusinessCategory strings for this FamilyPass.
        Returns empty list [] if and only if the pass is genuinely unrestricted.
        """
        if self.allowed_categories and isinstance(self.allowed_categories, (list, tuple)) and len(self.allowed_categories) > 0:
            return list(self.allowed_categories)
        return []

    def is_category_allowed(self, category):
        """
        Checks if this FamilyPass permits transactions for a merchant of `category`.
        - If allowed_categories is non-empty, category must be in allowed_categories.
        - If allowed_categories is empty, pass is unrestricted.
        """
        if self.allowed_categories and isinstance(self.allowed_categories, (list, tuple)) and len(self.allowed_categories) > 0:
            return category in self.allowed_categories
        return True

    def save(self, *args, **kwargs):
        # Synchronize purpose and purpose_label
        if not self.purpose:
            if self.purpose_label in FamilyPassPurpose.values:
                self.purpose = self.purpose_label
            else:
                lbl_lower = (self.purpose_label or "").lower()
                matched_purpose = None
                for p_val, p_lbl in FamilyPassPurpose.choices:
                    if p_val == FamilyPassPurpose.OTHER:
                        continue
                    if p_val.lower() in lbl_lower or p_lbl.lower() in lbl_lower:
                        matched_purpose = p_val
                        break
                if not matched_purpose:
                    # Also check common synonyms
                    if any(w in lbl_lower for w in ['pharmacy', 'health', 'clinic', 'hospital', 'doctor']):
                        matched_purpose = FamilyPassPurpose.MEDICAL
                    elif any(w in lbl_lower for w in ['school', 'college', 'tuition', 'exam']):
                        matched_purpose = FamilyPassPurpose.EDUCATION
                    elif any(w in lbl_lower for w in ['food', 'bazaar', 'kitchen']):
                        matched_purpose = FamilyPassPurpose.GROCERY
                    elif any(w in lbl_lower for w in ['electricity', 'water', 'gas', 'bill']):
                        matched_purpose = FamilyPassPurpose.BILLS_UTILITIES
                    elif any(w in lbl_lower for w in ['uber', 'ride', 'fare', 'bus', 'train']):
                        matched_purpose = FamilyPassPurpose.TRANSPORT
                    elif 'emergency' in lbl_lower:
                        matched_purpose = FamilyPassPurpose.EMERGENCY

                if matched_purpose:
                    self.purpose = matched_purpose
                else:
                    self.purpose = FamilyPassPurpose.OTHER
                    if not self.custom_purpose and self.purpose_label:
                        self.custom_purpose = self.purpose_label

        if self.purpose == FamilyPassPurpose.OTHER:
            if self.custom_purpose:
                self.purpose_label = f"Other: {self.custom_purpose}"
            else:
                self.purpose_label = "Other"
        elif not self.purpose_label or self.purpose_label == 'Family Spending' or self.purpose_label in FamilyPassPurpose.values:
            self.purpose_label = self.purpose

        super().save(*args, **kwargs)

    def __str__(self):
        return f"FamilyPass: {self.owner.username} -> {self.member.username} [{self.purpose_label}] (৳{self.used_amount}/৳{self.limit_amount})"


class TransactionType(models.TextChoices):
    CASH_IN = 'CASH_IN', 'Add Money / Cash In'
    SEND_MONEY = 'SEND_MONEY', 'Send Money'
    RECEIVE_MONEY = 'RECEIVE_MONEY', 'Receive Money'
    MERCHANT_PAYMENT = 'MERCHANT_PAYMENT', 'Merchant Payment'
    MOBILE_RECHARGE = 'MOBILE_RECHARGE', 'Mobile Recharge'
    BILL_PAYMENT = 'BILL_PAYMENT', 'Bill Payment'
    CASH_OUT = 'CASH_OUT', 'Cash Out'
    FUND_ALLOCATION = 'FUND_ALLOCATION', 'Purpose Fund Allocation'
    FUND_TRANSFER = 'FUND_TRANSFER', 'Inter-Fund Transfer'


class PaymentSource(models.TextChoices):
    NORMAL_WALLET = 'NORMAL_WALLET', 'Normal Wallet'
    PURPOSE_FUND = 'PURPOSE_FUND', 'Purpose Fund'
    FAMILY_PASS = 'FAMILY_PASS', 'FamilyPass'


class TransactionStatus(models.TextChoices):
    COMPLETED = 'COMPLETED', 'Completed'
    REJECTED = 'REJECTED', 'Rejected'
    FAILED = 'FAILED', 'Failed'


class Transaction(models.Model):
    transaction_id = models.CharField(max_length=64, unique=True, default=uuid.uuid4)
    sender = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='sent_transactions')
    receiver = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='received_transactions')
    merchant = models.ForeignKey(Merchant, on_delete=models.SET_NULL, null=True, blank=True, related_name='transactions')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    transaction_type = models.CharField(max_length=30, choices=TransactionType.choices)
    payment_source = models.CharField(max_length=30, choices=PaymentSource.choices, default=PaymentSource.NORMAL_WALLET)
    purpose_fund = models.ForeignKey(PurposeFund, on_delete=models.SET_NULL, null=True, blank=True, related_name='transactions')
    family_pass = models.ForeignKey(FamilyPass, on_delete=models.SET_NULL, null=True, blank=True, related_name='transactions')
    category = models.CharField(max_length=50, blank=True, default='')
    status = models.CharField(max_length=20, choices=TransactionStatus.choices, default=TransactionStatus.COMPLETED)
    rejection_reason = models.TextField(blank=True, default='')
    reference = models.CharField(max_length=255, blank=True, default='')
    metadata = models.JSONField(default=dict, blank=True)
    timestamp = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['sender', 'timestamp']),
            models.Index(fields=['transaction_type']),
            models.Index(fields=['payment_source']),
            models.Index(fields=['receiver', '-timestamp'], name='txn_receiver_time_idx'),
            models.Index(fields=['family_pass', '-timestamp'], name='txn_pass_time_idx'),
            models.Index(fields=['merchant', '-timestamp'], name='txn_merchant_time_idx'),
        ]
        constraints = [models.CheckConstraint(condition=models.Q(amount__gt=0), name='transaction_amount_positive')]

    def __str__(self):
        return f"{self.transaction_id} | {self.transaction_type} | ৳{self.amount} | {self.status}"


class FinancialRequest(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='financial_requests')
    key = models.CharField(max_length=128)
    fingerprint = models.CharField(max_length=64)
    response = models.JSONField(default=dict)
    response_status = models.PositiveSmallIntegerField(default=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'key'], name='unique_user_financial_request')]


class TransactionItem(models.Model):
    """
    Stores individual purchased items within a merchant payment transaction.
    Provides granular item-level tracking for FamilyPass activity and
    transaction history without modifying existing Transaction totals.
    """
    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE, related_name='items')
    name = models.CharField(max_length=200)
    product_id = models.CharField(max_length=100, blank=True, default='')
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('1.00'))
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    tax = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    total = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['id']
        indexes = [
            models.Index(fields=['transaction']),
        ]

    @property
    def item_name(self):
        return self.name

    @item_name.setter
    def item_name(self, value):
        self.name = value

    @property
    def line_total(self):
        return self.total

    @line_total.setter
    def line_total(self, value):
        self.total = value

    def save(self, *args, **kwargs):
        if self.total is None:
            self.total = (self.quantity * self.unit_price) - self.discount + self.tax
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} x{self.quantity} @ ৳{self.unit_price} = ৳{self.total}"


class FamilyPassTransaction(models.Model):
    family_pass = models.ForeignKey(FamilyPass, on_delete=models.CASCADE, related_name='activity_logs')
    transaction = models.OneToOneField(Transaction, on_delete=models.CASCADE, related_name='family_pass_detail')
    member = models.ForeignKey(User, on_delete=models.CASCADE, related_name='family_pass_spendings')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    remaining_limit_after = models.DecimalField(max_digits=12, decimal_places=2)
    timestamp = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-timestamp']
        indexes = [models.Index(fields=['family_pass', '-timestamp'], name='pass_activity_time_idx')]
        constraints = [models.CheckConstraint(condition=models.Q(amount__gt=0), name='pass_activity_amount_positive'), models.CheckConstraint(condition=models.Q(remaining_limit_after__gte=0), name='pass_activity_remaining_valid')]

    def __str__(self):
        return f"{self.member.username} spent ৳{self.amount} via FamilyPass ({self.family_pass.id})"


class NotificationType(models.TextChoices):
    FAMILY_PASS = 'FAMILY_PASS', 'FamilyPass Activity'
    ANOMALY_ALERT = 'ANOMALY_ALERT', 'Spending Anomaly'
    BUDGET_WARNING = 'BUDGET_WARNING', 'Budget Overrun Warning'
    TRANSACTION = 'TRANSACTION', 'Transaction Alert'
    SYSTEM = 'SYSTEM', 'System Alert'


class Notification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    title = models.CharField(max_length=200)
    message = models.TextField()
    notification_type = models.CharField(max_length=30, choices=NotificationType.choices, default=NotificationType.TRANSACTION)
    is_read = models.BooleanField(default=False)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.notification_type}] {self.title} -> {self.user.username}"


class FinancialGoal(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='financial_goals')
    name = models.CharField(max_length=150)
    target_amount = models.DecimalField(max_digits=12, decimal_places=2)
    current_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    deadline = models.DateField()
    status = models.CharField(max_length=20, default='IN_PROGRESS')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name}: ৳{self.current_amount} / ৳{self.target_amount}"


class AnomalyResult(models.Model):
    transaction = models.OneToOneField(Transaction, on_delete=models.CASCADE, related_name='anomaly_analysis')
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='anomalies')
    is_anomaly = models.BooleanField(default=False)
    anomaly_score = models.FloatField(default=0.0)
    reason = models.TextField(blank=True)
    features_summary = models.JSONField(default=dict, blank=True)
    model_version = models.CharField(max_length=50, default='iso_forest_v1.0')
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def prediction(self):
        return int(self.is_anomaly)

    class Meta:
        indexes = [models.Index(fields=['is_anomaly', '-created_at'], name='anomaly_flag_time_idx')]
        constraints = [models.CheckConstraint(condition=models.Q(anomaly_score__gte=0, anomaly_score__lte=1), name='anomaly_score_range')]

    def __str__(self):
        flag = "UNUSUAL" if self.is_anomaly else "NORMAL"
        return f"Txn {self.transaction.transaction_id} - {flag} (Score: {self.anomaly_score:.2f})"


class RiskLevel(models.TextChoices):
    SAFE = 'SAFE', 'Safe / On Track'
    MODERATE = 'MODERATE', 'Moderate Risk'
    HIGH_RISK = 'HIGH_RISK', 'High Risk of Overrun'


class BudgetForecast(models.Model):
    fund = models.ForeignKey(PurposeFund, on_delete=models.CASCADE, related_name='forecasts')
    month = models.CharField(max_length=20)  # e.g. "2026-10"
    allocated_budget = models.DecimalField(max_digits=12, decimal_places=2)
    current_spent = models.DecimalField(max_digits=12, decimal_places=2)
    predicted_amount = models.DecimalField(max_digits=12, decimal_places=2)
    potential_overrun = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    risk_level = models.CharField(max_length=20, choices=RiskLevel.choices, default=RiskLevel.SAFE)
    explanation = models.TextField(blank=True)
    model_version = models.CharField(max_length=50, default='linear_decay_forecaster_v1.0')
    created_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Forecast for {self.fund.name} [{self.month}]: Pred ৳{self.predicted_amount} (Budget ৳{self.allocated_budget})"


class InsightType(models.TextChoices):
    BUDGET_OVERRUN = 'BUDGET_OVERRUN', 'Budget Overrun Risk'
    SPENDING_TREND = 'SPENDING_TREND', 'Spending Trend'
    REALLOCATION = 'REALLOCATION', 'Fund Reallocation Recommendation'
    FAMILY_PASS_USAGE = 'FAMILY_PASS_USAGE', 'FamilyPass Utilization'
    SAVINGS_OPPORTUNITY = 'SAVINGS_OPPORTUNITY', 'Savings Opportunity'
    ANOMALY = 'ANOMALY', 'Unusual Spending Flag'


class AIInsight(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='ai_insights')
    insight_type = models.CharField(max_length=40, choices=InsightType.choices)
    title = models.CharField(max_length=200)
    description = models.TextField()
    action_type = models.CharField(max_length=50, default='NONE')
    action_payload = models.JSONField(default=dict, blank=True)
    confidence = models.FloatField(default=0.88)
    is_dismissed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.insight_type}] {self.title} for {self.user.username}"


class ExperimentCondition(models.TextChoices):
    BASELINE_SPREADSHEET = 'BASELINE', 'Baseline (Manual / Spreadsheet)'
    FUNDSHARE_PROTOTYPE = 'FUNDSHARE', 'FundShare Prototype'


class ExperimentRecord(models.Model):
    participant_id = models.CharField(max_length=50)
    condition = models.CharField(max_length=20, choices=ExperimentCondition.choices)
    task_index = models.IntegerField()
    task_description = models.CharField(max_length=255)
    completion_time_seconds = models.FloatField()
    is_correct = models.BooleanField(default=True)
    confidence_rating = models.IntegerField(default=5)  # 1 to 5 scale
    usability_score = models.FloatField(default=85.0)   # System Usability Scale or similar
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Exp {self.participant_id} | {self.condition} | Task {self.task_index} ({self.completion_time_seconds}s)"


class Contact(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='contacts')
    name = models.CharField(max_length=150)
    phone = models.CharField(max_length=30)
    username = models.CharField(max_length=150, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name', '-created_at']
        indexes = [
            models.Index(fields=['owner', 'phone']),
            models.Index(fields=['owner', 'name']),
        ]
        constraints = [
            models.UniqueConstraint(fields=['owner', 'phone'], name='unique_owner_contact_phone')
        ]

    def save(self, *args, **kwargs):
        from fundshare_app.services.phone_utils import normalize_phone
        if self.phone:
            self.phone = normalize_phone(self.phone)
        super().save(*args, **kwargs)

    @property
    def matched_user(self):
        from fundshare_app.services.phone_utils import find_user_by_phone
        return find_user_by_phone(self.phone)

    @property
    def is_registered(self):
        return self.matched_user is not None

    def __str__(self):
        return f"{self.name} ({self.phone}) - {self.owner.username}"
