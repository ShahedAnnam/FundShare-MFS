import datetime
from decimal import Decimal
from django.utils import timezone
from django.contrib.auth import authenticate, login, logout, get_user_model
from django.shortcuts import get_object_or_404
from django.db.models import Q
from django.db import transaction as db_transaction
from django.conf import settings
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from fundshare_app.views.security import AuthenticatedAPIView as APIView, AdminAPIView, FinancialAPIView, WalletUserPermission, CustomerPermission
from fundshare_app.services.security_service import SecurityError, verify_pin, validate_new_pin, check_login_rate, record_login_failure, clear_login_failures, check_registration_rate
from fundshare_app.forms import RegistrationForm
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated

from fundshare_app.models import (
    UserRole, Wallet, Merchant, PurposeFund, FundTransfer,
    FamilyPass, FamilyPassStatus, FamilyPassAction,
    Transaction, TransactionType, PaymentSource, TransactionStatus,
    Notification, NotificationType, AnomalyResult, BudgetForecast, AIInsight,
    ExperimentRecord, ExperimentCondition, Contact, FundStatus,
    FamilyPassPurpose, BusinessCategory
)

from fundshare_app.serializers.api_serializers import (
    UserSerializer, WalletSerializer, MerchantSerializer,
    PurposeFundSerializer, FundTransferSerializer,
    FamilyPassSerializer, TransactionSerializer,
    FamilyPassTransactionSerializer, NotificationSerializer,
    AnomalyResultSerializer, BudgetForecastSerializer,
    ExperimentRecordSerializer, ContactSerializer
)
from fundshare_app.services.transaction_service import TransactionService, TransactionValidationError
from fundshare_app.services.report_service import ReportService
from fundshare_app.services.contact_service import ContactService
from fundshare_app.services.recipient_service import RecipientService
from fundshare_app.services.phone_utils import normalize_phone, is_valid_bd_phone, find_user_by_phone_or_username
from fundshare_app.ml.anomaly_detector import AnomalyDetector
from fundshare_app.ml.budget_forecaster import BudgetForecaster
from fundshare_app.ml.recommendation_engine import RecommendationEngine
from fundshare_app.ml.ai_coach import AICoach
from fundshare_app.ml.data_generator import SyntheticDataGenerator

User = get_user_model()

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




def get_authenticated_user(request):
    if request.user and request.user.is_authenticated and request.user.is_active:
        return request.user
    return None


def require_auth(request):
    """Returns (user, error_response) tuple. If user is None, error_response is a 401 Response."""
    user = get_authenticated_user(request)
    if user is None:
        return None, Response(
            {"error": "Authentication required. Please log in.", "redirect": "/login/"},
            status=status.HTTP_401_UNAUTHORIZED
        )
    return user, None


# ==================== AUTHENTICATION ====================

@method_decorator(csrf_protect, name='dispatch')
class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        if not isinstance(request.data, dict):
            return Response({'error': 'Login details must be an object.'}, status=400)
        username = request.data.get('username', '')
        password = request.data.get('password', '')
        if not isinstance(username, str) or not isinstance(password, str) or not username.strip() or not password:
            return Response({'error': 'Enter your username or phone number and password.'}, status=400)
        username = username.strip()
        # Support normalized phone number or username login
        user_obj = find_user_by_phone_or_username(username)
        try:
            check_login_rate(request, user_obj.username if user_obj else username)
        except SecurityError as exc:
            return Response({'error': exc.message, 'code': exc.code}, status=exc.status)
        if user_obj:
            user = authenticate(request, username=user_obj.username, password=password)
        else:
            user = authenticate(request, username=username, password=password)
        if user:
            clear_login_failures(request, user.username)
            login(request, user)
            wallet, _ = Wallet.objects.get_or_create(owner=user)
            return Response({
                "message": "Login successful",
                "user": UserSerializer(user).data,
                "wallet_balance": float(wallet.balance),
                "role": user.effective_role,
                "effective_role": user.effective_role,
                "effective_role_display": user.get_effective_role_display()
            })
        record_login_failure(request, user_obj.username if user_obj else username)
        return Response({"error": "Invalid phone number or password"}, status=status.HTTP_401_UNAUTHORIZED)


@method_decorator(csrf_protect, name='dispatch')
class RegistrationView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        if request.user.is_authenticated:
            return Response({'error': 'Sign out before creating another account.', 'code': 'ALREADY_AUTHENTICATED'}, status=409)
        try:
            check_registration_rate(request)
            if not isinstance(request.data, dict):
                return Response({'error': 'Registration details must be an object.', 'code': 'INVALID_REGISTRATION'}, status=400)
            if any(not isinstance(request.data.get(name, ''), str) for name in RegistrationForm.base_fields):
                return Response({'error': 'Registration fields must be text.', 'code': 'INVALID_REGISTRATION'}, status=400)
            form = RegistrationForm(request.data)
            if not form.is_valid():
                return Response({
                    'error': 'Check your registration details.', 'code': 'INVALID_REGISTRATION',
                    'errors': {field: list(errors) for field, errors in form.errors.items()},
                }, status=400)
            user = form.save()
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')
            return Response({
                'message': 'Account created successfully.', 'user': UserSerializer(user).data,
                'wallet_balance': 0.0, 'role': user.effective_role,
                'effective_role': user.effective_role,
                'effective_role_display': user.get_effective_role_display(),
            }, status=201)
        except SecurityError as exc:
            return Response({'error': exc.message, 'code': exc.code}, status=exc.status)


class LogoutView(APIView):
    def post(self, request):
        logout(request)
        return Response({"message": "Logged out successfully"})


class MeView(APIView):
    def get(self, request):
        user, err = require_auth(request)
        if err:
            return err
        wallet, _ = Wallet.objects.get_or_create(owner=user)
        unread = Notification.objects.filter(user=user, is_read=False)
        if user.effective_role != UserRole.ADMIN:
            unread = unread.exclude(notification_type=NotificationType.ANOMALY_ALERT)
        unread_notifications = unread.count()

        # Check if user has active received FamilyPasses
        today = timezone.localdate() if timezone.is_aware(timezone.now()) else timezone.now().date()
        received_passes = FamilyPass.objects.filter(member=user, status=FamilyPassStatus.ACTIVE, start_date__lte=today, expiry_date__gte=today)

        return Response({
            "user": UserSerializer(user).data,
            "role": user.effective_role,
            "effective_role": user.effective_role,
            "effective_role_display": user.get_effective_role_display(),
            "wallet_balance": float(wallet.balance),
            "unread_notifications": unread_notifications,
            "received_family_passes_count": received_passes.count()
        })


class TransactionPINView(APIView):
    def post(self, request):
        try:
            if not isinstance(request.data, dict):
                return Response({'error': 'PIN details must be an object.'}, status=400)
            validate_new_pin(request.data.get('new_pin'))
            check_login_rate(request, 'pin-setup:' + request.user.username)
            password = request.data.get('password', '')
            if not isinstance(password, str) or not request.user.check_password(password):
                record_login_failure(request, 'pin-setup:' + request.user.username)
                return Response({'error': 'Incorrect account password.', 'code': 'PASSWORD_INVALID'}, status=403)
            clear_login_failures(request, 'pin-setup:' + request.user.username)
            with db_transaction.atomic():
                account = User.objects.select_for_update().get(pk=request.user.pk)
                if account.transaction_pin:
                    # Failed attempts must commit even when the change is rejected.
                    changing = True
                else:
                    changing = False
            if changing:
                verify_pin(request.user, request.data.get('current_pin'))
            with db_transaction.atomic():
                account = User.objects.select_for_update().get(pk=request.user.pk)
                if account.transaction_pin != request.user.transaction_pin:
                    return Response({'error': 'Your PIN changed. Sign in again before continuing.', 'code': 'PIN_CHANGED'}, status=409)
                account.set_transaction_pin(request.data['new_pin'])
                account.pin_failed_attempts = 0
                account.pin_locked_until = None
                account.save(update_fields=['transaction_pin', 'pin_failed_attempts', 'pin_locked_until'])
            return Response({'message': 'Transaction PIN saved.', 'has_transaction_pin': True})
        except SecurityError as exc:
            return Response({'error': exc.message, 'code': exc.code}, status=exc.status)


