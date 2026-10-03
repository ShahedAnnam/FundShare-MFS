from rest_framework import serializers
from decimal import Decimal
from fundshare_app.models import (
    User, Wallet, Merchant, PurposeFund, FundTransfer,
    FamilyPass, FamilyPassTransaction, Transaction, TransactionItem,
    Notification, AnomalyResult, BudgetForecast, AIInsight,
    ExperimentRecord, Contact
)


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'full_name', 'email', 'phone', 'role', 'avatar_url']


class WalletSerializer(serializers.ModelSerializer):
    owner = UserSerializer(read_only=True)

    class Meta:
        model = Wallet
        fields = ['id', 'owner', 'balance', 'updated_at']


class MerchantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Merchant
        fields = ['id', 'business_name', 'category', 'account_number', 'contact_phone', 'address', 'balance', 'is_active']


class PurposeFundSerializer(serializers.ModelSerializer):
    spent_amount = serializers.SerializerMethodField()
    utilization_pct = serializers.SerializerMethodField()
    recipient_username = serializers.CharField(source='recipient.username', read_only=True)
    recipient_name = serializers.CharField(source='recipient.full_name', read_only=True)

    class Meta:
        model = PurposeFund
        fields = [
            'id', 'name', 'category', 'allocated_amount', 'current_balance',
            'monthly_budget', 'icon', 'color', 'status', 'recipient',
            'recipient_username', 'recipient_name', 'created_at',
            'spent_amount', 'utilization_pct'
        ]

    def get_spent_amount(self, obj):
        alloc = float(obj.allocated_amount)
        curr = float(obj.current_balance)
        return max(0.0, round(alloc - curr, 2))

    def get_utilization_pct(self, obj):
        alloc = float(obj.allocated_amount)
        if alloc <= 0:
            return 0.0
        spent = max(0.0, alloc - float(obj.current_balance))
        return min(100.0, round((spent / alloc) * 100.0, 1))


