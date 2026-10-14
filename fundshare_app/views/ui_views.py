from datetime import timedelta
from decimal import Decimal
from django.utils import timezone
from django.db.models import Sum, Count, Q
from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import TemplateView
from django.contrib.auth import authenticate, login, logout, get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.decorators import login_required, user_passes_test
from django.views import View
from django.contrib import messages
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import ensure_csrf_cookie
from django.utils.decorators import method_decorator
from django.http import JsonResponse, HttpResponseNotAllowed
from fundshare_app.forms import RegistrationForm
from fundshare_app.ml.demo_qa import DEMO_QA
from fundshare_app.services.security_service import check_login_rate, record_login_failure, clear_login_failures, check_registration_rate, SecurityError
from fundshare_app.models import (
    FraudIncident, Wallet, UserRole, BusinessCategory,
    PurposeFund, FundStatus, FamilyPass, FamilyPassStatus,
    Transaction, TransactionStatus, PaymentSource
)


@method_decorator(ensure_csrf_cookie, name='dispatch')
class IndexView(LoginRequiredMixin, TemplateView):
    """Main SPA dashboard — requires login."""
    template_name = "index.html"
    login_url = '/login/'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['demo_qa'] = DEMO_QA
        if self.request.user.is_authenticated:
            ctx['user'] = self.request.user
            ctx['user_role'] = self.request.user.effective_role
            ctx['user_role_display'] = self.request.user.get_effective_role_display()
            is_admin = bool(
                self.request.user.is_staff or
                self.request.user.is_superuser or
                getattr(self.request.user, 'role', None) == UserRole.ADMIN
            )
            ctx['is_admin_portal'] = is_admin

            if is_admin:
                now = timezone.now()
                since_24h = now - timedelta(hours=24)
                User = get_user_model()

                # 1. Platform Liquidity & Wallets Breakdown
                total_float = Wallet.objects.aggregate(total_float=Sum('balance'))['total_float'] or Decimal('0.00')
                total_wallets = Wallet.objects.count()
                active_wallets = Wallet.objects.filter(is_frozen=False).count()
                frozen_wallets = Wallet.objects.filter(is_frozen=True).count()
                total_customers = User.objects.filter(role=UserRole.CUSTOMER).count()

                txns_24h = Transaction.objects.filter(status=TransactionStatus.COMPLETED, timestamp__gte=since_24h)
                volume_24h = txns_24h.aggregate(vol=Sum('amount'))['vol'] or Decimal('0.00')
                count_24h = txns_24h.count()

                txns_all = Transaction.objects.filter(status=TransactionStatus.COMPLETED)
                volume_all = txns_all.aggregate(vol=Sum('amount'))['vol'] or Decimal('0.00')
                count_all = txns_all.count()

                ctx['platform_aggregates'] = {
                    'total_float': total_float,
                    'total_wallets': total_wallets,
                    'active_wallets': active_wallets,
                    'frozen_wallets': frozen_wallets,
                    'total_customers': total_customers,
                    'volume_24h': volume_24h,
                    'count_24h': count_24h,
                    'volume_all_time': volume_all,
                    'count_all_time': count_all,
                }
                # Flat keys for template specification compatibility
                ctx['platform_float'] = total_float
                ctx['total_wallets_count'] = total_wallets
                ctx['active_wallets_count'] = active_wallets
                ctx['frozen_wallets_count'] = frozen_wallets
                ctx['total_volume_24h'] = volume_24h
                ctx['total_txns_count'] = count_all
                ctx['total_volume_all_time'] = volume_all
                ctx['total_customers_count'] = total_customers

                # 2. FamilyPass Platform Analytics
                total_circles = FamilyPass.objects.count()
                active_circles = FamilyPass.objects.filter(status=FamilyPassStatus.ACTIVE).count()
                total_dependents = FamilyPass.objects.values('member').distinct().count()
                fp_txns = Transaction.objects.filter(status=TransactionStatus.COMPLETED, payment_source=PaymentSource.FAMILY_PASS)
                fp_total_volume = fp_txns.aggregate(vol=Sum('amount'))['vol'] or Decimal('0.00')

                cat_aggregates = list(fp_txns.values('category').annotate(vol=Sum('amount'), count=Count('id')).order_by('-vol'))
                fp_categories = []
                if fp_total_volume > Decimal('0.00'):
                    for c in cat_aggregates:
                        cat_name = c['category'] or 'Other'
                        c_vol = c['vol'] or Decimal('0.00')
                        pct = round(float(c_vol / fp_total_volume * 100), 1)
                        fp_categories.append({'name': cat_name, 'volume': c_vol, 'count': c['count'], 'percentage': pct})
                else:
                    fp_categories = [
                        {'name': 'Grocery', 'volume': Decimal('0.00'), 'count': 0, 'percentage': 42.0},
                        {'name': 'Education', 'volume': Decimal('0.00'), 'count': 0, 'percentage': 28.0},
                        {'name': 'Healthcare', 'volume': Decimal('0.00'), 'count': 0, 'percentage': 18.0},
                        {'name': 'Utilities', 'volume': Decimal('0.00'), 'count': 0, 'percentage': 12.0},
                    ]

                all_family_circles = FamilyPass.objects.select_related('owner', 'member').order_by('-created_at')

                ctx['familypass_platform'] = {
                    'total_circles': total_circles,
                    'active_circles': active_circles,
                    'total_dependents': total_dependents,
                    'total_volume': fp_total_volume,
                    'categories': fp_categories,
                    'circles': all_family_circles,
                }
                ctx['total_family_passes_count'] = total_circles
                ctx['active_family_passes_count'] = active_circles
                ctx['total_linked_dependents'] = total_dependents
                ctx['total_family_pass_volume'] = fp_total_volume
                ctx['family_pass_categories'] = fp_categories
                ctx['family_passes'] = all_family_circles

                # 3. Purpose Funds Platform Analytics
                total_purpose_funds = PurposeFund.objects.count()
                active_purpose_funds = PurposeFund.objects.filter(status=FundStatus.ACTIVE).count()
                total_locked_reserves = PurposeFund.objects.aggregate(total=Sum('current_balance'))['total'] or Decimal('0.00')
                total_allocated_reserves = PurposeFund.objects.aggregate(total=Sum('allocated_amount'))['total'] or Decimal('0.00')
                funds_by_category = list(PurposeFund.objects.values('category').annotate(count=Count('id'), total_locked=Sum('current_balance')).order_by('-total_locked'))
                all_purpose_funds = PurposeFund.objects.select_related('owner', 'recipient').order_by('-created_at')

                ctx['purpose_funds_platform'] = {
                    'total_funds': total_purpose_funds,
                    'active_funds': active_purpose_funds,
                    'total_locked': total_locked_reserves,
                    'total_allocated': total_allocated_reserves,
                    'categories': funds_by_category,
                    'funds': all_purpose_funds,
                }
                ctx['total_purpose_funds_count'] = total_purpose_funds
                ctx['active_purpose_funds_count'] = active_purpose_funds
                ctx['total_locked_reserves'] = total_locked_reserves
                ctx['purpose_funds'] = all_purpose_funds
                ctx['purpose_funds_categories'] = funds_by_category

                # 4. Master User & Wallet Registry
                all_wallets = Wallet.objects.select_related('owner').order_by('owner__username')
                ctx['master_wallets'] = all_wallets
                ctx['wallet_users'] = all_wallets

                # 5. Trust & Risk Incidents
                pending_qs = FraudIncident.objects.filter(
                    status='PENDING'
                ).select_related(
                    'transaction',
                    'transaction__sender',
                    'transaction__receiver',
                    'anomaly_result'
                ).order_by('-risk_score', '-created_at')
                ctx['pending_incidents'] = pending_qs
                ctx['pending_incident_count'] = pending_qs.count()

                mule_count = 0
                for inc in FraudIncident.objects.all():
                    reasons_text = " ".join(str(r) for r in (inc.reasons or [])).lower()
                    top_text = " ".join(str(c) for c in (inc.top_contributions or [])).lower()
                    if any(term in reasons_text or term in top_text for term in ['mule', 'networkx', 'fan-in', 'fan_in']):
                        mule_count += 1

                risk_kpis = {
                    'pending_count': ctx['pending_incident_count'],
                    'confirmed_fraud_count': FraudIncident.objects.filter(status='CONFIRMED_FRAUD').count(),
                    'frozen_wallets_count': frozen_wallets,
                    'mule_detections_count': mule_count,
                    'total_incidents': FraudIncident.objects.count(),
                }
                ctx['risk_kpis'] = risk_kpis
                ctx['kpis'] = risk_kpis

                ctx['recent_resolved'] = FraudIncident.objects.exclude(
                    status='PENDING'
                ).select_related(
                    'transaction',
                    'transaction__sender',
                    'transaction__receiver',
                    'reviewed_by'
                ).order_by('-resolved_at')[:10]
        return ctx