# ==================== WALLET & TRANSACTIONS ====================

class WalletSummaryView(APIView):
    def get(self, request):
        user, err = require_auth(request)
        if err:
            return err
        wallet, _ = Wallet.objects.get_or_create(owner=user)

        funds = PurposeFund.objects.filter(owner=user, status='ACTIVE')
        funds_total = sum([float(f.current_balance) for f in funds])
        allocated_total = sum([float(f.allocated_amount) for f in funds])

        # Active FamilyPass permissions issued
        active_fps = FamilyPass.objects.filter(owner=user, status=FamilyPassStatus.ACTIVE)
        fp_total_limit = sum([float(fp.limit_amount) for fp in active_fps])
        fp_total_used = sum([float(fp.used_amount) for fp in active_fps])

        # Recent transactions (all activity relevant to user: sent, received, or FamilyPass funded by owner)
        recent_txns = Transaction.objects.filter(
            Q(sender=user) | Q(receiver=user) | Q(family_pass__owner=user)
        ).distinct().order_by('-timestamp')[:6]

        # Forecasts / warnings
        overrun_funds = []
        for f in funds:
            fc = BudgetForecaster.forecast_fund(f)
            if fc["potential_overrun"] > 0:
                overrun_funds.append(fc)

        return Response({
            "wallet_balance": float(wallet.balance),
            "funds_total_balance": round(funds_total, 2),
            "funds_allocated_total": round(allocated_total, 2),
            "total_liquid_wealth": round(float(wallet.balance) + funds_total, 2),
            "active_family_passes_count": active_fps.count(),
            "family_pass_total_limit": round(fp_total_limit, 2),
            "family_pass_total_used": round(fp_total_used, 2),
            "overrun_funds_count": len(overrun_funds),
            "overrun_funds": overrun_funds,
            "recent_transactions": TransactionSerializer(recent_txns, many=True).data
        })


class CashInView(FinancialAPIView):
    def post(self, request):
        if not settings.ENABLE_SIMULATED_CASH_IN:
            return Response({'error': 'Add Money requires a verified payment provider. Simulated cash-in is disabled.', 'code': 'CASH_IN_DISABLED'}, status=403)
        user, err = require_auth(request)
        if err:
            return err
        try:
            amount = Decimal(str(request.data.get('amount', '0')))
            ref = request.data.get('reference', 'Simulated Bank Add Money')
            txn = TransactionService.execute_transaction(
                sender=user,
                transaction_type=TransactionType.CASH_IN,
                amount=amount,
                reference=ref
            )
            return Response({
                "message": f"Successfully added ৳{amount:,.2f} to wallet",
                "transaction": TransactionSerializer(txn).data,
                "new_balance": float(user.wallet.balance)
            })
        except TransactionValidationError as e:
            return Response({"error": e.message, "code": e.code}, status=status.HTTP_400_BAD_REQUEST)


class SendMoneyView(FinancialAPIView):
    def post(self, request):
        user, err = require_auth(request)
        if err:
            return err
        try:
            amount = Decimal(str(request.data.get('amount', '0')))
            receiver_identifier = request.data.get('receiver_phone', request.data.get('receiver'))
            is_eligible, err_msg, receiver = RecipientService.check_recipient_eligibility(receiver_identifier, feature='SEND_MONEY')

            if not is_eligible or not receiver:
                return Response(
                    {"error": err_msg, "code": RecipientService.rejection_code(receiver_identifier, receiver)},
                    status=status.HTTP_400_BAD_REQUEST
                )


            txn = TransactionService.execute_transaction(
                sender=user,
                receiver=receiver,
                transaction_type=TransactionType.SEND_MONEY,
                amount=amount,
                reference=request.data.get('reference', '')
            )
            return Response({
                "message": f"Successfully sent ৳{amount:,.2f} to {receiver.full_name or receiver.phone or 'Customer'}",
                "transaction": TransactionSerializer(txn).data,
                "remaining_balance": float(user.wallet.balance)
            })
        except TransactionValidationError as e:
            return Response({"error": e.message, "code": e.code}, status=status.HTTP_400_BAD_REQUEST)


class UtilityServicesView(FinancialAPIView):
    """
    Handles Mobile Recharge, Bill Payment, and Cash Out
    """
    def post(self, request):
        user, err = require_auth(request)
        if err:
            return err
        action_type = request.data.get('action_type')  # 'RECHARGE', 'BILL', 'CASHOUT'
        try:
            amount = Decimal(str(request.data.get('amount', '0')))
            type_map = {
                'RECHARGE': TransactionType.MOBILE_RECHARGE,
                'BILL': TransactionType.BILL_PAYMENT,
                'CASHOUT': TransactionType.CASH_OUT,
            }
            if action_type not in type_map:
                return Response({'error': 'Select Recharge, Bill Payment, or Cash Out.', 'code': 'INVALID_ACTION'}, status=400)
            txn_type = type_map[action_type]

            payment_source = request.data.get('payment_source', PaymentSource.NORMAL_WALLET)
            family_pass_id = request.data.get('family_pass_id')
            family_pass = None

            if txn_type == TransactionType.BILL_PAYMENT and payment_source == PaymentSource.FAMILY_PASS:
                if not family_pass_id:
                    return Response({
                        "success": False,
                        "error": "FamilyPass is required for FamilyPass payment.",
                        "code": "FAMILYPASS_REQUIRED"
                    }, status=status.HTTP_400_BAD_REQUEST)
                try:
                    family_pass = FamilyPass.objects.get(id=family_pass_id)
                except (FamilyPass.DoesNotExist, ValueError):
                    return Response({
                        "success": False,
                        "error": "Selected FamilyPass was not found or is invalid.",
                        "code": "FAMILYPASS_NOT_FOUND"
                    }, status=status.HTTP_400_BAD_REQUEST)

            category = request.data.get('category')
            provider = request.data.get('provider')
            if txn_type == TransactionType.BILL_PAYMENT:
                if not isinstance(provider, str) or provider not in TransactionService.BILL_PROVIDER_CATEGORIES:
                    return Response({'error': 'Select an approved bill provider.', 'code': 'PROVIDER_UNAUTHORIZED'}, status=400)
                category = TransactionService.BILL_PROVIDER_CATEGORIES[provider]
            bill_type = request.data.get('bill_type')
            metadata = {
                'provider': provider,
                'bill_type': bill_type,
                'account_number': request.data.get('account_number', '')
            }

            txn = TransactionService.execute_transaction(
                sender=user,
                transaction_type=txn_type,
                amount=amount,
                payment_source=payment_source,
                family_pass=family_pass,
                category=category,
                reference=request.data.get('reference', ''),
                metadata=metadata
            )
            return Response({
                "message": f"Successfully processed {action_type.title()} of ৳{amount:,.2f}",
                "transaction": TransactionSerializer(txn).data,
                "remaining_balance": float(user.wallet.balance)
            })
        except TransactionValidationError as e:
            request.rejected_transaction = getattr(e, 'audit_data', None)
            return Response({
                "error": e.message,
                "code": e.code,
                "is_category_mismatch": e.code in ["CATEGORY_RESTRICTION_ERROR", "FAMILYPASS_CATEGORY_MISMATCH"]
            }, status=status.HTTP_400_BAD_REQUEST)


# ==================== PURPOSE FUNDS ====================

