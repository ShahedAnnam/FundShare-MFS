from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from django.db import transaction
from .models import (
    User, Wallet, Merchant, PurposeFund, FundTransfer, FamilyPass,
    Transaction, TransactionItem, FamilyPassTransaction, Notification, FinancialGoal,
    AnomalyResult, BudgetForecast, AIInsight, ExperimentRecord, Contact
)


class FinancialReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False



class CustomUserCreationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'phone', 'full_name', 'role')


class CustomUserChangeForm(UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = User


class ReceivedFamilyPassInline(admin.TabularInline):
    model = FamilyPass
    fk_name = 'member'
    extra = 0
    fields = ('owner', 'purpose_label', 'limit_amount', 'used_amount', 'status', 'start_date', 'expiry_date')
    readonly_fields = ('owner', 'purpose_label', 'limit_amount', 'used_amount', 'status', 'start_date', 'expiry_date')
    can_delete = False
    verbose_name = 'Assigned FamilyPass'
    verbose_name_plural = 'Assigned FamilyPasses (Active, Revoked, Expired)'

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    form = CustomUserChangeForm
    add_form = CustomUserCreationForm
    list_display = (
        'username', 'full_name', 'email', 'phone',
        'effective_role_display', 'role', 'is_active', 'is_staff', 'is_superuser'
    )
    list_filter = ('role', 'is_staff', 'is_superuser', 'is_active', 'date_joined')
    search_fields = ('username', 'full_name', 'email', 'phone')
    ordering = ('username',)
    readonly_fields = ('effective_role_display', 'last_login', 'date_joined')
    inlines = [ReceivedFamilyPassInline]

    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Personal Info', {'fields': ('full_name', 'first_name', 'last_name', 'email', 'phone', 'avatar_url')}),
        ('FUNDShare Role & Access', {'fields': ('effective_role_display', 'role', 'is_active', 'is_staff', 'is_superuser')}),
        ('Advanced Permissions', {'fields': ('groups', 'user_permissions'), 'classes': ('collapse',)}),
        ('Important Dates', {'fields': ('last_login', 'date_joined')}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'phone', 'full_name', 'role', 'password1', 'password2'),
        }),
    )

    @admin.display(description='Account Role')
    def effective_role_display(self, obj):
        return obj.get_effective_role_display()

    @transaction.atomic
    def save_model(self, request, obj, form, change):
        if change:
            current = User.objects.select_for_update().get(pk=obj.pk)
            for field in ('transaction_pin', 'pin_failed_attempts', 'pin_locked_until'):
                setattr(obj, field, getattr(current, field))
        super().save_model(request, obj, form, change)


@admin.register(Wallet)
class WalletAdmin(FinancialReadOnlyAdmin):
    list_display = ('id', 'owner', 'balance', 'created_at', 'updated_at')
    list_filter = ('created_at', 'updated_at')
    search_fields = ('owner__username', 'owner__full_name', 'owner__phone', 'owner__email')
    readonly_fields = ('created_at', 'updated_at')
    raw_id_fields = ('owner',)
    ordering = ('-created_at',)


@admin.register(Merchant)
class MerchantAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'business_name', 'category', 'account_number',
        'contact_phone', 'balance', 'is_active', 'user', 'created_at'
    )
    list_filter = ('category', 'is_active', 'created_at')
    search_fields = ('business_name', 'account_number', 'contact_phone', 'user__username', 'address')
    readonly_fields = ('created_at', 'balance')
    raw_id_fields = ('user',)
    ordering = ('business_name',)

    def has_delete_permission(self, request, obj=None):
        return False

    @transaction.atomic
    def save_model(self, request, obj, form, change):
        if change:
            current = Merchant.objects.select_for_update().get(pk=obj.pk)
            obj.balance = current.balance
        super().save_model(request, obj, form, change)


@admin.register(PurposeFund)
class PurposeFundAdmin(FinancialReadOnlyAdmin):
    list_display = (
        'id', 'name', 'owner', 'recipient', 'category', 'current_balance',
        'allocated_amount', 'monthly_budget', 'status', 'created_at'
    )
    list_filter = ('status', 'category', 'created_at')
    search_fields = ('name', 'owner__username', 'owner__full_name', 'owner__phone', 'recipient__username')
    readonly_fields = ('created_at', 'updated_at')
    raw_id_fields = ('owner', 'recipient')
    ordering = ('-created_at',)



@admin.register(FundTransfer)
class FundTransferAdmin(FinancialReadOnlyAdmin):
    list_display = ('id', 'owner', 'source_fund', 'destination_fund', 'amount', 'reason', 'timestamp')
    list_filter = ('timestamp',)
    search_fields = ('owner__username', 'source_fund__name', 'destination_fund__name', 'reason')
    readonly_fields = ('timestamp',)
    raw_id_fields = ('owner', 'source_fund', 'destination_fund')
    ordering = ('-timestamp',)


@admin.register(FamilyPass)
class FamilyPassAdmin(FinancialReadOnlyAdmin):
    list_display = (
        'id', 'owner', 'member', 'purpose_display', 'limit_amount', 'used_amount',
        'remaining_limit_display', 'status',
        'start_date', 'expiry_date'
    )
    list_filter = ('status', 'purpose', 'allowed_action', 'start_date', 'expiry_date')
    search_fields = ('owner__username', 'member__username', 'purpose_label', 'custom_purpose')
    readonly_fields = ('created_at', 'updated_at', 'remaining_limit_display')
    raw_id_fields = ('owner', 'member')
    ordering = ('-created_at',)

    @admin.display(description='Purpose')
    def purpose_display(self, obj):
        return obj.purpose_label

    @admin.display(description='Remaining Limit (৳)')
    def remaining_limit_display(self, obj):
        return f"৳{obj.remaining_limit:,.2f}"


