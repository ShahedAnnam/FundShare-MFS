"""
FUNDShare ML Pipeline - Grounded User-Specific ML Context Builder
Constructs a comprehensive, authoritative financial & ML context for ONE authenticated user.
Strictly isolated: Queries are rigorously scoped to user-owned records.
Zero cross-user data leakage.
"""
from typing import Dict, Any, List
from decimal import Decimal
from django.utils import timezone
from django.contrib.auth import get_user_model

from fundshare_app.models import (
    PurposeFund, Transaction, FamilyPass, AnomalyResult, Wallet
)
from fundshare_app.services.report_service import ReportService
from fundshare_app.ml.budget_forecaster import BudgetForecaster

User = get_user_model()


class MLContextBuilder:
    """
    Builds structured, grounded financial and ML context for a single user.
    """

    @classmethod
    def build_user_context(cls, user: User) -> Dict[str, Any]:
        """
        Gathers only authoritative records belonging to the authenticated user.
        """
        # 1. User & Wallet Info
        wallet = getattr(user, 'wallet', None)
        wallet_bal = float(wallet.balance) if wallet else 0.0

        # 2. Monthly Financial Summary (Scoped to this user)
        report = ReportService.generate_report(user, 'monthly')
        overview = report.get('overview', {})
        by_category = report.get('by_category', {})

        # 3. Purpose Funds & ML Forecasts
        funds = PurposeFund.objects.filter(owner=user, status='ACTIVE')
        funds_data = []
        forecasts_data = []

        for f in funds:
            alloc = float(f.allocated_amount)
            curr = float(f.current_balance)
            spent = max(0.0, alloc - curr)
            fc = BudgetForecaster.forecast_fund(f)

            predicted_amount = float(fc.get('predicted_amount', alloc))
            potential_overrun = float(fc.get('potential_overrun', 0.0))
            risk_level = fc.get('risk_level', 'SAFE')

            fund_summary = {
                "id": f.id,
                "name": f.name,
                "category": f.category,
                "allocated_budget": alloc,
                "current_spent": spent,
                "current_balance": curr,
                "predicted_month_end_spend": predicted_amount,
                "potential_overrun": potential_overrun,
                "risk_level": risk_level,
                "pct_used": round((spent / alloc) * 100.0, 1) if alloc > 0 else 0.0,
                "confidence": fc.get('confidence', 0.80)
            }
            funds_data.append(fund_summary)
            forecasts_data.append({
                "fund_id": f.id,
                "fund_name": f.name,
                "category": f.category,
                "allocated_budget": alloc,
                "current_spent": spent,
                "predicted_amount": predicted_amount,
                "potential_overrun": potential_overrun,
                "risk_level": risk_level,
                "explanation": fc.get('explanation', ''),
                "confidence": fc.get('confidence', 0.80)
            })

        # 4. Recent Completed Spending Transactions (last 10)
        recent_txns = []
        for t in Transaction.objects.filter(sender=user, status='COMPLETED').order_by('-timestamp')[:10]:
            target_name = (
                t.merchant.business_name if t.merchant
                else (t.receiver.full_name or t.receiver.username if t.receiver else "N/A")
            )
            recent_txns.append({
                "transaction_id": t.transaction_id,
                "amount": float(t.amount),
                "transaction_type": t.transaction_type,
                "payment_source": t.payment_source,
                "category": t.category or "General",
                "target": target_name,
                "timestamp": t.timestamp.strftime("%Y-%m-%d %H:%M:%S")
            })

        # 5. Genuine ML Anomaly Flags (strictly this user's transactions)
        anomalies_data = []
        user_anom_results = AnomalyResult.objects.filter(
            user=user,
            is_anomaly=True
        ).select_related('transaction', 'transaction__merchant').order_by('-created_at')[:6]

        for a in user_anom_results:
            txn = a.transaction
            m_name = txn.merchant.business_name if txn and txn.merchant else "Merchant"
            anomalies_data.append({
                "transaction_id": txn.transaction_id if txn else "TXN",
                "amount": float(txn.amount) if txn else 0.0,
                "category": txn.category if txn else "N/A",
                "merchant": m_name,
                "timestamp": txn.timestamp.strftime("%Y-%m-%d %H:%M:%S") if txn else "",
                "anomaly_score": round(float(a.anomaly_score), 4),
                "model_version": a.model_version,
                "reason": a.reason,
                "features_summary": a.features_summary
            })

        # 6. FamilyPass Delegations (Issued by user & Received by user)
        issued_fps = FamilyPass.objects.filter(owner=user, status='ACTIVE').select_related('member')
        issued_data = []
        for fp in issued_fps:
            limit = float(fp.limit_amount)
            used = float(fp.used_amount)
            issued_data.append({
                "family_pass_id": fp.id,
                "member_name": fp.member.full_name or fp.member.username,
                "member_phone": fp.member.phone,
                "purpose": fp.purpose_label or fp.purpose,
                "allowed_categories": fp.get_allowed_categories(),
                "limit": limit,
                "limit_amount": limit,
                "used": used,
                "used_amount": used,
                "remaining_limit": max(0.0, limit - used),
                "expiry_date": fp.expiry_date.strftime("%Y-%m-%d")
            })

        received_fps = FamilyPass.objects.filter(member=user, status='ACTIVE').select_related('owner')
        received_data = []
        for fp in received_fps:
            limit = float(fp.limit_amount)
            used = float(fp.used_amount)
            received_data.append({
                "family_pass_id": fp.id,
                "owner_name": fp.owner.full_name or fp.owner.username,
                "purpose": fp.purpose_label or fp.purpose,
                "allowed_categories": fp.get_allowed_categories(),
                "limit": limit,
                "limit_amount": limit,
                "used": used,
                "used_amount": used,
                "remaining_limit": max(0.0, limit - used),
                "expiry_date": fp.expiry_date.strftime("%Y-%m-%d")
            })

        # 7. Financial Health Signals
        total_income = float(overview.get("total_income", 0.0))
        total_spent = float(overview.get("total_spent", 0.0))
        net_savings = float(overview.get("net_savings", 0.0))
        savings_rate = float(overview.get("savings_rate_pct", 0.0))
        total_txns_count = overview.get("total_transactions", 0)

        signals = []
        if savings_rate >= 20.0:
            signals.append("HEALTHY_SAVINGS_RATE")
        elif savings_rate < 5.0 and total_income > 0:
            signals.append("LOW_SAVINGS_BUFFER")

        if any(f["risk_level"] == "HIGH_RISK" for f in funds_data):
            signals.append("BUDGET_OVERRUN_RISK")

        if len(anomalies_data) > 0:
            signals.append("RECENT_UNUSUAL_ACTIVITY")

        monthly_report_dict = {
            "total_income": total_income,
            "total_spent": total_spent,
            "net_savings": net_savings,
            "savings_rate_pct": savings_rate,
            "total_transactions": total_txns_count,
            "by_category": by_category
        }

        return {
            # Phase 2 Schema
            "user": {
                "id": user.id,
                "username": user.username,
                "name": user.full_name or user.username,
                "role": user.role
            },
            "wallet": {
                "balance": wallet_bal,
                "currency": "BDT"
            },
            "purpose_funds": funds_data,
            "recent_spending": recent_txns,
            "spending_trends": by_category,
            "anomalies": anomalies_data,
            "forecasts": forecasts_data,
            "family_passes": issued_data + received_data,
            "financial_signals": signals,

            # Backward-compatible & flat keys
            "username": user.username,
            "wallet_balance": wallet_bal,
            "monthly_report": monthly_report_dict,
            "monthly_overview": monthly_report_dict,
            "family_passes_issued": issued_data,
            "family_passes_received": received_data
        }