class PurposeFundsListView(FinancialAPIView):
    def get(self, request):
        user, err = require_auth(request)
        if err:
            return err
        funds = PurposeFund.objects.filter(owner=user, status='ACTIVE')
        data = PurposeFundSerializer(funds, many=True).data

        # Attach real-time forecasts to each fund
        for item in data:
            fund_obj = PurposeFund.objects.get(id=item["id"])
            fc = BudgetForecaster.forecast_fund(fund_obj)
            item["forecast"] = fc

        return Response(data)

    def post(self, request):
        user, err = require_auth(request)
        if err:
            return err
        try:
            name = request.data.get('name')
            category = request.data.get('category')
            initial_allocation = Decimal(str(request.data.get('allocated_amount', '0')))
            budget = Decimal(str(request.data.get('monthly_budget', str(initial_allocation))))
            icon = request.data.get('icon', 'wallet')
            color = request.data.get('color', '#10B981')

            if not name or not category:
                return Response({"error": "Fund name and business category are required."}, status=status.HTTP_400_BAD_REQUEST)

            TransactionService.validate_amount(initial_allocation, allow_zero=True)
            TransactionService.validate_amount(budget, allow_zero=True)
            if category not in BusinessCategory.values:
                return Response({'error': 'Select a valid business category.'}, status=400)

            recipient_identifier = request.data.get('recipient')
            recipient_user = None
            if recipient_identifier not in (None, ''):
                is_eligible, err_msg, recipient_user = RecipientService.check_recipient_eligibility(recipient_identifier, feature='FUND_SHARE')
                if not is_eligible or not recipient_user:
                    return Response({"error": err_msg, "code": RecipientService.rejection_code(recipient_identifier, recipient_user)}, status=status.HTTP_400_BAD_REQUEST)

            fund = PurposeFund.objects.create(
                owner=user,
                name=name,
                category=category,
                allocated_amount=Decimal('0.00'),
                current_balance=Decimal('0.00'),
                monthly_budget=budget,
                icon=icon,
                color=color,
                recipient=recipient_user
            )


            if initial_allocation > Decimal('0.00'):
                TransactionService.allocate_to_fund(user, fund, initial_allocation)

            return Response(PurposeFundSerializer(fund).data, status=status.HTTP_201_CREATED)
        except TransactionValidationError as e:
            return Response({'error': e.message, 'code': e.code}, status=400)


class PurposeFundAllocateView(FinancialAPIView):
    def post(self, request, pk):
        user, err = require_auth(request)
        if err:
            return err
        fund = get_object_or_404(PurposeFund, id=pk, owner=user)
        try:
            amount = Decimal(str(request.data.get('amount', '0')))
            updated_fund = TransactionService.allocate_to_fund(user, fund, amount)
            return Response({
                "message": f"Successfully allocated ৳{amount:,.2f} to {fund.name} Fund",
                "fund": PurposeFundSerializer(updated_fund).data,
                "wallet_balance": float(user.wallet.balance)
            })
        except TransactionValidationError as e:
            return Response({"error": e.message}, status=status.HTTP_400_BAD_REQUEST)


class PurposeFundTransferView(FinancialAPIView):
    """
    Explicit user-initiated inter-fund transfer.
    AI may recommend it, but user performs the transfer.
    """
    def post(self, request):
        user, err = require_auth(request)
        if err:
            return err
        source_id = request.data.get('source_fund_id')
        dest_id = request.data.get('destination_fund_id')
        try:
            amount = Decimal(str(request.data.get('amount', '0')))
            reason = request.data.get('reason', '')

            source_fund = get_object_or_404(PurposeFund, id=source_id, owner=user)
            dest_fund = get_object_or_404(PurposeFund, id=dest_id, owner=user)

            transfer = TransactionService.transfer_between_funds(
                user=user,
                source_fund=source_fund,
                destination_fund=dest_fund,
                amount=amount,
                reason=reason
            )
            return Response({
                "message": f"Transferred ৳{amount:,.2f} from {source_fund.name} to {dest_fund.name}",
                "transfer": FundTransferSerializer(transfer).data,
                "source_fund": PurposeFundSerializer(source_fund).data,
                "destination_fund": PurposeFundSerializer(dest_fund).data
            })
        except TransactionValidationError as e:
            return Response({"error": e.message}, status=status.HTTP_400_BAD_REQUEST)


class PurposeFundDetailView(APIView):
    def get(self, request, pk):
        user, err = require_auth(request)
        if err:
            return err
        fund = get_object_or_404(PurposeFund, id=pk, owner=user)
        txns = Transaction.objects.filter(purpose_fund=fund).order_by('-timestamp')
        forecast = BudgetForecaster.forecast_fund(fund)

        # Monthly spending chart points for this fund
        return Response({
            "fund": PurposeFundSerializer(fund).data,
            "forecast": forecast,
            "transactions": TransactionSerializer(txns[:15], many=True).data,
            "total_transactions": txns.count()
        })


class PurposeFundManageView(FinancialAPIView):
    """
    CRUD management for an existing PurposeFund / FundShare:
    - GET: retrieve fund details
    - PATCH / PUT: edit fund name, category, monthly_budget, icon, color, recipient
    - DELETE: safe deletion or archival. If the fund has financial history, it is safely
      archived so transactions are preserved. Remaining balance is returned to owner's wallet.
    """
    def get(self, request, pk):
        user, err = require_auth(request)
        if err:
            return err
        fund = get_object_or_404(PurposeFund, id=pk, owner=user)
        return Response(PurposeFundSerializer(fund).data)

    def patch(self, request, pk):
        user, err = require_auth(request)
        if err:
            return err
        with db_transaction.atomic():
            TransactionService.lock_wallets([user.id])
            fund = get_object_or_404(PurposeFund.objects.select_for_update(), id=pk, owner=user)
            return self._update_fund(request, fund)

    def _update_fund(self, request, fund):
        user = request.user
        try:
            if 'name' in request.data:
                name = request.data.get('name', '').strip()
                if not name:
                    return Response({"error": "Fund name cannot be empty."}, status=status.HTTP_400_BAD_REQUEST)
                fund.name = name

            if 'category' in request.data:
                cat = request.data.get('category')
                if cat:
                    if cat not in BusinessCategory.values:
                        return Response({'error': 'Select a valid business category.'}, status=400)
                    fund.category = cat

            if 'monthly_budget' in request.data:
                budget = Decimal(str(request.data.get('monthly_budget', '0')))
                TransactionService.validate_amount(budget, allow_zero=True)
                fund.monthly_budget = budget

            if 'icon' in request.data:
                fund.icon = request.data.get('icon', fund.icon)

            if 'color' in request.data:
                fund.color = request.data.get('color', fund.color)

            if 'recipient' in request.data:
                recip_ident = request.data.get('recipient')
                if recip_ident not in (None, ''):
                    is_eligible, err_msg, recip_user = RecipientService.check_recipient_eligibility(recip_ident, feature='FUND_SHARE')
                    if not is_eligible or not recip_user:
                        return Response(
                            {"error": err_msg, "code": RecipientService.rejection_code(recip_ident, recip_user)},
                            status=status.HTTP_400_BAD_REQUEST
                        )
                    fund.recipient = recip_user
                else:
                    fund.recipient = None

            fund.save()
            return Response({
                "message": f"Fund '{fund.name}' updated successfully.",
                "fund": PurposeFundSerializer(fund).data
            })
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def put(self, request, pk):
        return self.patch(request, pk)

    def delete(self, request, pk):
        user, err = require_auth(request)
        if err:
            return err
        TransactionService.lock_wallets([user.id])
        fund = get_object_or_404(PurposeFund.objects.select_for_update(), id=pk, owner=user, status=FundStatus.ACTIVE)

        # Check for prior financial history (transactions or inter-fund transfers)
        has_txns = Transaction.objects.filter(purpose_fund=fund).exists()
        has_transfers = FundTransfer.objects.filter(Q(source_fund=fund) | Q(destination_fund=fund)).exists()
        has_history = has_txns or has_transfers

        refund_amount = fund.current_balance
        if refund_amount > Decimal('0.00'):
            wallet, _ = Wallet.objects.get_or_create(owner=user)
            wallet.balance += refund_amount
            wallet.save(update_fields=['balance', 'updated_at'])
            Transaction.objects.create(
                sender=user,
                receiver=user,
                amount=refund_amount,
                transaction_type=TransactionType.CASH_IN,
                payment_source=PaymentSource.NORMAL_WALLET,
                purpose_fund=fund if has_history else None,
                category='Deposit',
                status=TransactionStatus.COMPLETED,
                reference=f"Refund from closed fund '{fund.name}'"
            )
            fund.current_balance = Decimal('0.00')

        if has_history:
            fund.status = FundStatus.ARCHIVED
            fund.save(update_fields=['status', 'current_balance', 'updated_at'])
            return Response({
                "message": f"Fund '{fund.name}' has active transaction history, so it was safely archived. Remaining balance of ৳{refund_amount:,.2f} returned to your wallet.",
                "status": "archived",
                "refunded_amount": float(refund_amount)
            })
        else:
            fund.delete()
            return Response({
                "message": f"Fund '{fund.name}' successfully deleted. Remaining balance of ৳{refund_amount:,.2f} returned to your wallet.",
                "status": "deleted",
                "refunded_amount": float(refund_amount)
            })



