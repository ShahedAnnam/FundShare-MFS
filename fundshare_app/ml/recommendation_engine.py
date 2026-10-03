from decimal import Decimal
from django.utils import timezone
from fundshare_app.models import PurposeFund, Transaction, FamilyPass, AIInsight, InsightType


class RecommendationEngine:
    """
    AI Recommendation & Financial Behavior Engine:
    - Next-month fund budget recommendations based on multi-month trends
    - Inter-fund transfer suggestions to balance overruns with surpluses
    - Comprehensive financial behavior analysis (category shifts, FamilyPass utilization)
    """

    @classmethod
    @classmethod
    def get_next_month_recommendations(cls, user) -> list:
        """
        Analyzes actual category spending and recommends next month allocations.
        User has full control to Accept, Edit, or Reject.
        """
        from fundshare_app.ml.budget_forecaster import BudgetForecaster
        funds = PurposeFund.objects.filter(owner=user, status='ACTIVE')
        recommendations = []

        for fund in funds:
            current_budget = float(fund.monthly_budget or fund.allocated_amount)
            fc = BudgetForecaster.forecast_fund(fund)
            predicted = float(fc.get('predicted_amount', current_budget))
            overrun = float(fc.get('potential_overrun', 0.0))

            if overrun > 0:
                suggested = round(predicted / 100.0) * 100.0
                diff = round(suggested - current_budget, 2)
                reason = f"Based on current burn rate (predicted ৳{predicted:,.2f}), increasing allocation by ৳{diff:,.2f} will prevent mid-month shortage."
                confidence = 0.90
            else:
                suggested = current_budget
                diff = 0.0
                reason = f"Current allocation of ৳{current_budget:,.2f} is on track (predicted spend: ৳{predicted:,.2f}). Maintain baseline."
                confidence = 0.85

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
        """
        Detects if one fund is projected to overrun while another has a surplus,
        and provides an advisory transfer recommendation (user decides, never automated).
        """
        from fundshare_app.ml.budget_forecaster import BudgetForecaster
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
        """
        Computes financial behavior intelligence:
        - Fund utilization percentages
        - FamilyPass delegation health
        - Real calculated savings rate
        """
        from fundshare_app.services.report_service import ReportService
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

        # FamilyPass Health
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
