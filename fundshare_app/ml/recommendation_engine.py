"""
FUNDShare ML Pipeline - Grounded Deterministic Recommendation Engine
Generates structured, traceable recommendation objects from actual financial state,
machine learning predictions (forecasting + anomaly detection), and business rules.
Strictly non-LLM: The recommendation engine calculates everything deterministically.
"""
from typing import Dict, Any, List
from decimal import Decimal
from django.utils import timezone

from fundshare_app.models import (
    PurposeFund, Transaction, FamilyPass, AnomalyResult, AIInsight, InsightType
)
from fundshare_app.ml.budget_forecaster import BudgetForecaster
from fundshare_app.services.report_service import ReportService


class RecommendationEngine:
    """
    Produces evidence-backed, structured recommendation objects for a single user.
    """

    @classmethod
    def generate_recommendations(cls, user) -> List[Dict[str, Any]]:
        """
        Consumes real financial balances, ML forecasts, genuine anomaly records,
        and FamilyPass status to generate structured recommendation items.
        """
        recommendations = []

        # ----------------------------------------------------
        # 1. Forecast & Budget Warnings (Source: forecast_model / deterministic_rule)
        # ----------------------------------------------------
        funds = PurposeFund.objects.filter(owner=user, status='ACTIVE')
        overrun_funds = []
        surplus_funds = []

        for f in funds:
            alloc = float(f.monthly_budget or f.allocated_amount)
            curr = float(f.current_balance)
            spent = max(0.0, alloc - curr)
            pct_used = round((spent / alloc) * 100.0, 1) if alloc > 0 else 0.0

            fc = BudgetForecaster.forecast_fund(f)
            predicted = float(fc.get('predicted_amount', alloc))
            overrun = float(fc.get('potential_overrun', 0.0))
            risk_level = fc.get('risk_level', 'SAFE')
            confidence = float(fc.get('confidence', 0.80))

            if overrun > 0:
                overrun_funds.append((f, overrun, predicted))
                is_severe = overrun > (alloc * 0.20)
                recommendations.append({
                    "type": "forecast_warning",
                    "priority": "critical" if is_severe else "high",
                    "title": f"{f.name} spending may exceed your monthly budget",
                    "message": (
                        f"The ML forecasting model predicts month-end {f.category} expenditure "
                        f"of ৳{predicted:,.2f}, which is ৳{overrun:,.2f} higher than your ৳{alloc:,.2f} budget."
                    ),
                    "evidence": {
                        "fund_id": f.id,
                        "fund_name": f.name,
                        "category": f.category,
                        "current_balance": curr,
                        "allocated_budget": alloc,
                        "predicted_spending": predicted,
                        "potential_overrun": overrun,
                        "confidence": confidence
                    },
                    "source": "forecast_model",
                    "action": "review_budget"
                })
            else:
                if curr > 500.0:
                    surplus_funds.append((f, curr))

            # Low fund balance rule
            if curr < 250.0 and alloc >= 1000.0 and pct_used >= 85.0:
                recommendations.append({
                    "type": "low_fund_balance",
                    "priority": "high",
                    "title": f"Low available balance in {f.name}",
                    "message": (
                        f"Only ৳{curr:,.2f} remains in your {f.name} ({pct_used}% consumed). "
                        f"Consider adding money before further purchases."
                    ),
                    "evidence": {
                        "fund_id": f.id,
                        "current_balance": curr,
                        "allocated_budget": alloc,
                        "pct_used": pct_used
                    },
                    "source": "deterministic_rule",
                    "action": "allocate_funds"
                })

        # ----------------------------------------------------
        # 2. Inter-Fund Transfer Opportunity (Source: deterministic_rule)
        # ----------------------------------------------------
        if overrun_funds and surplus_funds:
            overrun_f, max_overrun, pred_spent = max(overrun_funds, key=lambda x: x[1])
            surplus_f, max_surplus = max(surplus_funds, key=lambda x: x[1])

            suggested_transfer = min(max_overrun, max_surplus)
            suggested_transfer = max(100.0, round(suggested_transfer / 100.0) * 100.0)

            recommendations.append({
                "type": "saving_opportunity",
                "priority": "medium",
                "title": f"Rebalance: Transfer surplus from {surplus_f.name} to {overrun_f.name}",
                "message": (
                    f"You can prevent a deficit in {overrun_f.name} by transferring "
                    f"৳{suggested_transfer:,.2f} from {surplus_f.name} (available balance: ৳{max_surplus:,.2f})."
                ),
                "evidence": {
                    "source_fund_id": surplus_f.id,
                    "source_fund_name": surplus_f.name,
                    "source_balance": max_surplus,
                    "destination_fund_id": overrun_f.id,
                    "destination_fund_name": overrun_f.name,
                    "destination_deficit": max_overrun,
                    "suggested_transfer": suggested_transfer
                },
                "source": "deterministic_rule",
                "action": "interfund_transfer"
            })

        # ----------------------------------------------------
        # 3. Anomaly Warnings (Source: anomaly_model)
        # ----------------------------------------------------
        recent_anoms = AnomalyResult.objects.filter(
            user=user,
            is_anomaly=True
        ).select_related('transaction', 'transaction__merchant').order_by('-created_at')[:2]

        for a in recent_anoms:
            txn = a.transaction
            if txn:
                m_name = txn.merchant.business_name if txn.merchant else "Merchant"
                recommendations.append({
                    "type": "anomaly_warning",
                    "priority": "high" if a.anomaly_score >= 0.70 else "medium",
                    "title": f"Unusual spending flagged: ৳{float(txn.amount):,.2f} at {m_name}",
                    "message": (
                        f"Transaction {txn.transaction_id} was flagged as unusual by the anomaly detection model. "
                        f"Note: Unusual behavior does not mean fraud; it reflects deviation from typical spending."
                    ),
                    "evidence": {
                        "transaction_id": txn.transaction_id,
                        "amount": float(txn.amount),
                        "category": txn.category or "General",
                        "merchant": m_name,
                        "anomaly_score": round(float(a.anomaly_score), 4),
                        "model_version": a.model_version,
                        "timestamp": txn.timestamp.strftime("%Y-%m-%d %H:%M:%S")
                    },
                    "source": "anomaly_model",
                    "action": "review_transaction"
                })

        # ----------------------------------------------------
        # 4. FamilyPass Warnings (Source: family_pass_rule)
        # ----------------------------------------------------
        active_fps = FamilyPass.objects.filter(owner=user, status='ACTIVE').select_related('member')
        for fp in active_fps:
            limit = float(fp.limit_amount)
            used = float(fp.used_amount)
            usage_pct = round((used / limit) * 100.0, 1) if limit > 0 else 0.0

            if usage_pct >= 85.0 and limit > 0:
                m_name = fp.member.full_name or fp.member.username
                recommendations.append({
                    "type": "family_pass_warning",
                    "priority": "medium",
                    "title": f"FamilyPass for {m_name} near spending limit",
                    "message": (
                        f"{m_name} has used {usage_pct}% of their ৳{limit:,.2f} allowance "
                        f"for {fp.purpose_label or fp.purpose}. Remaining: ৳{max(0.0, limit - used):,.2f}."
                    ),
                    "evidence": {
                        "family_pass_id": fp.id,
                        "member": m_name,
                        "limit_amount": limit,
                        "used_amount": used,
                        "remaining_limit": max(0.0, limit - used),
                        "usage_pct": usage_pct
                    },
                    "source": "family_pass_rule",
                    "action": "manage_family_pass"
                })

        # ----------------------------------------------------
        # 5. Monthly Savings Trend (Source: spending_analysis)
        # ----------------------------------------------------
        report = ReportService.generate_report(user, 'monthly')
        overview = report.get('overview', {})
        total_income = float(overview.get("total_income", 0.0))
        total_spent = float(overview.get("total_spent", 0.0))
        savings_rate = float(overview.get("savings_rate_pct", 0.0))

        if total_income > 0 and savings_rate < 15.0:
            recommendations.append({
                "type": "spending_trend",
                "priority": "low",
                "title": "Monthly savings rate optimization",
                "message": (
                    f"Your savings rate this month is currently {savings_rate:.1f}%. "
                    f"Reviewing discretionary spending can help build your emergency reserves."
                ),
                "evidence": {
                    "total_income": total_income,
                    "total_spent": total_spent,
                    "savings_rate_pct": savings_rate
                },
                "source": "spending_analysis",
                "action": "view_reports"
            })

        return recommendations

    # ========================================================
    # Backward-Compatible Helper Methods for Existing Dashboard
    # ========================================================
    @classmethod
    def get_next_month_recommendations(cls, user) -> list:
        funds = PurposeFund.objects.filter(owner=user, status='ACTIVE')
        recommendations = []

        for fund in funds:
            current_budget = float(fund.monthly_budget or fund.allocated_amount)
            fc = BudgetForecaster.forecast_fund(fund)
            predicted = float(fc.get('predicted_amount', current_budget))
            overrun = float(fc.get('potential_overrun', 0.0))
            dynamic_conf = float(fc.get('confidence', 0.80))

            if overrun > 0:
                suggested = round(predicted / 100.0) * 100.0
                diff = round(suggested - current_budget, 2)
                reason = f"Based on machine learning budget projection (predicted ৳{predicted:,.2f}), increasing allocation by ৳{diff:,.2f} will prevent mid-month shortage."
                confidence = dynamic_conf
            else:
                suggested = current_budget
                diff = 0.0
                reason = f"Current allocation of ৳{current_budget:,.2f} is on track (projected spend: ৳{predicted:,.2f}). Maintain baseline."
                confidence = round(max(0.60, min(0.95, dynamic_conf * 0.95)), 2)

            recommendations.append({
                "fund_id": fund.id,
                "fund_name": fund.name,
                "category": fund.category,
                "current_budget": current_budget,
                "suggested_allocation": suggested,
                "difference": diff,
                "reason": reason,
                "confidence": confidence,
                "historical_trend": []
            })

        return recommendations

    @classmethod
    def get_interfund_transfer_recommendation(cls, user) -> dict:
        funds = PurposeFund.objects.filter(owner=user, status='ACTIVE')
        overrun_fund = None
        surplus_fund = None
        max_overrun = 0.0

        for f in funds:
            fc = BudgetForecaster.forecast_fund(f)
            overrun = float(fc.get('potential_overrun', 0.0))
            curr_bal = float(f.current_balance)
            if overrun > max_overrun:
                max_overrun = overrun
                overrun_fund = f
            elif overrun == 0.0 and curr_bal > 100.0 and surplus_fund is None:
                surplus_fund = f

        if overrun_fund and surplus_fund:
            suggested_amount = min(max_overrun, float(surplus_fund.current_balance))
            suggested_amount = max(100.0, round(suggested_amount / 100.0) * 100.0)
            return {
                "source_fund_id": surplus_fund.id,
                "source_fund_name": surplus_fund.name,
                "source_balance": float(surplus_fund.current_balance),
                "destination_fund_id": overrun_fund.id,
                "destination_fund_name": overrun_fund.name,
                "destination_balance": float(overrun_fund.current_balance),
                "suggested_amount": suggested_amount,
                "rationale": f"Your {overrun_fund.name} Fund is projected to have a ৳{max_overrun:,.2f} deficit by month-end, while your {surplus_fund.name} Fund has an available ৳{float(surplus_fund.current_balance):,.2f} balance. Transferring ৳{suggested_amount:,.2f} balances both allocations smoothly."
            }
        return None

    @classmethod
    def get_behavioral_analysis(cls, user) -> dict:
        report = ReportService.generate_report(user, 'monthly')
        overview = report.get('overview', {})
        savings_rate = overview.get('savings_rate_pct', 0.0)
        total_spent = overview.get('total_spent', 0.0)

        funds = PurposeFund.objects.filter(owner=user, status='ACTIVE')
        fund_utilization = []
        for f in funds:
            alloc = float(f.allocated_amount) if f.allocated_amount > 0 else 1.0
            curr = float(f.current_balance)
            spent = max(0.0, alloc - curr)
            pct = round((spent / alloc) * 100.0, 1)
            fund_utilization.append({
                "fund_id": f.id,
                "name": f.name,
                "allocated": alloc,
                "spent": spent,
                "remaining": curr,
                "utilization_pct": min(100.0, pct),
                "color": f.color
            })

        family_passes = FamilyPass.objects.filter(owner=user, status='ACTIVE')
        fp_summary = []
        fp_members = []
        for fp in family_passes:
            m_name = fp.member.full_name or fp.member.username
            fp_members.append(m_name)
            limit = float(fp.limit_amount)
            used = float(fp.used_amount)
            rem = float(fp.remaining_limit)
            fp_summary.append({
                "member_name": m_name,
                "limit": limit,
                "used": used,
                "remaining": rem,
                "usage_pct": round((used / limit) * 100.0, 1) if limit > 0 else 0.0,
                "expiry_date": fp.expiry_date.strftime("%d %b %Y"),
                "status": fp.status
            })

        discipline_score = min(100.0, max(50.0, round(70.0 + (savings_rate * 0.3), 1)))
        members_str = ", ".join(fp_members) if fp_members else "No active FamilyPass delegations"
        ai_summary = f"Your monthly spending is ৳{total_spent:,.2f} with a calculated savings rate of {savings_rate}%. Discipline score: {discipline_score}/100. FamilyPass active members: {members_str}."

        return {
            "fund_utilization": fund_utilization,
            "mom_shifts": [],
            "family_pass_summary": fp_summary,
            "savings_rate_pct": savings_rate,
            "total_budget_discipline_score": discipline_score,
            "ai_behavioral_summary": ai_summary
        }