class LoginPageView(View):
    """Standalone login page with beautiful MFS UI."""
    def get(self, request):
        if request.user.is_authenticated:
            return redirect('/')
        return render(request, 'login.html', {'error': None})

    def post(self, request):
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')

        if not username or not password:
            return render(request, 'login.html', {'error': 'Please enter your phone number/username and password.'})

        # Try username first, then phone
        User = get_user_model()

        from fundshare_app.services.phone_utils import find_user_by_phone_or_username
        user_obj = find_user_by_phone_or_username(username)
        try:
            check_login_rate(request, user_obj.username if user_obj else username)
        except SecurityError as exc:
            return render(request, 'login.html', {'error': exc.message, 'username': username}, status=429)
        if user_obj:
            user = authenticate(request, username=user_obj.username, password=password)
        else:
            user = authenticate(request, username=username, password=password)

        if user is not None:
            clear_login_failures(request, user.username)
            login(request, user)
            next_url = request.GET.get('next', '/')
            if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
                next_url = '/'
            return redirect(next_url)
        else:
            record_login_failure(request, user_obj.username if user_obj else username)
            return render(request, 'login.html', {
                'error': 'Invalid phone number or password. Please try again.',
                'username': username
            })


class RegistrationPageView(View):
    def get(self, request):
        if request.user.is_authenticated:
            return redirect('/')
        return render(request, 'register.html', {'form': RegistrationForm()})

    def post(self, request):
        if request.user.is_authenticated:
            return redirect('/')
        form = RegistrationForm(request.POST)
        try:
            check_registration_rate(request)
            if form.is_valid():
                user = form.save()
                login(request, user, backend='django.contrib.auth.backends.ModelBackend')
                return redirect('/')
        except SecurityError as exc:
            return render(request, 'register.html', {'form': form, 'error': exc.message}, status=exc.status)
        return render(request, 'register.html', {'form': form}, status=400)


