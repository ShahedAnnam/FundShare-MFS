import datetime
from decimal import Decimal
from django.utils import timezone
from django.contrib.auth import authenticate, login, logout, get_user_model
from django.shortcuts import get_object_or_404
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated

from fundshare_app.models import (
    UserRole, Wallet, Merchant, PurposeFund, FundTransfer,
    FamilyPass, FamilyPassStatus, FamilyPassAction,
    Transaction, TransactionType, PaymentSource,
    Notification, NotificationType, AnomalyResult, BudgetForecast, AIInsight,
    ExperimentRecord, ExperimentCondition
)
from fundshare_app.serializers.api_serializers import (
    UserSerializer, WalletSerializer, MerchantSerializer,
    PurposeFundSerializer, FundTransferSerializer,
    FamilyPassSerializer, TransactionSerializer,
    FamilyPassTransactionSerializer, NotificationSerializer,
    AnomalyResultSerializer, BudgetForecastSerializer,
    ExperimentRecordSerializer
)
from fundshare_app.services.transaction_service import TransactionService, TransactionValidationError
from fundshare_app.services.report_service import ReportService
from fundshare_app.ml.anomaly_detector import AnomalyDetector
from fundshare_app.ml.budget_forecaster import BudgetForecaster
from fundshare_app.ml.recommendation_engine import RecommendationEngine
from fundshare_app.ml.ai_coach import AICoach
from fundshare_app.ml.data_generator import SyntheticDataGenerator

User = get_user_model()


def get_authenticated_or_demo_user(request):
    """
    Returns the authenticated user. If not authenticated via session, returns None
    and views should return HTTP 401.
    For backwards compatibility during hackathon, falls back to 'shahed' ONLY if
    request has a special demo header (X-Demo-User).
    """
    if request.user and request.user.is_authenticated:
        return request.user
    # Check demo override header (for evaluation/judge use only)
    demo_user = request.headers.get('X-Demo-User')
    if demo_user:
        user = User.objects.filter(username=demo_user).first()
        if user:
            return user
    return None


def require_auth(request):
    """Returns (user, error_response) tuple. If user is None, error_response is a 401 Response."""
    user = get_authenticated_or_demo_user(request)
    if user is None:
        return None, Response(
            {"error": "Authentication required. Please log in.", "redirect": "/login/"},
            status=status.HTTP_401_UNAUTHORIZED
        )
    return user, None


# ==================== AUTHENTICATION & DEMO SWITCHER ====================

class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        username = request.data.get('username', '').strip()
        password = request.data.get('password', '').strip()
        # Support phone number login
        user_obj = User.objects.filter(phone=username).first() or \
                   User.objects.filter(username=username).first()
        if user_obj:
            user = authenticate(request, username=user_obj.username, password=password)
        else:
            user = authenticate(request, username=username, password=password)
        if user:
            login(request, user)
            wallet, _ = Wallet.objects.get_or_create(owner=user)
            return Response({
                "message": "Login successful",
                "user": UserSerializer(user).data,
                "wallet_balance": float(wallet.balance),
                "role": user.role
            })
        return Response({"error": "Invalid phone number or password"}, status=status.HTTP_401_UNAUTHORIZED)


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
        unread_notifications = Notification.objects.filter(user=user, is_read=False).count()

        # Check if user has active received FamilyPasses
        received_passes = FamilyPass.objects.filter(member=user, status=FamilyPassStatus.ACTIVE)

        return Response({
            "user": UserSerializer(user).data,
            "wallet_balance": float(wallet.balance),
            "unread_notifications": unread_notifications,
            "received_family_passes_count": received_passes.count()
        })


class SwitchRoleView(APIView):
    """
    Instant 1-Click Role Switcher for hackathon judges:
    - shahed (Customer Owner)
    - rahim (FamilyPass Member 1)
    - karim (FamilyPass Member 2)
    - agora (Merchant)
    - admin (Judge / Evaluator)
    """
    permission_classes = [AllowAny]

    def post(self, request):
        target_username = request.data.get('username', 'shahed')
        user = User.objects.filter(username=target_username).first()
        if not user:
            SyntheticDataGenerator.populate_database()
            user = User.objects.filter(username=target_username).first()

        if user:
            login(request, user)
            wallet, _ = Wallet.objects.get_or_create(owner=user)
            return Response({
                "message": f"Switched to {user.full_name or user.username} ({user.get_role_display()})",
                "user": UserSerializer(user).data,
                "wallet_balance": float(wallet.balance)
            })
        return Response({"error": "User not found"}, status=status.HTTP_404_NOT_FOUND)


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

        # Recent transactions
        recent_txns = Transaction.objects.filter(sender=user).order_by('-timestamp')[:6]

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


