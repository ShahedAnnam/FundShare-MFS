from rest_framework import serializers
from decimal import Decimal
from fundshare_app.models import (
    User, Wallet, Merchant, PurposeFund, FundTransfer,
    FamilyPass, FamilyPassTransaction, Transaction,
    Notification, AnomalyResult, BudgetForecast, AIInsight,
    ExperimentRecord
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

    class Meta:
        model = PurposeFund
        fields = [
            'id', 'name', 'category', 'allocated_amount', 'current_balance',
            'monthly_budget', 'icon', 'color', 'status', 'created_at',
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


class TransactionSerializer(serializers.ModelSerializer):
    sender_name = serializers.CharField(source='sender.full_name', read_only=True)
    sender_username = serializers.CharField(source='sender.username', read_only=True)
    receiver_name = serializers.CharField(source='receiver.full_name', read_only=True)
    merchant_name = serializers.CharField(source='merchant.business_name', read_only=True)
    purpose_fund_name = serializers.CharField(source='purpose_fund.name', read_only=True)
    has_anomaly = serializers.SerializerMethodField()
    anomaly_reason = serializers.SerializerMethodField()

    class Meta:
        model = Transaction
        fields = [
            'id', 'transaction_id', 'sender', 'sender_name', 'sender_username',
            'receiver', 'receiver_name', 'merchant', 'merchant_name', 'amount',
            'transaction_type', 'payment_source', 'purpose_fund', 'purpose_fund_name',
            'family_pass', 'category', 'status', 'rejection_reason', 'reference',
            'metadata', 'timestamp', 'has_anomaly', 'anomaly_reason'
        ]

    def get_has_anomaly(self, obj):
        return hasattr(obj, 'anomaly_analysis') and obj.anomaly_analysis.is_anomaly

    def get_anomaly_reason(self, obj):
        if hasattr(obj, 'anomaly_analysis') and obj.anomaly_analysis.is_anomaly:
            return obj.anomaly_analysis.reason
        return ''


class FamilyPassTransactionSerializer(serializers.ModelSerializer):
    member_name = serializers.CharField(source='member.full_name', read_only=True)
    merchant_name = serializers.CharField(source='transaction.merchant.business_name', read_only=True)
    category = serializers.CharField(source='transaction.category', read_only=True)

    class Meta:
        model = FamilyPassTransaction
        fields = ['id', 'family_pass', 'transaction', 'member_name', 'merchant_name', 'category', 'amount', 'remaining_limit_after', 'timestamp']


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