class LogoutPageView(View):
    def post(self, request):
        logout(request)
        return redirect('/login/')




def is_staff_or_admin(user):
    """Validator for Trust & Risk Analyst permissions."""
    return user.is_authenticated and user.is_active and (
        user.is_staff or user.is_superuser or getattr(user, 'role', None) == UserRole.ADMIN
    )


@login_required(login_url='/login/')
@user_passes_test(is_staff_or_admin, login_url='/login/')
def analyst_risk_dashboard(request):
    """
    Analyst Trust & Risk Intelligence Console:
    Displays pending FraudIncident triage queue, live KPIs, Explainable AI attribution,
    and handles automated wallet freeze on CONFIRMED_FRAUD and unfreeze on APPROVED.
    """
    if request.method == 'POST':
        action = request.POST.get('action')
        incident_id = request.POST.get('incident_id')
        notes = request.POST.get('notes', '').strip()
        incident = get_object_or_404(FraudIncident, pk=incident_id)

        msg = ""
        if action == 'confirm_fraud':
            incident.resolve('CONFIRMED_FRAUD', reviewer=request.user, notes=notes)
            msg = f"Incident #{incident.id} marked as CONFIRMED_FRAUD. Associated wallet(s) have been frozen."
        elif action in ('approve', 'mark_approved', 'mark_false_positive'):
            incident.resolve('APPROVED', reviewer=request.user, notes=notes)
            msg = f"Incident #{incident.id} approved as false positive. Associated wallet(s) restored."
        elif action == 'dismiss':
            incident.resolve('DISMISSED', reviewer=request.user, notes=notes)
            msg = f"Incident #{incident.id} dismissed."
        else:
            return JsonResponse({'success': False, 'error': f"Unknown action '{action}'."}, status=400)

        is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('accept', '')
        if is_ajax:
            return JsonResponse({
                'success': True,
                'message': msg,
                'incident_id': incident.id,
                'status': incident.status,
                'reviewer_notes': incident.reviewer_notes or '',
                'kpis': {
                    'pending_count': FraudIncident.objects.filter(status='PENDING').count(),
                    'confirmed_fraud_count': FraudIncident.objects.filter(status='CONFIRMED_FRAUD').count(),
                    'frozen_wallets_count': Wallet.objects.filter(is_frozen=True).count(),
                }
            })

        messages.success(request, msg)
        return redirect('risk_console')

    # GET request: compile KPIs and pending records
    pending_incidents = FraudIncident.objects.filter(
        status='PENDING'
    ).select_related(
        'transaction',
        'transaction__sender',
        'transaction__receiver',
        'anomaly_result'
    ).order_by('-risk_score', '-created_at')

    # Calculate mule ring detections across incidents
    mule_count = 0
    for inc in FraudIncident.objects.all():
        reasons_text = " ".join(str(r) for r in (inc.reasons or [])).lower()
        top_text = " ".join(str(c) for c in (inc.top_contributions or [])).lower()
        if any(term in reasons_text or term in top_text for term in ['mule', 'networkx', 'fan-in', 'fan_in']):
            mule_count += 1

    kpis = {
        'total_incidents': FraudIncident.objects.count(),
        'pending_count': pending_incidents.count(),
        'confirmed_fraud_count': FraudIncident.objects.filter(status='CONFIRMED_FRAUD').count(),
        'frozen_wallets_count': Wallet.objects.filter(is_frozen=True).count(),
        'mule_detections_count': mule_count,
    }

    recent_resolved = FraudIncident.objects.exclude(
        status='PENDING'
    ).select_related(
        'transaction',
        'transaction__sender',
        'transaction__receiver',
        'reviewed_by'
    ).order_by('-resolved_at')[:10]

    context = {
        'pending_incidents': pending_incidents,
        'kpis': kpis,
        'recent_resolved': recent_resolved,
        'user': request.user,
        'user_role': request.user.effective_role,
        'user_role_display': request.user.get_effective_role_display(),
    }
    return render(request, 'risk_console.html', context)