class CashInView(APIView):
    def post(self, request):
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


class SendMoneyView(APIView):
    def post(self, request):
        user, err = require_auth(request)
        if err:
            return err
        try:
            amount = Decimal(str(request.data.get('amount', '0')))
            receiver_identifier = request.data.get('receiver')
            receiver = User.objects.filter(username=receiver_identifier).first() or \
                       User.objects.filter(phone=receiver_identifier).first()

            if not receiver:
                return Response({"error": "Recipient user not found. Check phone or username."}, status=status.HTTP_404_NOT_FOUND)

            txn = TransactionService.execute_transaction(
                sender=user,
                receiver=receiver,
                transaction_type=TransactionType.SEND_MONEY,
                amount=amount,
                reference=request.data.get('reference', '')
            )
            return Response({
                "message": f"Successfully sent ৳{amount:,.2f} to {receiver.full_name or receiver.username}",
                "transaction": TransactionSerializer(txn).data,
                "remaining_balance": float(user.wallet.balance)
            })
        except TransactionValidationError as e:
            return Response({"error": e.message, "code": e.code}, status=status.HTTP_400_BAD_REQUEST)


class UtilityServicesView(APIView):
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
            txn_type = type_map.get(action_type, TransactionType.BILL_PAYMENT)
            txn = TransactionService.execute_transaction(
                sender=user,
                transaction_type=txn_type,
                amount=amount,
                reference=request.data.get('reference', '')
            )
            return Response({
                "message": f"Successfully processed {action_type.title()} of ৳{amount:,.2f}",
                "transaction": TransactionSerializer(txn).data,
                "remaining_balance": float(user.wallet.balance)
            })
        except TransactionValidationError as e:
            return Response({"error": e.message, "code": e.code}, status=status.HTTP_400_BAD_REQUEST)


# ==================== PURPOSE FUNDS ====================

