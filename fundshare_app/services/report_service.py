import calendar
import datetime
from decimal import Decimal
from django.utils import timezone
from django.db.models import Q
from fundshare_app.models import (
    PurposeFund, Transaction, FamilyPass, AnomalyResult, BudgetForecast,
    TransactionType, TransactionStatus, PaymentSource
)
from fundshare_app.ml.budget_forecaster import BudgetForecaster


class ReportService:
    """
    Generates structured Weekly, Monthly, and Yearly financial reports for the customer.
    Follows Section 17 of the Hackathon specifications.
    """

    @classmethod
    def generate_report(cls, user, period_type: str = "monthly") -> dict:
        now = timezone.now()
        year = now.year
        month = now.month

        # Period filtering based on transaction timestamp
        period_type_lower = (period_type or "monthly").lower()
        if period_type_lower == "weekly":
            start_date = now - datetime.timedelta(days=7)
            period_filter = {'timestamp__gte': start_date}
            anomaly_period_filter = {'created_at__gte': start_date}
            period_title = "WEEKLY FINANCIAL REPORT (Last 7 Days)"
        elif period_type_lower == "yearly":
            period_filter = {'timestamp__year': year}
            anomaly_period_filter = {'created_at__year': year}
            period_title = f"ANNUAL FINANCIAL REPORT {year}"
        else:  # monthly default
            period_filter = {'timestamp__year': year, 'timestamp__month': month}
            anomaly_period_filter = {'created_at__year': year, 'created_at__month': month}
            month_name = now.strftime('%B').upper()
            period_title = f"{month_name} {year} FINANCIAL REPORT"

        # Spending Query:
        # 1. Direct spending by this user from normal wallet or purpose fund:
        #    sender=user, transaction_type in [MERCHANT_PAYMENT, BILL_PAYMENT, MOBILE_RECHARGE, CASH_OUT], status=COMPLETED
        #    EXCLUDING FamilyPass payments where user is a member (funded by someone else's wallet)
        # 2. Plus FamilyPass spending funded by this user as Owner:
        #    family_pass__owner=user, payment_source=FAMILY_PASS, status=COMPLETED
        spending_filter = (
            Q(sender=user, status=TransactionStatus.COMPLETED) &
            ~Q(payment_source=PaymentSource.FAMILY_PASS) &
            Q(transaction_type__in=[
                TransactionType.MERCHANT_PAYMENT,
                TransactionType.BILL_PAYMENT,
                TransactionType.MOBILE_RECHARGE,
                TransactionType.CASH_OUT
            ])
        ) | (
            Q(family_pass__owner=user,
              payment_source=PaymentSource.FAMILY_PASS,
              status=TransactionStatus.COMPLETED)
        )

        spending_qs = Transaction.objects.filter(
            spending_filter,
            **period_filter
        ).distinct()

        total_spent = sum([float(t.amount) for t in spending_qs])
        total_transactions = spending_qs.count()
        average_transaction = round(total_spent / total_transactions, 2) if total_transactions > 0 else 0.0

        # Income Query:
        # Cash in to wallet, or incoming send/receive money where user is receiver and not sender
        income_filter = (
            Q(receiver=user, transaction_type=TransactionType.CASH_IN, status=TransactionStatus.COMPLETED)
        ) | (
            Q(receiver=user, status=TransactionStatus.COMPLETED) &
            Q(transaction_type__in=[TransactionType.SEND_MONEY, TransactionType.RECEIVE_MONEY]) &
            ~Q(sender=user)
        )

        income_qs = Transaction.objects.filter(
            income_filter,
            **period_filter
        ).distinct()

        total_income = sum([float(t.amount) for t in income_qs])
        net_savings = max(0.0, total_income - total_spent)
        savings_rate = round(net_savings / total_income, 4) if total_income > 0 else 0.0
        savings_rate_pct = round(savings_rate * 100.0, 1)

        # Category Breakdown
        categories = {}
        for t in spending_qs:
            cat = t.category or 'Other'
            categories[cat] = categories.get(cat, 0.0) + float(t.amount)

        by_category = {cat: round(amt, 2) for cat, amt in sorted(categories.items(), key=lambda x: x[1], reverse=True) if amt > 0}

        cat_breakdown = [
            {
                "category": cat,
                "amount": amt,
                "percentage": round((amt / total_spent) * 100.0, 1) if total_spent > 0 else 0.0
            }
            for cat, amt in by_category.items()
        ]

        if by_category:
            highest_cat = list(by_category.keys())[0]
            highest_amt = by_category[highest_cat]
            most_increased_category = f"{highest_cat} (Highest volume)"
        else:
            highest_cat = "None"
            highest_amt = 0.0
            most_increased_category = "None"

        # Fund-wise spending
        funds = PurposeFund.objects.filter(owner=user, status='ACTIVE')
        fund_breakdown = []
        overrun_risks = []
        for f in funds:
            alloc = float(f.allocated_amount)
            curr = float(f.current_balance)
            spent = max(0.0, alloc - curr)
            fc = BudgetForecaster.forecast_fund(f)
            if fc.get("potential_overrun", 0) > 0:
                overrun_risks.append(f"{f.name} (Risk: ৳{fc['potential_overrun']:,.2f} overrun)")
            fund_breakdown.append({
                "fund_name": f.name,
                "category": f.category,
                "allocated": alloc,
                "spent": round(spent, 2),
                "remaining": round(curr, 2),
                "utilization_pct": round((spent / alloc) * 100.0, 1) if alloc > 0 else 0.0
            })

        potential_budget_risk = ", ".join(overrun_risks) if overrun_risks else "None identified"

        # FamilyPass Breakdown
        family_passes = FamilyPass.objects.filter(owner=user, status='ACTIVE')
        fp_total_spent = 0.0
        fp_members_detail = []
        for fp in family_passes:
            used = float(fp.used_amount)
            fp_total_spent += used
            fp_members_detail.append({
                "member_name": fp.member.full_name or fp.member.username,
                "limit": float(fp.limit_amount),
                "spent": used,
                "remaining": float(fp.remaining_limit),
                "utilization_pct": round((used / float(fp.limit_amount)) * 100.0, 1) if fp.limit_amount > 0 else 0.0
            })

        # Anomalies during period
        anomalies_qs = AnomalyResult.objects.filter(
            user=user,
            is_anomaly=True,
            **anomaly_period_filter
        ).order_by('-created_at')[:3]
        if user.effective_role != 'ADMIN':
            anomalies_qs = AnomalyResult.objects.none()
        anomaly_list = []
        for a in anomalies_qs:
            anomaly_list.append({
                "txn_id": a.transaction.transaction_id,
                "amount": float(a.transaction.amount),
                "category": a.transaction.category,
                "reason": a.reason,
                "score": a.anomaly_score
            })

        # Dynamic AI Summary (authentic data)
        if total_spent > 0 or total_income > 0:
            summary_parts = [
                f"During this {period_type_lower} period, total recorded income was ৳{total_income:,.2f} with expenditures of ৳{total_spent:,.2f}, resulting in net savings of ৳{net_savings:,.2f} ({savings_rate_pct}% savings rate)."
            ]
            if highest_cat != "None":
                summary_parts.append(f"Highest spending category: {highest_cat} (৳{highest_amt:,.2f}).")
            if fp_total_spent > 0:
                summary_parts.append(f"FamilyPass delegations accounted for ৳{fp_total_spent:,.2f} of total household expenses.")
            if overrun_risks:
                summary_parts.append(f"Budget risks flagged: {potential_budget_risk}.")
            else:
                summary_parts.append("All active purpose funds remain within spending targets.")
            ai_summary = " ".join(summary_parts)
        else:
            ai_summary = f"No transactions recorded for this account during the selected {period_type_lower} timeframe."

        return {
            "overview": {
                "total_spent": round(total_spent, 2),
                "total_income": round(total_income, 2),
                "net_savings": round(net_savings, 2),
                "total_transactions": total_transactions,
                "average_transaction": average_transaction,
                "savings_rate": savings_rate
            },
            "by_category": by_category,
            "report_title": period_title,
            "period_type": period_type,
            "currency": "BDT (৳)",
            "total_income": round(total_income, 2),
            "total_spending": round(total_spent, 2),
            "net_savings": round(net_savings, 2),
            "savings_rate_pct": savings_rate_pct,
            "highest_spending_category": highest_cat,
            "most_increased_category": most_increased_category,
            "potential_budget_risk": potential_budget_risk,
            "family_pass_total_spent": round(fp_total_spent, 2),
            "family_pass_members": fp_members_detail,
            "category_breakdown": cat_breakdown,
            "fund_breakdown": fund_breakdown,
            **({'anomalies': anomaly_list} if user.effective_role == 'ADMIN' else {}),
            "ai_summary": ai_summary,
            "generated_at": timezone.now().strftime("%d %B %Y, %I:%M %p")
        }