class ContactSerializer(serializers.ModelSerializer):
    is_registered = serializers.BooleanField(read_only=True)
    account_status = serializers.SerializerMethodField()
    account_id = serializers.SerializerMethodField()
    matched_username = serializers.SerializerMethodField()
    avatar_url = serializers.SerializerMethodField()
    allowed_features = serializers.SerializerMethodField()

    class Meta:
        model = Contact
        fields = [
            'id', 'name', 'phone', 'username', 'created_at', 'updated_at',
            'is_registered', 'account_status', 'account_id', 'matched_username',
            'avatar_url', 'allowed_features'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_account_status(self, obj):
        return 'REGISTERED' if obj.is_registered else 'NOT_REGISTERED'

    def get_account_id(self, obj):
        u = obj.matched_user
        return u.id if u else None

    def get_matched_username(self, obj):
        u = obj.matched_user
        return u.username if u else (obj.username or None)

    def get_avatar_url(self, obj):
        u = obj.matched_user
        return getattr(u, 'avatar_url', '') if u else ''

    def get_allowed_features(self, obj):
        is_reg = obj.is_registered
        return {
            'send_money': is_reg,
            'fund_share': is_reg,
            'family_pass': is_reg,
            'mobile_recharge': True,
            'bill_payment': True,
        }



class FundTransferSerializer(serializers.ModelSerializer):
    source_fund_name = serializers.CharField(source='source_fund.name', read_only=True)
    destination_fund_name = serializers.CharField(source='destination_fund.name', read_only=True)

    class Meta:
        model = FundTransfer
        fields = ['id', 'source_fund', 'source_fund_name', 'destination_fund', 'destination_fund_name', 'amount', 'reason', 'timestamp']


class FamilyPassSerializer(serializers.ModelSerializer):
    owner_name = serializers.CharField(source='owner.full_name', read_only=True)
    owner_username = serializers.CharField(source='owner.username', read_only=True)
    member_name = serializers.CharField(source='member.full_name', read_only=True)
    member_username = serializers.CharField(source='member.username', read_only=True)
    remaining_limit = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    is_valid = serializers.BooleanField(source='is_valid_and_active', read_only=True)
    usage_pct = serializers.SerializerMethodField()

    class Meta:
        model = FamilyPass
        fields = [
            'id', 'owner', 'owner_name', 'owner_username', 'member', 'member_name', 'member_username',
            'limit_amount', 'used_amount', 'remaining_limit', 'start_date', 'expiry_date',
            'allowed_action', 'status', 'purpose_label', 'is_valid', 'usage_pct', 'created_at'
        ]

    def get_usage_pct(self, obj):
        limit = float(obj.limit_amount)
        if limit <= 0:
            return 0.0
        return min(100.0, round((float(obj.used_amount) / limit) * 100.0, 1))


class TransactionItemSerializer(serializers.ModelSerializer):
    item_name = serializers.CharField(source='name', read_only=True)
    line_total = serializers.DecimalField(source='total', max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = TransactionItem
        fields = [
            'id', 'name', 'item_name', 'product_id', 'quantity',
            'unit_price', 'discount', 'tax', 'total', 'line_total', 'created_at'
        ]


class TransactionSerializer(serializers.ModelSerializer):
    sender_name = serializers.CharField(source='sender.full_name', read_only=True)
    sender_username = serializers.CharField(source='sender.username', read_only=True)
    receiver_name = serializers.CharField(source='receiver.full_name', read_only=True)
    merchant_name = serializers.CharField(source='merchant.business_name', read_only=True)
    merchant_location = serializers.CharField(source='merchant.address', read_only=True, default='')
    purpose_fund_name = serializers.CharField(source='purpose_fund.name', read_only=True)
    items = TransactionItemSerializer(many=True, read_only=True)
    has_items = serializers.SerializerMethodField()
    has_anomaly = serializers.SerializerMethodField()
    anomaly_reason = serializers.SerializerMethodField()

    class Meta:
        model = Transaction
        fields = [
            'id', 'transaction_id', 'sender', 'sender_name', 'sender_username',
            'receiver', 'receiver_name', 'merchant', 'merchant_name', 'merchant_location', 'amount',
            'transaction_type', 'payment_source', 'purpose_fund', 'purpose_fund_name',
            'family_pass', 'category', 'status', 'rejection_reason', 'reference',
            'metadata', 'timestamp', 'has_anomaly', 'anomaly_reason', 'items', 'has_items'
        ]

    def get_has_items(self, obj):
        return obj.items.exists()

    def get_has_anomaly(self, obj):
        return hasattr(obj, 'anomaly_analysis') and obj.anomaly_analysis.is_anomaly

    def get_anomaly_reason(self, obj):
        if hasattr(obj, 'anomaly_analysis') and obj.anomaly_analysis.is_anomaly:
            return obj.anomaly_analysis.reason
        return ''


class FamilyPassTransactionSerializer(serializers.ModelSerializer):
    transaction_id = serializers.CharField(source='transaction.transaction_id', read_only=True)
    reference = serializers.CharField(source='transaction.reference', read_only=True, default='')
    status = serializers.CharField(source='transaction.status', read_only=True)
    payment_source = serializers.CharField(source='transaction.payment_source', read_only=True)
    member_name = serializers.SerializerMethodField()
    member_username = serializers.CharField(source='member.username', read_only=True)
    merchant_name = serializers.CharField(source='transaction.merchant.business_name', read_only=True, default='')
    merchant_location = serializers.CharField(source='transaction.merchant.address', read_only=True, default='')
    merchant = serializers.SerializerMethodField()
    category = serializers.CharField(source='transaction.category', read_only=True, default='')
    family_pass_label = serializers.CharField(source='family_pass.purpose_label', read_only=True, default='')
    items = serializers.SerializerMethodField()
    has_items = serializers.SerializerMethodField()

    class Meta:
        model = FamilyPassTransaction
        fields = [
            'id', 'family_pass', 'family_pass_label', 'transaction', 'transaction_id',
            'member_name', 'member_username', 'merchant_name', 'merchant_location', 'merchant',
            'category', 'amount', 'status', 'payment_source', 'reference',
            'remaining_limit_after', 'items', 'has_items', 'timestamp'
        ]

    def get_member_name(self, obj):
        return obj.member.full_name or obj.member.username

    def get_merchant(self, obj):
        if obj.transaction and obj.transaction.merchant:
            m = obj.transaction.merchant
            return {
                'id': m.id,
                'name': m.business_name,
                'category': m.category,
                'location': m.address,
                'phone': m.contact_phone
            }
        return None

    def get_items(self, obj):
        if obj.transaction:
            return TransactionItemSerializer(obj.transaction.items.all(), many=True).data
        return []

    def get_has_items(self, obj):
        if obj.transaction:
            return obj.transaction.items.exists()
        return False


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ['id', 'title', 'message', 'notification_type', 'is_read', 'metadata', 'created_at']


class AnomalyResultSerializer(serializers.ModelSerializer):
    transaction_id = serializers.CharField(source='transaction.transaction_id', read_only=True)
    amount = serializers.DecimalField(source='transaction.amount', max_digits=12, decimal_places=2, read_only=True)
    category = serializers.CharField(source='transaction.category', read_only=True)
    merchant_name = serializers.CharField(source='transaction.merchant.business_name', read_only=True, default='')

    class Meta:
        model = AnomalyResult
        fields = ['id', 'transaction_id', 'amount', 'category', 'merchant_name', 'is_anomaly', 'anomaly_score', 'reason', 'features_summary', 'model_version', 'created_at']


class BudgetForecastSerializer(serializers.ModelSerializer):
    fund_name = serializers.CharField(source='fund.name', read_only=True)
    fund_category = serializers.CharField(source='fund.category', read_only=True)

    class Meta:
        model = BudgetForecast
        fields = ['id', 'fund', 'fund_name', 'fund_category', 'month', 'allocated_budget', 'current_spent', 'predicted_amount', 'potential_overrun', 'risk_level', 'explanation', 'created_at']


class ExperimentRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExperimentRecord
        fields = ['id', 'participant_id', 'condition', 'task_index', 'task_description', 'completion_time_seconds', 'is_correct', 'confidence_rating', 'usability_score', 'notes', 'created_at']