@login_required(login_url='/login/')
@user_passes_test(is_staff_or_admin, login_url='/login/')
def resolve_fraud_incident(request, incident_id):
    """Dedicated endpoint to resolve an incident."""
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    incident = get_object_or_404(FraudIncident, pk=incident_id)
    action = request.POST.get('action')
    notes = request.POST.get('notes', '').strip()

    if action == 'confirm_fraud':
        incident.resolve('CONFIRMED_FRAUD', reviewer=request.user, notes=notes)
        msg = f"Incident #{incident.id} marked as CONFIRMED_FRAUD. Associated wallet(s) have been frozen."
    elif action in ('approve', 'mark_approved', 'mark_false_positive'):
        incident.resolve('APPROVED', reviewer=request.user, notes=notes)
        msg = f"Incident #{incident.id} approved as false positive. Associated wallet(s) restored."
    elif action == 'dismiss':
        incident.resolve('DISMISSED', reviewer=request.user, notes=notes)
        msg = f"Incident #{incident.id} dismissed."
    else:
        return JsonResponse({'success': False, 'error': f"Unknown action '{action}'."}, status=400)

    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('accept', '')
    if is_ajax:
        return JsonResponse({
            'success': True,
            'message': msg,
            'incident_id': incident.id,
            'status': incident.status,
            'reviewer_notes': incident.reviewer_notes or '',
        })

    messages.success(request, msg)
    return redirect('risk_console')


@login_required(login_url='/login/')
@user_passes_test(is_staff_or_admin, login_url='/login/')
def admin_toggle_wallet_freeze(request, wallet_id=None, pk=None):
    """
    Administrative endpoint to toggle wallet freeze/unfreeze status for any customer.
    Route: /admin-actions/wallet/<int:wallet_id>/toggle-freeze/ or /admin/wallet/<int:wallet_id>/toggle-freeze/
    """
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    target_id = wallet_id if wallet_id is not None else pk
    wallet = get_object_or_404(Wallet, pk=target_id)
    if wallet.is_frozen:
        wallet.unfreeze()
        action_done = 'unfrozen'
        msg = f"Wallet for {wallet.owner.username} ({wallet.owner.phone or 'No phone'}) has been UNFROZEN."
    else:
        wallet.freeze()
        action_done = 'frozen'
        msg = f"Wallet for {wallet.owner.username} ({wallet.owner.phone or 'No phone'}) has been FROZEN."

    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('accept', '')
    if is_ajax:
        return JsonResponse({
            'success': True,
            'wallet_id': wallet.id,
            'is_frozen': wallet.is_frozen,
            'status_label': 'FROZEN' if wallet.is_frozen else 'ACTIVE',
            'action': action_done,
            'message': msg,
            'frozen_count': Wallet.objects.filter(is_frozen=True).count(),
            'active_count': Wallet.objects.filter(is_frozen=False).count(),
        })

    messages.success(request, msg)
    return redirect('/')