class PurposeFundsListView(APIView):
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

            # Check wallet balance if allocating
            wallet, _ = Wallet.objects.get_or_create(owner=user)
            if initial_allocation > Decimal('0.00'):
                if wallet.balance < initial_allocation:
                    return Response({"error": f"Insufficient wallet balance. You have ৳{wallet.balance:,.2f} available."}, status=status.HTTP_400_BAD_REQUEST)
                wallet.balance -= initial_allocation
                wallet.save(update_fields=['balance', 'updated_at'])

            fund = PurposeFund.objects.create(
                owner=user,
                name=name,
                category=category,
                allocated_amount=initial_allocation,
                current_balance=initial_allocation,
                monthly_budget=budget,
                icon=icon,
                color=color
            )

            if initial_allocation > Decimal('0.00'):
                Transaction.objects.create(
                    sender=user,
                    amount=initial_allocation,
                    transaction_type=TransactionType.FUND_ALLOCATION,
                    payment_source=PaymentSource.NORMAL_WALLET,
                    purpose_fund=fund,
                    category=category,
                    status='COMPLETED',
                    reference=f"Initial allocation for {fund.name} Fund"
                )

            return Response(PurposeFundSerializer(fund).data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class PurposeFundAllocateView(APIView):
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


class PurposeFundTransferView(APIView):
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


# ==================== MERCHANTS & PAYMENTS ====================

class MerchantsListView(APIView):
    def get(self, request):
        merchants = Merchant.objects.filter(is_active=True).order_by('category', 'business_name')
        return Response(MerchantSerializer(merchants, many=True).data)


class PayMerchantView(APIView):
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
            amount = Decimal(str(request.data.get('amount', '0')))
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

            # Execute transaction with deterministic business rule engine
            txn = TransactionService.execute_transaction(
                sender=user,
                transaction_type=TransactionType.MERCHANT_PAYMENT,
                amount=amount,
                merchant=merchant,
                payment_source=payment_source,
                purpose_fund=purpose_fund,
                family_pass=family_pass,
                reference=ref
            )

            return Response({
                "success": True,
                "message": f"Payment of ৳{amount:,.2f} to {merchant.business_name} successful!",
                "transaction": TransactionSerializer(txn).data
            })

        except TransactionValidationError as e:
            # Deterministic rule rejection with explainable message
            return Response({
                "success": False,
                "error": e.message,
                "code": e.code,
                "is_category_mismatch": e.code == "CATEGORY_RESTRICTION_ERROR",
                "is_family_pass_error": "FAMILYPASS" in e.code or "OWNER" in e.code
            }, status=status.HTTP_400_BAD_REQUEST)


class MerchantDashboardView(APIView):
    def get(self, request):
        user, err = require_auth(request)
        if err:
            return err
        merchant = Merchant.objects.filter(user=user).first()
        if not merchant:
            # If logged in as another user, find Agora as demo merchant
            merchant = Merchant.objects.filter(business_name__icontains="Agora").first()

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
    def get(self, request):
        user, err = require_auth(request)
        if err:
            return err

        # 1. Passes issued by user (Owner view)
        issued_passes = FamilyPass.objects.filter(owner=user).order_by('-created_at')

        # 2. Passes received by user (Member view)
        received_passes = FamilyPass.objects.filter(member=user, status=FamilyPassStatus.ACTIVE)

        return Response({
            "issued_passes": FamilyPassSerializer(issued_passes, many=True).data,
            "received_passes": FamilyPassSerializer(received_passes, many=True).data,
            "user_role": user.role
        })

    def post(self, request):
        user, err = require_auth(request)
        if err:
            return err
        try:
            member_identifier = request.data.get('member')
            limit_amount = Decimal(str(request.data.get('limit_amount', '0')))
            duration_days = int(request.data.get('duration_days', 30))
            action = request.data.get('allowed_action', FamilyPassAction.MERCHANT_PAYMENT)
            purpose_label = request.data.get('purpose_label', 'Family Spending')

            member = User.objects.filter(username=member_identifier).first() or \
                     User.objects.filter(phone=member_identifier).first()

            if not member:
                return Response({"error": "Member not found. Check username or phone."}, status=status.HTTP_404_NOT_FOUND)

            if member == user:
                return Response({"error": "Cannot grant FamilyPass to yourself."}, status=status.HTTP_400_BAD_REQUEST)

            start_date = timezone.localdate() if timezone.is_aware(timezone.now()) else timezone.now().date()
            expiry_date = start_date + datetime.timedelta(days=duration_days)

            fp = FamilyPass.objects.create(
                owner=user,
                member=member,
                limit_amount=limit_amount,
                used_amount=Decimal('0.00'),
                start_date=start_date,
                expiry_date=expiry_date,
                allowed_action=action,
                status=FamilyPassStatus.ACTIVE,
                purpose_label=purpose_label
            )

            # Send Notification to Member
            Notification.objects.create(
                user=member,
                title="🎁 New FamilyPass Granted",
                message=f"{user.full_name or user.username} granted you a FamilyPass with ৳{limit_amount:,.2f} spending limit valid until {expiry_date}.",
                notification_type=NotificationType.FAMILY_PASS
            )

            return Response(FamilyPassSerializer(fp).data, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class FamilyPassRevokeView(APIView):
    def post(self, request, pk):
        user, err = require_auth(request)
        if err:
            return err
        fp = get_object_or_404(FamilyPass, id=pk, owner=user)
        fp.status = FamilyPassStatus.REVOKED
        fp.save(update_fields=['status', 'updated_at'])

        # Notify Member
        Notification.objects.create(
            user=fp.member,
            title="FamilyPass Revoked",
            message=f"{user.full_name or user.username} revoked your FamilyPass ({fp.purpose_label}).",
            notification_type=NotificationType.FAMILY_PASS
        )

        return Response({
            "message": f"FamilyPass for {fp.member.full_name or fp.member.username} has been immediately revoked.",
            "family_pass": FamilyPassSerializer(fp).data
        })


class FamilyPassActivityView(APIView):
    def get(self, request, pk):
        user, err = require_auth(request)
        if err:
            return err
        fp = get_object_or_404(FamilyPass, id=pk)
        if fp.owner != user and fp.member != user:
            return Response({"error": "Unauthorized access to FamilyPass activity."}, status=status.HTTP_403_FORBIDDEN)

        activities = fp.activity_logs.all().order_by('-timestamp')
        return Response({
            "family_pass": FamilyPassSerializer(fp).data,
            "activities": FamilyPassTransactionSerializer(activities, many=True).data
        })


class AvailableMembersView(APIView):
    def get(self, request):
        members = User.objects.filter(role__in=[UserRole.MEMBER, UserRole.CUSTOMER]).exclude(username='admin')
        return Response(UserSerializer(members, many=True).data)


# ==================== TRANSACTION HISTORY & NOTIFICATIONS ====================

class TransactionHistoryView(APIView):
    def get(self, request):
        user, err = require_auth(request)
        if err:
            return err
        qs = Transaction.objects.filter(sender=user)

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
        notifs = Notification.objects.filter(user=user).order_by('-created_at')[:25]
        return Response(NotificationSerializer(notifs, many=True).data)


class MarkNotificationReadView(APIView):
    def post(self, request, pk):
        user, err = require_auth(request)
        if err:
            return err
        notif = get_object_or_404(Notification, id=pk, user=user)
        notif.is_read = True
        notif.save(update_fields=['is_read'])
        return Response({"message": "Marked read"})


# ==================== AI & INTELLIGENCE ====================

class IntelligenceDashboardView(APIView):
    def get(self, request):
        user, err = require_auth(request)
        if err:
            return err
        behavioral = RecommendationEngine.get_behavioral_analysis(user)
        recommendations = RecommendationEngine.get_next_month_recommendations(user)
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
    def post(self, request):
        user, err = require_auth(request)
        if err:
            return err
        question = request.data.get('question', '')
        lang = request.data.get('lang', 'en')
        if not question:
            return Response({"error": "Question is required."}, status=status.HTTP_400_BAD_REQUEST)

        response = AICoach.answer_query(user, question, lang)
        return Response(response)


class AISetKeyView(APIView):
    """
    Allows the judge/user to set Gemini API key from the UI settings page.
    Writes to the .env file for persistence.
    """
    def post(self, request):
        import os
        from pathlib import Path
        gemini_key = request.data.get('gemini_api_key', '').strip()
        if not gemini_key:
            return Response({"error": "API key is required"}, status=status.HTTP_400_BAD_REQUEST)

        # Update os.environ immediately for current process
        os.environ['GEMINI_API_KEY'] = gemini_key

        # Also update Django settings in memory
        from django.conf import settings
        settings.GEMINI_API_KEY = gemini_key

        # Write to .env file for persistence
        env_file = Path(settings.BASE_DIR) / '.env'
        try:
            if env_file.exists():
                content = env_file.read_text(encoding='utf-8')
                if 'GEMINI_API_KEY=' in content:
                    lines = content.splitlines()
                    new_lines = []
                    for line in lines:
                        if line.startswith('GEMINI_API_KEY='):
                            new_lines.append(f'GEMINI_API_KEY={gemini_key}')
                        else:
                            new_lines.append(line)
                    env_file.write_text('\n'.join(new_lines), encoding='utf-8')
                else:
                    with env_file.open('a', encoding='utf-8') as f:
                        f.write(f'\nGEMINI_API_KEY={gemini_key}\n')
            else:
                env_file.write_text(f'GEMINI_API_KEY={gemini_key}\n', encoding='utf-8')
        except Exception as e:
            pass  # Key already set in memory, file write is best-effort

        return Response({
            "message": "Gemini API key saved successfully. AI Coach is now powered by Gemini 2.0 Flash.",
            "ai_enabled": True
        })


class ReportsView(APIView):
    def get(self, request):
        user, err = require_auth(request)
        if err:
            return err
        period = request.query_params.get('period', 'monthly')
        report = ReportService.generate_report(user, period)
        return Response(report)


# ==================== HACKATHON EVALUATION & EXPERIMENTS ====================

class EvaluationMetricsView(APIView):
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
                "privacy": "100% Synthetic Data generated for local Bangladesh demographics.",
                "transparency": "Every prediction outputs explicit evidence and confidence rating.",
                "human_control": "Zero automated transfers or budget changes. All financial actions require explicit user confirmation."
            }
        })


class ExperimentRecordsView(APIView):
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


class SeedDemoDataView(APIView):
    """
    1-Click reset/re-seed endpoint for demo resetting.
    """
    def post(self, request):
        wipe = request.data.get('wipe', False)
        result = SyntheticDataGenerator.populate_database(wipe_existing=wipe)
        AnomalyDetector.get_instance().train_and_evaluate()
        return Response({
            "message": "Demo data seeded successfully",
            "stats": result
        })