class TransactionItemInline(admin.TabularInline):
    model = TransactionItem
    extra = 0
    fields = ('name', 'product_id', 'quantity', 'unit_price', 'discount', 'tax', 'total', 'created_at')
    readonly_fields = ('name', 'product_id', 'quantity', 'unit_price', 'discount', 'tax', 'total', 'created_at')
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Transaction)
class TransactionAdmin(FinancialReadOnlyAdmin):
    list_display = (
        'transaction_id', 'transaction_type', 'amount',
        'sender', 'receiver', 'merchant', 'payment_source',
        'status', 'timestamp'
    )
    list_filter = ('status', 'transaction_type', 'payment_source', 'category', 'timestamp')
    search_fields = (
        'transaction_id', 'sender__username', 'receiver__username',
        'reference', 'category', 'rejection_reason'
    )
    readonly_fields = ('timestamp',)
    raw_id_fields = ('sender', 'receiver', 'merchant', 'purpose_fund', 'family_pass')
    inlines = [TransactionItemInline]
    ordering = ('-timestamp',)


@admin.register(TransactionItem)
class TransactionItemAdmin(FinancialReadOnlyAdmin):
    list_display = (
        'id', 'transaction_link', 'name', 'product_id', 'quantity',
        'unit_price', 'discount', 'tax', 'total', 'merchant_display', 'created_at'
    )
    list_filter = ('created_at', 'transaction__payment_source', 'transaction__status')
    search_fields = (
        'name', 'product_id', 'transaction__transaction_id',
        'transaction__merchant__business_name'
    )
    readonly_fields = (
        'transaction', 'name', 'product_id', 'quantity',
        'unit_price', 'discount', 'tax', 'total', 'created_at'
    )
    ordering = ('-created_at',)

    @admin.display(description='Transaction ID')
    def transaction_link(self, obj):
        return obj.transaction.transaction_id

    @admin.display(description='Merchant')
    def merchant_display(self, obj):
        return obj.transaction.merchant.business_name if obj.transaction and obj.transaction.merchant else '-'

    def has_add_permission(self, request):
        return False


@admin.register(FamilyPassTransaction)
class FamilyPassTransactionAdmin(FinancialReadOnlyAdmin):
    list_display = (
        'id', 'family_pass', 'member', 'amount',
        'remaining_limit_after', 'transaction', 'timestamp'
    )
    list_filter = ('timestamp',)
    search_fields = ('member__username', 'transaction__transaction_id')
    readonly_fields = ('timestamp',)
    raw_id_fields = ('family_pass', 'transaction', 'member')
    ordering = ('-timestamp',)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'title', 'notification_type', 'is_read', 'created_at')
    list_filter = ('notification_type', 'is_read', 'created_at')
    search_fields = ('user__username', 'title', 'message')
    readonly_fields = ('created_at',)
    raw_id_fields = ('user',)
    ordering = ('-created_at',)


@admin.register(FinancialGoal)
class FinancialGoalAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'name', 'owner', 'target_amount',
        'current_amount', 'deadline', 'status', 'created_at'
    )
    list_filter = ('status', 'deadline', 'created_at')
    search_fields = ('name', 'owner__username')
    readonly_fields = ('created_at',)
    raw_id_fields = ('owner',)
    ordering = ('-created_at',)


@admin.register(AnomalyResult)
class AnomalyResultAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'transaction', 'user', 'is_anomaly',
        'anomaly_score', 'model_version', 'created_at'
    )
    list_filter = ('is_anomaly', 'model_version', 'created_at')
    search_fields = ('user__username', 'transaction__transaction_id', 'reason')
    readonly_fields = ('created_at',)
    raw_id_fields = ('transaction', 'user')
    ordering = ('-created_at',)


@admin.register(BudgetForecast)
class BudgetForecastAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'fund', 'month', 'allocated_budget',
        'current_spent', 'predicted_amount', 'potential_overrun',
        'risk_level', 'created_at'
    )
    list_filter = ('risk_level', 'month', 'created_at')
    search_fields = ('fund__name', 'explanation')
    readonly_fields = ('created_at',)
    raw_id_fields = ('fund',)
    ordering = ('-created_at',)


@admin.register(AIInsight)
class AIInsightAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'insight_type', 'title', 'confidence', 'is_dismissed', 'created_at')
    list_filter = ('insight_type', 'is_dismissed', 'created_at')
    search_fields = ('user__username', 'title', 'description')
    readonly_fields = ('created_at',)
    raw_id_fields = ('user',)
    ordering = ('-created_at',)


@admin.register(ExperimentRecord)
class ExperimentRecordAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'participant_id', 'condition', 'task_index',
        'completion_time_seconds', 'is_correct', 'confidence_rating',
        'usability_score', 'created_at'
    )
    list_filter = ('condition', 'is_correct', 'confidence_rating', 'created_at')
    search_fields = ('participant_id', 'task_description', 'notes')
    readonly_fields = ('created_at',)
    ordering = ('-created_at',)


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'phone', 'owner', 'username', 'is_registered_display', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('name', 'phone', 'username', 'owner__username', 'owner__full_name')
    readonly_fields = ('created_at', 'updated_at', 'is_registered_display')
    raw_id_fields = ('owner',)
    ordering = ('name',)

    @admin.display(boolean=True, description='Registered Account')
    def is_registered_display(self, obj):
        return obj.is_registered