# ==================== MERCHANTS & PAYMENTS ====================


class MerchantsListView(APIView):
    def get(self, request):
        merchants = Merchant.objects.filter(is_active=True).order_by('category', 'business_name')
        data = MerchantSerializer(merchants, many=True).data
        for merchant in data:
            merchant.pop('balance', None)
        return Response(data)


class PayMerchantView(FinancialAPIView):
    """
    CORE INNOVATION TEST ENDPOINT:
    - Normal Wallet Payment
    - Purpose Fund Payment (STRICT CATEGORY RESTRICTION)
    - FamilyPass Payment (7-POINT VALIDATION)
    """
    def post(self, request):
        user, err = require_auth(request)
        if err:
            return err
        try:
            merchant_id = request.data.get('merchant_id')
            raw_amount = request.data.get('amount')
            amount = Decimal(str(raw_amount)) if raw_amount not in [None, ''] else None
            items = request.data.get('items', None)
            payment_source = request.data.get('payment_source', PaymentSource.NORMAL_WALLET)
            purpose_fund_id = request.data.get('purpose_fund_id')
            family_pass_id = request.data.get('family_pass_id')
            ref = request.data.get('reference', '')

            merchant = get_object_or_404(Merchant, id=merchant_id)

            purpose_fund = None
            if purpose_fund_id:
                purpose_fund = PurposeFund.objects.filter(id=purpose_fund_id).first()

            family_pass = None
            if family_pass_id:
                family_pass = FamilyPass.objects.filter(id=family_pass_id).first()

            if payment_source == PaymentSource.FAMILY_PASS:
                if not family_pass_id:
                    return Response({
                        "success": False,
                        "error": "FamilyPass is required for FamilyPass payment.",
                        "code": "FAMILYPASS_REQUIRED"
                    }, status=status.HTTP_400_BAD_REQUEST)
                if not family_pass:
                    return Response({
                        "success": False,
                        "error": "Selected FamilyPass was not found or is invalid.",
                        "code": "FAMILYPASS_NOT_FOUND"
                    }, status=status.HTTP_400_BAD_REQUEST)

            # Execute transaction with deterministic business rule engine
            txn = TransactionService.execute_transaction(
                sender=user,
                transaction_type=TransactionType.MERCHANT_PAYMENT,
                amount=amount,
                merchant=merchant,
                payment_source=payment_source,
                purpose_fund=purpose_fund,
                family_pass=family_pass,
                reference=ref,
                items=items
            )

            return Response({
                "success": True,
                "message": f"Payment of ৳{txn.amount:,.2f} to {merchant.business_name} successful!",
                "transaction": TransactionSerializer(txn).data
            })

        except TransactionValidationError as e:
            # Deterministic rule rejection with explainable message
            request.rejected_transaction = getattr(e, 'audit_data', None)
            return Response({
                "success": False,
                "error": e.message,
                "code": e.code,
                "is_category_mismatch": e.code in ["CATEGORY_RESTRICTION_ERROR", "FAMILYPASS_CATEGORY_MISMATCH"]
            }, status=status.HTTP_400_BAD_REQUEST)


class MerchantDashboardView(APIView):
    def get(self, request):
        user, err = require_auth(request)
        if err:
            return err
        merchant = Merchant.objects.filter(user=user).first()
        if not merchant:
            return Response({'error': 'This account has no merchant dashboard.'}, status=403)
        if user.role != UserRole.MERCHANT:
            return Response({'error': 'Merchant access is required.'}, status=403)

        txns = Transaction.objects.filter(merchant=merchant).order_by('-timestamp')[:20]
        total_vol = sum([float(t.amount) for t in txns if t.status == 'COMPLETED'])

        return Response({
            "merchant": MerchantSerializer(merchant).data,
            "total_received_volume": round(total_vol, 2),
            "transactions_count": txns.count(),
            "transactions": TransactionSerializer(txns, many=True).data
        })


# ==================== FAMILYPASS ====================