@login_required(login_url='/login/')
@user_passes_test(is_staff_or_admin, login_url='/login/')
def admin_toggle_family_pass(request, pass_id=None, pk=None):
    """
    Administrative endpoint to inspect, deactivate/revoke, or delete a FamilyPass circle.
    Route: /admin-actions/familypass/<int:pk>/action/ or /admin/family-pass/<int:pass_id>/toggle-status/
    """
    target_id = pass_id if pass_id is not None else pk
    pass_obj = get_object_or_404(FamilyPass, pk=target_id)
    action = request.POST.get('action') or request.GET.get('action', 'toggle')

    if action == 'inspect':
        return JsonResponse({
            'success': True,
            'id': pass_obj.id,
            'owner': pass_obj.owner.username,
            'owner_phone': pass_obj.owner.phone or '',
            'member': pass_obj.member.username,
            'member_phone': pass_obj.member.phone or '',
            'purpose_label': pass_obj.purpose_label,
            'purpose': pass_obj.purpose,
            'custom_purpose': pass_obj.custom_purpose,
            'allowed_categories': pass_obj.allowed_categories,
            'limit_amount': float(pass_obj.limit_amount),
            'used_amount': float(pass_obj.used_amount),
            'remaining_limit': float(pass_obj.remaining_limit),
            'status': pass_obj.status,
            'start_date': str(pass_obj.start_date),
            'expiry_date': str(pass_obj.expiry_date),
            'created_at': str(pass_obj.created_at),
        })

    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    if action == 'delete':
        owner_name = pass_obj.owner.username
        pass_obj.delete()
        msg = f"FamilyPass circle #{target_id} ({owner_name}) deleted permanently."
        status_val = 'DELETED'
    else:
        if pass_obj.status == FamilyPassStatus.ACTIVE:
            pass_obj.status = FamilyPassStatus.REVOKED
            msg = f"FamilyPass circle #{target_id} has been REVOKED/DEACTIVATED."
        else:
            pass_obj.status = FamilyPassStatus.ACTIVE
            msg = f"FamilyPass circle #{target_id} has been ACTIVATED."
        pass_obj.save()
        status_val = pass_obj.status

    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('accept', '')
    if is_ajax:
        return JsonResponse({
            'success': True,
            'pass_id': target_id,
            'status': status_val,
            'message': msg,
            'active_circles': FamilyPass.objects.filter(status=FamilyPassStatus.ACTIVE).count(),
            'total_circles': FamilyPass.objects.count(),
        })

    messages.success(request, msg)
    return redirect('/')


@login_required(login_url='/login/')
@user_passes_test(is_staff_or_admin, login_url='/login/')
def admin_toggle_purpose_fund(request, fund_id=None, pk=None):
    """
    Administrative endpoint to inspect, deactivate/archive, or cancel/delete a Purpose Fund.
    Route: /admin-actions/purposefund/<int:pk>/action/ or /admin/purpose-funds/<int:fund_id>/toggle-status/
    """
    target_id = fund_id if fund_id is not None else pk
    fund = get_object_or_404(PurposeFund, pk=target_id)
    action = request.POST.get('action') or request.GET.get('action', 'toggle')

    if action == 'inspect':
        return JsonResponse({
            'success': True,
            'id': fund.id,
            'name': fund.name,
            'owner': fund.owner.username,
            'owner_phone': fund.owner.phone or '',
            'category': fund.category,
            'current_balance': float(fund.current_balance),
            'allocated_amount': float(fund.allocated_amount),
            'monthly_budget': float(fund.monthly_budget),
            'status': fund.status,
            'created_at': str(fund.created_at),
        })

    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    if action in ('delete', 'cancel'):
        name = fund.name
        fund.delete()
        msg = f"Purpose Fund '{name}' deleted permanently."
        status_val = 'DELETED'
    else:
        if fund.status == FundStatus.ACTIVE:
            fund.status = FundStatus.ARCHIVED
            msg = f"Purpose Fund '{fund.name}' has been ARCHIVED/DEACTIVATED."
        else:
            fund.status = FundStatus.ACTIVE
            msg = f"Purpose Fund '{fund.name}' has been ACTIVATED."
        fund.save()
        status_val = fund.status

    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'application/json' in request.headers.get('accept', '')
    if is_ajax:
        return JsonResponse({
            'success': True,
            'fund_id': target_id,
            'status': status_val,
            'message': msg,
            'total_funds': PurposeFund.objects.count(),
        })

    messages.success(request, msg)
    return redirect('/')