class FamilyPassListView(APIView):
    permission_classes = [IsAuthenticated, CustomerPermission]
    def get(self, request):
        user, err = require_auth(request)
        if err:
            return err

        today = timezone.localdate() if timezone.is_aware(timezone.now()) else timezone.now().date()

        # 1. Passes issued by user (Owner view)
        issued_passes = FamilyPass.objects.filter(owner=user).order_by('-created_at')

        # 2. Passes received by this same customer
        received_passes = FamilyPass.objects.filter(member=user, status=FamilyPassStatus.ACTIVE, expiry_date__gte=today)

        # Build purpose options metadata for frontend UI dropdowns
        purpose_options = [
            {
                "value": p.value,
                "label": p.label,
                "requires_custom": p == FamilyPassPurpose.OTHER
            }
            for p in FamilyPassPurpose
        ]

        return Response({
            "issued_passes": FamilyPassSerializer(issued_passes, many=True).data,
            "received_passes": FamilyPassSerializer(received_passes, many=True).data,
            "user_role": user.effective_role,
            "effective_role": user.effective_role,
            "effective_role_display": user.get_effective_role_display(),
            "purpose_options": purpose_options,
        })

    def post(self, request):
        user, err = require_auth(request)
        if err:
            return err
        try:
            member_identifier = request.data.get('recipient_phone', request.data.get('member') or request.data.get('member_identifier'))
            raw_limit = request.data.get('limit_amount', '0')
            try:
                limit_amount = Decimal(str(raw_limit))
            except Exception:
                return Response({"error": "Invalid allowance limit format."}, status=status.HTTP_400_BAD_REQUEST)

            TransactionService.validate_amount(limit_amount)

            try:
                duration_days = int(request.data.get('duration_days') or request.data.get('validity_days') or 30)
            except Exception:
                duration_days = 30

            if duration_days <= 0:
                return Response({"error": "Duration must be at least 1 day."}, status=status.HTTP_400_BAD_REQUEST)

            action = request.data.get('allowed_action', FamilyPassAction.MERCHANT_PAYMENT)
            if action not in FamilyPassAction.values:
                action = FamilyPassAction.MERCHANT_PAYMENT

            # Purpose validation with dropdown restriction
            raw_purpose = request.data.get('purpose')
            raw_purpose_label = (request.data.get('purpose_label') or '').strip()
            custom_purpose = (request.data.get('custom_purpose') or '').strip()

            if raw_purpose:
                if raw_purpose not in FamilyPassPurpose.values:
                    return Response({
                        "error": f"Invalid purpose '{raw_purpose}'. Must be one of: {', '.join(FamilyPassPurpose.values)}."
                    }, status=status.HTTP_400_BAD_REQUEST)
                purpose = raw_purpose
            elif raw_purpose_label in FamilyPassPurpose.values:
                purpose = raw_purpose_label
            elif raw_purpose_label:
                purpose = FamilyPassPurpose.OTHER
                if not custom_purpose:
                    custom_purpose = raw_purpose_label
            else:
                purpose = FamilyPassPurpose.OTHER

            if purpose == FamilyPassPurpose.OTHER:
                purpose_label = f"Other: {custom_purpose}" if custom_purpose else "Other"
            else:
                purpose_label = purpose

            is_eligible, err_msg, member = RecipientService.check_recipient_eligibility(member_identifier, feature='FAMILY_PASS')

            if not is_eligible or not member:
                return Response(
                    {"error": err_msg, "code": RecipientService.rejection_code(member_identifier, member)},
                    status=status.HTTP_400_BAD_REQUEST
                )

            if member == user:
                return Response({"error": "Cannot grant FamilyPass to yourself."}, status=status.HTTP_400_BAD_REQUEST)

            start_date = timezone.localdate() if timezone.is_aware(timezone.now()) else timezone.now().date()
            expiry_date = start_date + datetime.timedelta(days=duration_days)

            # Determine allowed categories based on explicit payload or purpose mapping
            if 'allowed_categories' in request.data:
                explicit_cats = request.data['allowed_categories']
                if not isinstance(explicit_cats, list):
                    return Response({"error": "allowed_categories must be a list of category values."}, status=status.HTTP_400_BAD_REQUEST)
                invalid = [c for c in explicit_cats if c not in BusinessCategory.values]
                if invalid:
                    return Response({"error": f"Invalid categories: {', '.join(invalid)}."}, status=status.HTTP_400_BAD_REQUEST)
                allowed_categories = explicit_cats
            else:
                allowed_categories = PURPOSE_TO_CATEGORIES.get(purpose, [])
            # Create FamilyPass with allowed_categories
            fp = FamilyPass.objects.create(
                owner=user,
                member=member,
                limit_amount=limit_amount,
                used_amount=Decimal('0.00'),
                start_date=start_date,
                expiry_date=expiry_date,
                allowed_action=action,
                status=FamilyPassStatus.ACTIVE,
                purpose=purpose,
                custom_purpose=custom_purpose,
                purpose_label=purpose_label,
                allowed_categories=allowed_categories
            )

            # Send Notification to Member
            Notification.objects.create(
                user=member,
                title="🎁 New FamilyPass Granted",
                message=f"{user.full_name or user.phone or 'Customer'} granted you a FamilyPass for '{fp.purpose_label}' with ৳{limit_amount:,.2f} spending limit valid until {expiry_date}.",
                notification_type=NotificationType.FAMILY_PASS,
                metadata={
                    "family_pass_id": fp.id,
                    "owner": user.username,
                    "purpose": fp.purpose,
                    "limit_amount": float(limit_amount),
                    "expiry_date": str(expiry_date)
                }
            )

            return Response(FamilyPassSerializer(fp).data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class FamilyPassDetailView(APIView):
    """
    Handles retrieving and editing a granted FamilyPass permission.
    Strictly verifies ownership, prevents editing revoked/expired passes,
    rejects limits below already-used amounts, and notifies the recipient.
    """
    permission_classes = [IsAuthenticated, CustomerPermission]
    def get(self, request, pk):
        user, err = require_auth(request)
        if err:
            return err
        fp = get_object_or_404(FamilyPass, id=pk)
        if fp.owner != user and fp.member != user:
            return Response({"error": "Unauthorized access to FamilyPass details."}, status=status.HTTP_403_FORBIDDEN)
        return Response(FamilyPassSerializer(fp).data)

    def patch(self, request, pk):
        return self._update(request, pk)

    def put(self, request, pk):
        return self._update(request, pk)

    def post(self, request, pk):
        return self._update(request, pk)

    def _update(self, request, pk):
        with db_transaction.atomic():
            TransactionService.lock_wallets([request.user.id])
            return self._update_locked(request, pk)

    def _update_locked(self, request, pk):
        user, err = require_auth(request)
        if err:
            return err
        fp = get_object_or_404(FamilyPass.objects.select_for_update(), id=pk)

        # 1. Authorization: Only the granting owner may edit
        if fp.owner != user:
            return Response(
                {"error": "Unauthorized: You can only edit FamilyPass permissions that you granted."},
                status=status.HTTP_403_FORBIDDEN
            )

        # 2. Status validation: Cannot edit revoked or expired passes
        today = timezone.localdate() if timezone.is_aware(timezone.now()) else timezone.now().date()
        if fp.status != FamilyPassStatus.ACTIVE:
            return Response(
                {"error": f"Cannot edit FamilyPass with status '{fp.status}'."},
                status=status.HTTP_400_BAD_REQUEST
            )
        if fp.expiry_date < today:
            fp.status = FamilyPassStatus.EXPIRED
            fp.save(update_fields=['status', 'updated_at'])
            return Response(
                {"error": f"Cannot edit an expired FamilyPass (expired on {fp.expiry_date})."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 3. Allowance limit validation
        if 'limit_amount' in request.data:
            try:
                new_limit = Decimal(str(request.data['limit_amount']))
            except Exception:
                return Response({"error": "Invalid allowance limit format."}, status=status.HTTP_400_BAD_REQUEST)

            try:
                TransactionService.validate_amount(new_limit)
            except TransactionValidationError as exc:
                return Response({'error': exc.message, 'code': exc.code}, status=400)

            # Reject new allowance limit that is lower than amount already spent
            if new_limit < fp.used_amount:
                return Response(
                    {"error": f"New allowance limit (৳{new_limit:,.2f}) cannot be lower than the amount already spent (৳{fp.used_amount:,.2f})."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            fp.limit_amount = new_limit

        # 4. Expiry date validation
        if 'expiry_date' in request.data and request.data['expiry_date']:
            try:
                raw_exp = request.data['expiry_date']
                if isinstance(raw_exp, str):
                    new_expiry = datetime.date.fromisoformat(raw_exp.strip())
                else:
                    new_expiry = raw_exp
                if new_expiry < today:
                    return Response({"error": "Expiry date cannot be in the past."}, status=status.HTTP_400_BAD_REQUEST)
                fp.expiry_date = new_expiry
            except Exception:
                return Response({"error": "Invalid expiry date format. Use YYYY-MM-DD."}, status=status.HTTP_400_BAD_REQUEST)
        elif 'duration_days' in request.data:
            try:
                days = int(request.data['duration_days'])
                if days <= 0:
                    return Response({"error": "Duration must be at least 1 day."}, status=status.HTTP_400_BAD_REQUEST)
                fp.expiry_date = today + datetime.timedelta(days=days)
            except Exception:
                return Response({"error": "Invalid duration format."}, status=status.HTTP_400_BAD_REQUEST)

        # 5. Purpose dropdown validation
        purpose_changed = False
        if 'purpose' in request.data:
            purpose_val = request.data['purpose']
            if purpose_val not in FamilyPassPurpose.values:
                return Response(
                    {"error": f"Invalid purpose '{purpose_val}'. Supported options: {', '.join(FamilyPassPurpose.values)}."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            fp.purpose = purpose_val
            purpose_changed = True
            if fp.purpose == FamilyPassPurpose.OTHER:
                fp.custom_purpose = request.data.get('custom_purpose', '').strip()
                fp.purpose_label = f"Other: {fp.custom_purpose}" if fp.custom_purpose else "Other"
            else:
                fp.custom_purpose = ''
                fp.purpose_label = fp.purpose
        elif 'custom_purpose' in request.data and fp.purpose == FamilyPassPurpose.OTHER:
            fp.custom_purpose = request.data['custom_purpose'].strip()
            fp.purpose_label = f"Other: {fp.custom_purpose}" if fp.custom_purpose else "Other"
        elif 'purpose_label' in request.data and not fp.purpose:
            fp.purpose_label = request.data['purpose_label'].strip()

        # 6. Allowed Action
        if 'allowed_action' in request.data:
            action_val = request.data['allowed_action']
            if action_val in FamilyPassAction.values:
                fp.allowed_action = action_val

        # 7. Allowed Categories
        if 'allowed_categories' in request.data:
            # Explicit override takes priority
            cat_vals = request.data['allowed_categories']
            if not isinstance(cat_vals, list):
                return Response({"error": "allowed_categories must be a list of category values."}, status=status.HTTP_400_BAD_REQUEST)
            # Validate categories against BusinessCategory enum
            invalid = [c for c in cat_vals if c not in BusinessCategory.values]
            if invalid:
                return Response({"error": f"Invalid categories: {', '.join(invalid)}."}, status=status.HTTP_400_BAD_REQUEST)
            fp.allowed_categories = cat_vals
        elif purpose_changed:
            # Auto-sync allowed_categories from the new purpose
            fp.allowed_categories = PURPOSE_TO_CATEGORIES.get(fp.purpose, [])
        fp.save()

        # Notify Member about the edit
        Notification.objects.create(
            user=fp.member,
            title="✏️ FamilyPass Updated",
            message=f"{user.full_name or user.phone or 'Customer'} updated your FamilyPass ({fp.purpose_label}). New limit: ৳{fp.limit_amount:,.2f}, valid until {fp.expiry_date}.",
            notification_type=NotificationType.FAMILY_PASS,
            metadata={
                "family_pass_id": fp.id,
                "new_limit": float(fp.limit_amount),
                "remaining_limit": float(fp.remaining_limit),
                "expiry_date": str(fp.expiry_date),
                "purpose": fp.purpose
            }
        )

        return Response({
            "success": True,
            "message": "FamilyPass updated successfully.",
            "family_pass": FamilyPassSerializer(fp).data
        })


class FamilyPassRevokeView(APIView):
    permission_classes = [IsAuthenticated, CustomerPermission]
    @db_transaction.atomic
    def post(self, request, pk):
        user, err = require_auth(request)
        if err:
            return err
        TransactionService.lock_wallets([user.id])
        fp = FamilyPass.objects.select_for_update().filter(id=pk).first()
        if not fp:
            return Response({"error": "FamilyPass not found."}, status=status.HTTP_404_NOT_FOUND)
        if fp.owner != user:
            return Response({"error": "Only the pass owner can revoke this permission."}, status=status.HTTP_403_FORBIDDEN)
        fp.status = FamilyPassStatus.REVOKED
        fp.save(update_fields=['status', 'updated_at'])

        member = fp.member

        # Notify Member
        Notification.objects.create(
            user=member,
            title="🚫 FamilyPass Revoked",
            message=f"{user.full_name or user.phone or 'Customer'} revoked your FamilyPass ({fp.purpose_label}). This permission is no longer active.",
            notification_type=NotificationType.FAMILY_PASS,
            metadata={
                "family_pass_id": fp.id,
                "revoked_by": user.username,
            }
        )

        return Response({
            "success": True,
            "message": f"FamilyPass for {member.full_name or member.phone or 'Customer'} has been immediately revoked.",
            "family_pass": FamilyPassSerializer(fp).data,
            "member_id": member.id,
        })


class FamilyPassActivityView(APIView):
    permission_classes = [IsAuthenticated, CustomerPermission]
    def get(self, request, pk):
        user, err = require_auth(request)
        if err:
            return err
        fp = get_object_or_404(FamilyPass, id=pk)
        if fp.owner != user and fp.member != user:
            return Response({"error": "Unauthorized access to FamilyPass activity."}, status=status.HTTP_403_FORBIDDEN)

        activities = fp.activity_logs.select_related(
            'family_pass', 'member', 'transaction', 'transaction__merchant'
        ).prefetch_related('transaction__items').order_by('-timestamp')
        serialized_activities = FamilyPassTransactionSerializer(activities, many=True).data

        return Response({
            "family_pass": FamilyPassSerializer(fp).data,
            "activities": serialized_activities,
            "transactions": serialized_activities
        })


class AvailableFamilyPassRecipientsView(APIView):
    permission_classes = [IsAuthenticated, CustomerPermission]
    def get(self, request):
        customers = User.objects.filter(role=UserRole.CUSTOMER, is_active=True, is_superuser=False).exclude(pk=request.user.pk)
        return Response([{'id': customer.id, 'username': customer.username, 'phone': customer.phone, 'full_name': customer.full_name} for customer in customers])


# ==================== TRANSACTION HISTORY & NOTIFICATIONS ====================

class TransactionHistoryView(APIView):
    def get(self, request):
        user, err = require_auth(request)
        if err:
            return err
        qs = Transaction.objects.filter(
            Q(sender=user) | Q(receiver=user) | Q(family_pass__owner=user)
        ).distinct()

        # Filters
        txn_type = request.query_params.get('type')
        if txn_type:
            qs = qs.filter(transaction_type=txn_type)

        category = request.query_params.get('category')
        if category:
            qs = qs.filter(category=category)

        payment_source = request.query_params.get('source')
        if payment_source:
            qs = qs.filter(payment_source=payment_source)

        fund_id = request.query_params.get('fund_id')
        if fund_id:
            qs = qs.filter(purpose_fund_id=fund_id)

        status_param = request.query_params.get('status')
        if status_param:
            qs = qs.filter(status=status_param)

        return Response(TransactionSerializer(qs.order_by('-timestamp')[:50], many=True).data)


class NotificationsListView(APIView):
    def get(self, request):
        user, err = require_auth(request)
        if err:
            return err
        notifs = Notification.objects.filter(user=user)
        if user.effective_role != UserRole.ADMIN:
            notifs = notifs.exclude(notification_type=NotificationType.ANOMALY_ALERT)
        notifs = notifs.order_by('-created_at')[:25]
        return Response(NotificationSerializer(notifs, many=True).data)


class MarkNotificationReadView(APIView):
    def post(self, request, pk):
        user, err = require_auth(request)
        if err:
            return err
        allowed = Notification.objects.filter(user=user)
        if user.effective_role != UserRole.ADMIN:
            allowed = allowed.exclude(notification_type=NotificationType.ANOMALY_ALERT)
        notif = get_object_or_404(allowed, id=pk)
        notif.is_read = True
        notif.save(update_fields=['is_read'])
        return Response({"message": "Marked read"})


# ==================== AI & INTELLIGENCE ====================

class IntelligenceDashboardView(AdminAPIView):
    def get(self, request):
        user, err = require_auth(request)
        if err:
            return err
        behavioral = RecommendationEngine.get_behavioral_analysis(user)
        recommendations = RecommendationEngine.generate_recommendations(user)
        transfer_suggestion = RecommendationEngine.get_interfund_transfer_recommendation(user)

        # Anomaly detector evaluation
        detector = AnomalyDetector.get_instance()
        anomalies_qs = AnomalyResult.objects.filter(user=user, is_anomaly=True).order_by('-created_at')[:4]

        # Forecasts for all funds
        funds = PurposeFund.objects.filter(owner=user, status='ACTIVE')
        forecasts = [BudgetForecaster.forecast_fund(f) for f in funds]

        return Response({
            "forecasts": forecasts,
            "recommendations": recommendations,
            "interfund_transfer_suggestion": transfer_suggestion,
            "behavioral_analysis": behavioral,
            "recent_anomalies": AnomalyResultSerializer(anomalies_qs, many=True).data
        })


class AICoachQueryView(APIView):
    """
    POST /api/ai/coach/ and POST /api/ai/query/
    Conversational AI coach grounded strictly in the authenticated user's financial state.
    """
    def post(self, request):
        user, err = require_auth(request)
        if err:
            return err
        question = request.data.get('question') or request.data.get('message') or request.data.get('query', '')
        lang = request.data.get('lang', 'en')
        if not isinstance(question, str) or not question.strip():
            return Response({"error": "Question is required."}, status=status.HTTP_400_BAD_REQUEST)
        question = question.strip()
        if len(question) > 2000:
            return Response({"error": "Please keep your question within 2,000 characters."}, status=status.HTTP_400_BAD_REQUEST)
        if lang not in ('en', 'bn'):
            return Response({"error": "Unsupported language."}, status=status.HTTP_400_BAD_REQUEST)

        response = AICoach.answer_query(user, question, lang)
        return Response(response)


class AIRecommendationsView(APIView):
    """
    GET /api/ai/recommendations/
    Deterministic, structured recommendations generated from ML forecasts,
    Isolation Forest anomaly results, and current account rules for the authenticated user.
    """
    def get(self, request):
        user, err = require_auth(request)
        if err:
            return err
        recommendations = RecommendationEngine.generate_recommendations(user)
        return Response({
            "recommendations": recommendations,
            "count": len(recommendations)
        })


class AIForecastView(APIView):
    """
    GET /api/ai/forecast/
    Retrieves real out-of-sample budget forecasts for the authenticated user's active funds.
    """
    def get(self, request):
        user, err = require_auth(request)
        if err:
            return err
        funds = PurposeFund.objects.filter(owner=user, status='ACTIVE')
        forecasts = [BudgetForecaster.forecast_fund(f) for f in funds]
        return Response({
            "forecasts": forecasts,
            "count": len(forecasts)
        })


class AITransactionExplainView(APIView):
    """
    GET /api/ai/transaction/<str:txn_id>/explain/
    Natural language explanation of why a transaction was flagged or its context.
    Stops cross-user data leakage by enforcing user ownership.
    """
    def get(self, request, txn_id):
        user, err = require_auth(request)
        if err:
            return err

        txn = None
        if str(txn_id).isdigit():
            txn = Transaction.objects.filter(id=int(txn_id)).first()
        if not txn:
            txn = Transaction.objects.filter(transaction_id=str(txn_id)).first()

        if not txn:
            return Response({"error": "Transaction not found."}, status=status.HTTP_404_NOT_FOUND)

        # STRICT OWNERSHIP CHECK: User must be sender, receiver, or fund owner
        is_owner = (
            txn.sender == user or
            txn.receiver == user or
            (txn.purpose_fund and txn.purpose_fund.owner == user) or
            (txn.family_pass and txn.family_pass.owner == user)
        )
        if not is_owner:
            return Response(
                {"error": "Access denied. You can only explain your own transactions."},
                status=status.HTTP_403_FORBIDDEN
            )

        explanation = AICoach.explain_transaction(user, txn)
        return Response(explanation)


class ReportsView(APIView):
    def get(self, request):
        user, err = require_auth(request)
        if err:
            return err
        period = request.query_params.get('period', 'monthly')
        report = ReportService.generate_report(user, period)
        return Response(report)


# ==================== HACKATHON EVALUATION & EXPERIMENTS ====================

class EvaluationMetricsView(AdminAPIView):
    """
    Admin / Evaluator dashboard showing genuine ML metrics and dataset statistics.
    Sections 28, 29, 31 of Hackathon Spec.
    """
    def get(self, request):
        detector = AnomalyDetector.get_instance()
        anomaly_metrics = detector.evaluation_metrics
        forecast_metrics = BudgetForecaster.evaluate_offline_model()

        dataset_stats = {
            "synthetic_customers": User.objects.filter(role=UserRole.CUSTOMER).count(),
            "merchants": Merchant.objects.count(),
            "purpose_funds": PurposeFund.objects.count(),
            "family_passes": FamilyPass.objects.count(),
            "total_transactions": Transaction.objects.count(),
            "injected_anomalies_count": AnomalyResult.objects.filter(is_anomaly=True).count(),
            "currency": "Bangladeshi Taka (BDT ৳)"
        }

        return Response({
            "dataset_stats": dataset_stats,
            "anomaly_detection": anomaly_metrics,
            "forecasting": forecast_metrics,
            "responsible_ai_summary": {
                "privacy": "Repository demo data is used for training. Live ledger predictions are administrator-only.",
                "transparency": "Anomaly severity percentiles are not fraud probabilities or confidence ratings.",
                "human_control": "Zero automated transfers or budget changes. All financial actions require explicit user confirmation."
            }
        })


class MLTransactionReportView(AdminAPIView):
    """Paginated, read-only ledger predictions for administrator review."""
    def get(self, request):
        from rest_framework.pagination import PageNumberPagination
        from django.db.models import Count, Q
        detector = AnomalyDetector.get_instance()
        model = detector.evaluation_metrics
        version = model.get('model_version')
        active_versions = {v for v in [version, 'iso_forest_v2.0', 'iso_forest_v2.0_causal'] if v}
        ledger = Transaction.objects.select_related('sender', 'receiver', 'merchant', 'purpose_fund', 'anomaly_analysis').prefetch_related('items')
        current = Q(anomaly_analysis__model_version__in=active_versions)
        summary = ledger.aggregate(
            total=Count('pk'),
            normal=Count('pk', filter=current & Q(anomaly_analysis__is_anomaly=False)),
            anomaly=Count('pk', filter=current & Q(anomaly_analysis__is_anomaly=True))
        )
        summary['unscored'] = summary['total'] - summary['normal'] - summary['anomaly']
        prediction = request.query_params.get('prediction', '')
        if prediction not in ('', '0', '1', 'unscored'):
            return Response({'error': 'Prediction must be 0, 1, or unscored.'}, status=400)
        if prediction == 'unscored':
            ledger = ledger.exclude(current)
        elif prediction:
            ledger = ledger.filter(current, anomaly_analysis__is_anomaly=prediction == '1')
        transaction_type = request.query_params.get('type', '')
        if transaction_type:
            if transaction_type not in TransactionType.values:
                return Response({'error': 'Invalid transaction type.'}, status=400)
            ledger = ledger.filter(transaction_type=transaction_type)
        search = request.query_params.get('search', '').strip()
        if len(search) > 64:
            return Response({'error': 'Transaction search must be 64 characters or fewer.'}, status=400)
        if search:
            ledger = ledger.filter(transaction_id__icontains=search)
        pagination = PageNumberPagination()
        pagination.page_size = 20
        page = pagination.paginate_queryset(ledger.order_by('-timestamp', '-pk'), request)
        rows = []
        for txn in page:
            analysis = getattr(txn, 'anomaly_analysis', None)
            valid = analysis is not None and (analysis.model_version in active_versions)
            rows.append({
                'transaction': TransactionSerializer(txn).data,
                'prediction': analysis.prediction if valid else None,
                'label': ('Anomaly' if analysis.is_anomaly else 'Normal') if valid else 'Unscored',
                'analysis': AnomalyResultSerializer(analysis).data if valid else None
            })
        response = pagination.get_paginated_response(rows)
        response.data.update(summary=summary, model=model, transaction_types=list(TransactionType.values))
        return response


class ExperimentRecordsView(AdminAPIView):
    """
    Serves Baseline (Manual Spreadsheet) vs FundShare Prototype experiment comparisons.
    Section 30: User/Business Experiment
    """
    def get(self, request):
        records = ExperimentRecord.objects.all().order_by('task_index', 'condition')

        # Calculate comparative aggregates
        baseline_records = records.filter(condition=ExperimentCondition.BASELINE_SPREADSHEET)
        fundshare_records = records.filter(condition=ExperimentCondition.FUNDSHARE_PROTOTYPE)

        base_avg_time = sum([r.completion_time_seconds for r in baseline_records]) / max(1, baseline_records.count())
        fs_avg_time = sum([r.completion_time_seconds for r in fundshare_records]) / max(1, fundshare_records.count())

        base_accuracy = (sum([1 for r in baseline_records if r.is_correct]) / max(1, baseline_records.count())) * 100.0
        fs_accuracy = (sum([1 for r in fundshare_records if r.is_correct]) / max(1, fundshare_records.count())) * 100.0

        base_usability = sum([r.usability_score for r in baseline_records]) / max(1, baseline_records.count())
        fs_usability = sum([r.usability_score for r in fundshare_records]) / max(1, fundshare_records.count())

        return Response({
            "comparative_summary": {
                "avg_completion_time_seconds": {
                    "baseline": round(base_avg_time, 1),
                    "fundshare": round(fs_avg_time, 1),
                    "improvement_factor": round(base_avg_time / max(0.1, fs_avg_time), 1)
                },
                "task_accuracy_pct": {
                    "baseline": round(base_accuracy, 1),
                    "fundshare": round(fs_accuracy, 1)
                },
                "usability_score": {
                    "baseline": round(base_usability, 1),
                    "fundshare": round(fs_usability, 1)
                }
            },
            "records": ExperimentRecordSerializer(records, many=True).data
        })

    def post(self, request):
        """
        Allows live recording of new experiment trials during judge demonstrations.
        """
        serializer = ExperimentRecordSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class SeedDemoDataView(AdminAPIView):
    """
    1-Click reset/re-seed endpoint for demo resetting.
    """
    def post(self, request):
        if not settings.ENABLE_DEMO_RESET:
            return Response({'error': 'Demo reset is disabled in this environment.', 'code': 'RESET_DISABLED'}, status=403)
        wipe = request.data.get('wipe', False)
        result = SyntheticDataGenerator.populate_database(wipe_existing=wipe)
        AnomalyDetector.get_instance().train_and_evaluate()
        return Response({
            "message": "Demo data seeded successfully",
            "stats": result
        })


# ==================== CONTACT BOOK ====================

class ContactsListView(APIView):
    """
    Private Contact Book management for the authenticated user.
    Strictly isolated: users can ONLY access and modify their own contacts.
    """
    def get(self, request):
        user, err = require_auth(request)
        if err:
            return err

        q = request.query_params.get('q', '').strip()
        contacts = Contact.objects.filter(owner=user)
        if q:
            contacts = contacts.filter(
                Q(name__icontains=q) | Q(phone__icontains=q) | Q(username__icontains=q)
            )

        data = [ContactService.get_contact_account_info(c) for c in contacts]
        return Response(data)

    def post(self, request):
        user, err = require_auth(request)
        if err:
            return err

        name = request.data.get('name', '').strip()
        raw_phone = request.data.get('phone', '').strip()
        contact_username = request.data.get('username', '').strip()

        if not name:
            return Response({"error": "Contact name is required."}, status=status.HTTP_400_BAD_REQUEST)
        if not raw_phone:
            return Response({"error": "Phone number is required."}, status=status.HTTP_400_BAD_REQUEST)

        norm_phone = normalize_phone(raw_phone)
        if not norm_phone:
            return Response({"error": "Please provide a valid phone number."}, status=status.HTTP_400_BAD_REQUEST)

        # Check if already in user's contact book
        existing = Contact.objects.filter(owner=user, phone=norm_phone).first()
        if existing:
            return Response(
                {"error": f"A contact with phone {norm_phone} already exists in your Contact Book ('{existing.name}')."},
                status=status.HTTP_400_BAD_REQUEST
            )

        contact = Contact.objects.create(
            owner=user,
            name=name,
            phone=norm_phone,
            username=contact_username
        )

        return Response(ContactService.get_contact_account_info(contact), status=status.HTTP_201_CREATED)


class ContactDetailView(APIView):
    """
    Manage a single contact. Ownership is strictly enforced.
    """
    def get(self, request, pk):
        user, err = require_auth(request)
        if err:
            return err
        contact = get_object_or_404(Contact, id=pk, owner=user)
        return Response(ContactService.get_contact_account_info(contact))

    def patch(self, request, pk):
        user, err = require_auth(request)
        if err:
            return err
        contact = get_object_or_404(Contact, id=pk, owner=user)

        if 'name' in request.data:
            name = request.data.get('name', '').strip()
            if not name:
                return Response({"error": "Contact name cannot be empty."}, status=status.HTTP_400_BAD_REQUEST)
            contact.name = name

        if 'phone' in request.data:
            new_phone = normalize_phone(request.data.get('phone', '').strip())
            if not new_phone:
                return Response({"error": "Valid phone number required."}, status=status.HTTP_400_BAD_REQUEST)
            # Check for conflict with another contact of the same owner
            conflict = Contact.objects.filter(owner=user, phone=new_phone).exclude(id=contact.id).first()
            if conflict:
                return Response(
                    {"error": f"Another contact already uses phone {new_phone} ('{conflict.name}')."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            contact.phone = new_phone

        if 'username' in request.data:
            contact.username = request.data.get('username', '').strip()

        contact.save()
        return Response({
            "message": f"Contact '{contact.name}' updated successfully.",
            "contact": ContactService.get_contact_account_info(contact)
        })

    def put(self, request, pk):
        return self.patch(request, pk)

    def delete(self, request, pk):
        user, err = require_auth(request)
        if err:
            return err
        contact = get_object_or_404(Contact, id=pk, owner=user)
        contact_name = contact.name
        contact.delete()
        return Response({"message": f"Contact '{contact_name}' deleted successfully."})


class ContactSearchView(APIView):
    """
    Dedicated search endpoint: GET /api/contacts/search/?q=...
    """
    def get(self, request):
        user, err = require_auth(request)
        if err:
            return err

        q = request.query_params.get('q', '').strip()
        contacts = Contact.objects.filter(owner=user)
        if q:
            contacts = contacts.filter(
                Q(name__icontains=q) | Q(phone__icontains=q) | Q(username__icontains=q)
            )

        return Response([ContactService.get_contact_account_info(c) for c in contacts])


class RecipientResolveView(APIView):
    """
    Resolves recipient eligibility on the fly:
    Global phone resolution; saved contacts are not involved.
    """
    def get(self, request):
        recipient = request.query_params.get('phone') or request.query_params.get('recipient') or request.query_params.get('q')
        feature = request.query_params.get('feature', 'SEND_MONEY')
        return self.resolve(request, recipient, feature)

    def resolve(self, request, recipient, feature):
        is_eligible, err_msg, matched_user = RecipientService.check_recipient_eligibility(recipient, feature=feature)

        norm_phone = normalize_phone(recipient)
        return Response({
            "identifier": recipient,
            "normalized_phone": norm_phone,
            "feature": feature,
            "is_eligible": is_eligible,
            "error_message": err_msg,
            "code": None if is_eligible else RecipientService.rejection_code(recipient, matched_user),
            "is_registered": matched_user is not None,
            "account_status": "REGISTERED" if matched_user else "NOT_REGISTERED",
            "user": {
                "id": matched_user.id,
                "username": matched_user.username,
                "full_name": matched_user.full_name,
                "phone": matched_user.phone,
                "role": matched_user.effective_role,
                "effective_role": matched_user.effective_role,
                "effective_role_display": matched_user.get_effective_role_display(),
                "avatar_url": getattr(matched_user, 'avatar_url', ''),
            } if matched_user else None
        })

    def post(self, request):
        if not isinstance(request.data, dict):
            return Response({'error': 'Recipient details must be an object.'}, status=400)
        recipient = request.data.get('phone', request.data.get('recipient'))
        feature = request.data.get('feature', 'SEND_MONEY')
        return self.resolve(request, recipient, feature)
