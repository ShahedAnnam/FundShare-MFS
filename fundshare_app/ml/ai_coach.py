import json
import re
import datetime
from decimal import Decimal
from django.utils import timezone
from django.conf import settings
from fundshare_app.models import PurposeFund, Transaction, FamilyPass, FamilyPassTransaction, AnomalyResult
from fundshare_app.services.report_service import ReportService
from fundshare_app.ml.budget_forecaster import BudgetForecaster
from fundshare_app.ml.demo_qa import find_demo_answer, demo_response
from fundshare_app.ml.support_context import get_support_context, SUPPORT_INSTRUCTION


class FinancialAIService:
    """
    Centralized Financial AI Service for FundShare:
    - Detects user intent (General Conversation vs Structured Financial Query)
    - Retrieves authoritative, grounded financial context from the active user's ledger
    - Answers predefined product questions locally and uses Gemini 3.1 Flash-Lite for other queries
    - Falls back smoothly to authoritative Deterministic Local Analytics on network failure or offline mode
    - Product guidance is predefined; personal financial analytics never use mock balances
    """

    @classmethod
    def detect_intent(cls, question: str) -> str:
        q = (question or "").strip().lower()
        if not q:
            return "GENERAL"

        # Specific financial intents
        spending_keywords = [
            "how much did i spend", "total spend", "my expense", "how much spent",
            "how much i spent", "spent this month", "total expenditure", "spending overview",
            "how much have i spent", "what did i spend", "my spending"
        ]
        category_keywords = [
            "where did i spend", "where i spent", "top category", "spend most",
            "spent most", "category breakdown", "breakdown of spend", "highest expense",
            "highest spending", "which category", "what category"
        ]
        savings_keywords = [
            "how can i save", "how to save", "save money", "savings rate",
            "how much did i save", "savings advice", "save more", "increase savings",
            "save next month", "how to save money"
        ]
        overrun_keywords = [
            "risk", "overrun", "exceed", "which fund", "budget limit",
            "budget status", "at risk", "fund risk", "fund risks", "over budget"
        ]
        familypass_keywords = [
            "familypass", "family pass", "who spent", "member spending",
            "delegation", "family spending", "pass status"
        ]
        recommend_keywords = [
            "next month", "recommend", "allocation", "allocate",
            "suggestion", "suggested fund", "budget recommendation"
        ]
        anomaly_keywords = [
            "unusual", "anomaly", "anomalies", "flagged",
            "suspicious", "fraud", "irregular"
        ]

        if any(k in q for k in spending_keywords):
            return "SPENDING_SUMMARY"
        if any(k in q for k in category_keywords):
            return "CATEGORY_SPENDING"
        if any(k in q for k in savings_keywords):
            return "SAVINGS_ANALYSIS"
        if any(k in q for k in overrun_keywords):
            return "BUDGET_OVERRUN"
        if any(k in q for k in familypass_keywords):
            return "FAMILYPASS"
        if any(k in q for k in recommend_keywords):
            return "RECOMMENDATIONS"
        if any(k in q for k in anomaly_keywords):
            return "ANOMALY"

        # Broad financial terms
        financial_terms = [
            "spend", "spent", "balance", "wallet", "save", "saving", "savings", "budget",
            "fund", "funds", "familypass", "family pass", "transaction", "transactions",
            "income", "expense", "expenses", "taka", "bdt", "tk", "deposit", "transfer", "recharge",
            "bill", "bills", "anomaly", "overrun", "allocation", "merchant", "limit",
            "allowance", "finance", "finances", "financial", "money", "cost", "costs",
            "খরচ", "টাকা", "ব্যালান্স", "সঞ্চয়", "বাজেট", "ফান্ড", "ফ্যামিলিপাস", "লেনদেন"
        ]
        if any(t in q for t in financial_terms):
            return "FINANCIAL_GENERAL"

        return "GENERAL"

    @classmethod
    def get_user_financial_context(cls, user) -> dict:
        wallet = getattr(user, 'wallet', None)
        wallet_bal = float(wallet.balance) if wallet else 0.0

        # Authoritative monthly financial report from database
        report = ReportService.generate_report(user, 'monthly')
        overview = report.get('overview', {})
        by_category = report.get('by_category', {})

        # Active Purpose Funds
        funds = PurposeFund.objects.filter(owner=user, status='ACTIVE')
        funds_data = []
        for f in funds:
            alloc = float(f.allocated_amount)
            curr = float(f.current_balance)
            spent = max(0.0, alloc - curr)
            fc = BudgetForecaster.forecast_fund(f)
            funds_data.append({
                "id": f.id,
                "name": f.name,
                "category": f.category,
                "allocated_budget": alloc,
                "current_spent": spent,
                "current_balance": curr,
                "burn_rate_predicted_spend": float(fc.get('predicted_amount', alloc)),
                "potential_overrun": float(fc.get('potential_overrun', 0.0)),
                "risk_level": fc.get('risk_level', 'SAFE'),
                "pct_used": round((spent / alloc) * 100.0, 1) if alloc > 0 else 0.0
            })

        # FamilyPass data (Issued by user if owner)
        family_passes_issued = FamilyPass.objects.filter(owner=user, status='ACTIVE')
        fp_issued_data = []
        for fp in family_passes_issued:
            limit = float(fp.limit_amount)
            used = float(fp.used_amount)
            rem = float(fp.remaining_limit)
            recent_logs = []
            for item in fp.activity_logs.select_related('transaction', 'transaction__merchant').order_by('-timestamp')[:3]:
                m_name = item.transaction.merchant.business_name if (item.transaction and item.transaction.merchant) else "Merchant"
                recent_logs.append({
                    "amount": float(item.amount),
                    "merchant": m_name,
                    "time": item.timestamp.strftime("%d %b %I:%M %p")
                })
            fp_issued_data.append({
                "member_name": fp.member.full_name or fp.member.username,
                "purpose": fp.purpose_label or fp.purpose,
                "allowed_categories": fp.get_allowed_categories(),
                "limit": limit,
                "used": used,
                "remaining": rem,
                "recent_activity": recent_logs
            })

        # Received permissions coexist with this customer's own wallet and funds.
        family_passes_received = FamilyPass.objects.filter(member=user, status='ACTIVE')
        fp_received_data = []
        for fp in family_passes_received:
            limit = float(fp.limit_amount)
            used = float(fp.used_amount)
            rem = float(fp.remaining_limit)
            recent_logs = []
            for item in fp.activity_logs.select_related('transaction', 'transaction__merchant').order_by('-timestamp')[:3]:
                m_name = item.transaction.merchant.business_name if (item.transaction and item.transaction.merchant) else "Merchant"
                recent_logs.append({
                    "amount": float(item.amount),
                    "merchant": m_name,
                    "time": item.timestamp.strftime("%d %b %I:%M %p")
                })
            fp_received_data.append({
                "owner_name": fp.owner.full_name or fp.owner.username,
                "purpose": fp.purpose_label or fp.purpose,
                "allowed_categories": fp.get_allowed_categories(),
                "limit": limit,
                "used": used,
                "remaining": rem,
                "recent_activity": recent_logs
            })

        # Recent completed transactions (last 8)
        recent_txns = []
        for t in Transaction.objects.filter(sender=user).order_by('-timestamp')[:8]:
            m_name = t.merchant.business_name if t.merchant else (t.receiver.username if t.receiver else "N/A")
            recent_txns.append({
                "id": t.transaction_id,
                "amount": float(t.amount),
                "type": t.transaction_type,
                "source": t.payment_source,
                "category": t.category,
                "target": m_name,
                "status": t.status,
                "time": t.timestamp.strftime("%d %b %I:%M %p")
            })

        # Real Anomalies
        anomalies = []
        for a in AnomalyResult.objects.filter(user=user, is_anomaly=True).order_by('-created_at')[:4]:
            anomalies.append({
                "txn_id": a.transaction.transaction_id if a.transaction else "TXN",
                "amount": float(a.transaction.amount) if a.transaction else 0.0,
                "category": a.transaction.category if a.transaction else "N/A",
                "score": a.anomaly_score,
                "reason": a.reason
            })

        return {
            "user_name": user.full_name or user.username,
            "username": user.username,
            "role": user.role,
            "wallet_balance": wallet_bal,
            "monthly_report": {
                "total_income": overview.get("total_income", 0.0),
                "total_spent": overview.get("total_spent", 0.0),
                "net_savings": overview.get("net_savings", 0.0),
                "savings_rate": overview.get("savings_rate_pct", 0.0),
                "total_transactions": overview.get("total_transactions", 0),
                "average_transaction": overview.get("average_transaction", 0.0),
                "by_category": by_category
            },
            "purpose_funds": funds_data,
            "family_passes_issued": fp_issued_data,
            "family_passes_received": fp_received_data,
            "recent_transactions": recent_txns,
            "anomalies": anomalies,
            "ml_forecasts_available": len(funds_data) > 0,
            "market_signals": "Market signals unavailable (live external market feeds not connected)"
        }

    @classmethod
    def generate_online_response(cls, user, question: str, intent: str, facts: dict, lang: str = 'en') -> dict:
        gemini_key = getattr(settings, 'GEMINI_API_KEY', '').strip()
        if not gemini_key:
            return None

        try:
            from google import genai
            from google.genai import types

            context = get_support_context(user)
            model_name = getattr(settings, 'GEMINI_MODEL', 'gemini-3.1-flash-lite')
            system_instruction = SUPPORT_INSTRUCTION + f"\nReply in {'Bengali' if lang == 'bn' else 'English'}."
            contents = json.dumps({'authorized_context': context, 'user_question': question}, default=str)
            with genai.Client(api_key=gemini_key, http_options=types.HttpOptions(timeout=15000, retry_options=types.HttpRetryOptions(attempts=1))) as client:
                response = client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=types.GenerateContentConfig(system_instruction=system_instruction, max_output_tokens=1200),
                )
            if response and response.text and response.text.strip():
                return {
                    "question": question,
                    "answer": response.text,
                    "source": "Gemini 3.1 Flash-Lite",
                    "ai_powered": True,
                    "online": True,
                    "intent": intent,
                    "grounded_facts": context,
                    "suggested_actions": cls._suggest_actions_for_intent(intent, context),
                }
        except Exception:
            # Never return or log provider exceptions: they can contain credentials.
            pass
        return None

    @classmethod
    def deterministic_offline_analysis(cls, user, question: str, intent: str, facts: dict, lang: str = 'en') -> dict:
        mr = facts['monthly_report']

        if intent == "GENERAL":
            if lang == "bn":
                text = (
                    "👋 **হ্যালো!** আমি ফান্ডশেয়ার (FundShare) ফিনান্সিয়াল ইন্টেলিজেন্স কোচ।\n\n"
                    "বর্তমানে অফলাইন ডিটারমিনিস্টিক ইঞ্জিন সক্রিয় রয়েছে। সাধারণ জ্ঞান বা সাধারণ আলোচনার জন্য অনলাইন কানেকশন প্রয়োজন, তবে আপনি আপনার **ওয়ালেট ব্যালান্স, খরচ বিবরণ, পারপাস ফান্ড, বাজেট এবং ফ্যামিলিপাস** সম্পর্কে যেকোনো হিসাব জানতে পারেন!"
                )
            else:
                text = (
                    "👋 **Hello!** I am your FundShare Financial Intelligence Coach.\n\n"
                    "Currently, the offline deterministic financial engine is active. While open-ended general conversations require an active online Gemini connection, you can ask me anything about your **account balance, spending breakdown, budget forecasts, purpose funds, or FamilyPass delegations** based directly on your ledger."
                )
            return {
                "question": question,
                "answer": text,
                "source": "Offline Financial Intelligence Engine",
                "ai_powered": False,
                "online": False,
                "intent": intent,
                "suggested_actions": []
            }

        elif intent == "SPENDING_SUMMARY":
            total_spent = mr['total_spent']
            txns_count = mr['total_transactions']
            avg_txn = mr['average_transaction']
            by_cat = mr['by_category']
            cat_lines = "\n".join([f"  • **{cat}:** ৳{amt:,.2f}" for cat, amt in by_cat.items()]) if by_cat else "  • No category expenses recorded."

            if lang == "bn":
                text = (
                    f"📊 **আপনার মাসিক খরচ সারসংক্ষেপ:**\n\n"
                    f"• এই মাসে সর্বমোট খরচ: **৳{total_spent:,.2f}** ({txns_count} টি লেনদেন)\n"
                    f"• গড়ে প্রতি লেনদেন: **৳{avg_txn:,.2f}**\n\n"
                    f"**ক্যাটাগরি ভিত্তিক খরচ:**\n{cat_lines}"
                )
            else:
                text = (
                    f"📊 **Monthly Spending Overview:**\n\n"
                    f"• **Total Spent This Month:** **৳{total_spent:,.2f}** across {txns_count} completed transactions.\n"
                    f"• **Average Transaction Amount:** **৳{avg_txn:,.2f}**\n\n"
                    f"**Category Breakdown:**\n{cat_lines}"
                )
            return {
                "question": question,
                "answer": text,
                "source": "Offline Financial Intelligence Engine",
                "ai_powered": False,
                "online": False,
                "intent": intent,
                "suggested_actions": [{"type": "NAVIGATE_HISTORY", "label": "View Transactions"}]
            }

        elif intent == "CATEGORY_SPENDING":
            by_cat = mr['by_category']
            if by_cat:
                top_cat, top_amt = list(by_cat.items())[0]
                cat_lines = "\n".join([f"• **{cat}:** ৳{amt:,.2f}" for cat, amt in by_cat.items()])
                if lang == "bn":
                    text = (
                        f"🏆 **সর্বোচ্চ খরচের খাত: {top_cat} (৳{top_amt:,.2f})**\n\n"
                        f"**সম্পূর্ণ ক্যাটাগরি তালিকা:**\n{cat_lines}"
                    )
                else:
                    text = (
                        f"🏆 **Top Spending Category: {top_cat} (৳{top_amt:,.2f})**\n\n"
                        f"**Full Category Breakdown:**\n{cat_lines}"
                    )
            else:
                text = "📊 You have not recorded any category expenses for this period."

            return {
                "question": question,
                "answer": text,
                "source": "Offline Financial Intelligence Engine",
                "ai_powered": False,
                "online": False,
                "intent": intent,
                "suggested_actions": []
            }

        elif intent == "SAVINGS_ANALYSIS":
            income = mr['total_income']
            spent = mr['total_spent']
            savings = mr['net_savings']
            rate = mr['savings_rate']
            by_cat = mr['by_category']
            top_cat = list(by_cat.keys())[0] if by_cat else "discretionary spending"

            if lang == "bn":
                text = (
                    f"💰 **সঞ্চয় ও আর্থিক শৃঙ্খলা বিশ্লেষণ:**\n\n"
                    f"• মোট আয়: **৳{income:,.2f}**\n"
                    f"• মোট ব্যয়: **৳{spent:,.2f}**\n"
                    f"• নিট সঞ্চয়: **৳{savings:,.2f}**\n"
                    f"• সঞ্চয়ের হার: **{rate}%**\n\n"
                    f"💡 **সাশ্রয়ী পরামর্শ:** আগামী মাসে সঞ্চয় বৃদ্ধি করতে আপনার প্রধান খরচের খাত ({top_cat}) এর উপর নজর রাখুন এবং পারপাস ফান্ড বাজেটের অতিরিক্ত ব্যবহার পরিহার করুন।"
                )
            else:
                text = (
                    f"💰 **Savings & Financial Discipline Analysis:**\n\n"
                    f"• **Total Income:** **৳{income:,.2f}**\n"
                    f"• **Total Spent:** **৳{spent:,.2f}**\n"
                    f"• **Net Savings:** **৳{savings:,.2f}**\n"
                    f"• **Savings Rate:** **{rate}%**\n\n"
                    f"💡 **Actionable Advice:** To maximize savings next month, focus on moderating outlays in your largest spending category (**{top_cat}**) and allocate a fixed portion of income to your Purpose Funds at the start of the month."
                )
            return {
                "question": question,
                "answer": text,
                "source": "Offline Financial Intelligence Engine",
                "ai_powered": False,
                "online": False,
                "intent": intent,
                "suggested_actions": [{"type": "NAVIGATE_FUNDS", "label": "Review Funds"}]
            }

        elif intent == "BUDGET_OVERRUN":
            funds = facts['purpose_funds']
            at_risk = [f for f in funds if f['potential_overrun'] > 0]
            if at_risk:
                lines = []
                for f in at_risk:
                    lines.append(f"• **{f['name']} Fund:** Spent ৳{f['current_spent']:,.2f} / ৳{f['allocated_budget']:,.2f} (Projected: ৳{f['burn_rate_predicted_spend']:,.2f}, Overrun: ৳{f['potential_overrun']:,.2f})")
                text = "⚠️ **Purpose Funds at Risk of Overrun:**\n\n" + "\n".join(lines)
                actions = [{"type": "NAVIGATE_FUNDS", "label": "Manage Funds"}]
            elif funds:
                text = "✅ **All Purpose Funds are on track!** No projected budget overruns detected based on current burn rates."
                actions = [{"type": "NAVIGATE_FUNDS", "label": "View Funds"}]
            else:
                text = "ℹ️ You do not have any active Purpose Funds configured yet. Create a Purpose Fund to track specific budgets."
                actions = [{"type": "NAVIGATE_FUNDS", "label": "Create Fund"}]

            return {
                "question": question,
                "answer": text,
                "source": "Offline Financial Intelligence Engine",
                "ai_powered": False,
                "online": False,
                "intent": intent,
                "suggested_actions": actions
            }

        elif intent == "FAMILYPASS":
            issued = facts['family_passes_issued']
            received = facts['family_passes_received']

            lines = []
            if issued:
                lines.append("👥 **Active FamilyPass Delegations (Issued by you):**")
                for fp in issued:
                    lines.append(f"• **{fp['member_name']}** ({fp['purpose']}): Limit ৳{fp['limit']:,.2f} | Spent ৳{fp['used']:,.2f} | Remaining **৳{fp['remaining']:,.2f}**")
            if received:
                lines.append("👥 **FamilyPass Allocations (Received from family):**")
                for fp in received:
                    lines.append(f"• From **{fp['owner_name']}** ({fp['purpose']}): Limit ৳{fp['limit']:,.2f} | Spent ৳{fp['used']:,.2f} | Remaining **৳{fp['remaining']:,.2f}**")

            if lines:
                text = "\n".join(lines)
            else:
                text = "👥 **FamilyPass Status:** No active FamilyPass delegations found for your account."

            return {
                "question": question,
                "answer": text,
                "source": "Offline Financial Intelligence Engine",
                "ai_powered": False,
                "online": False,
                "intent": intent,
                "suggested_actions": [{"type": "NAVIGATE_FAMILYPASS", "label": "FamilyPass Dashboard"}]
            }

        elif intent == "RECOMMENDATIONS":
            funds = facts['purpose_funds']
            if funds:
                lines = []
                for f in funds:
                    rec_amt = f['burn_rate_predicted_spend'] if f['potential_overrun'] > 0 else f['allocated_budget']
                    lines.append(f"• **{f['name']} Fund:** Current ৳{f['allocated_budget']:,.2f} → Recommended **৳{rec_amt:,.2f}** ({'adjust up to cover burn rate' if f['potential_overrun'] > 0 else 'maintain healthy baseline'})")
                text = "🎯 **Recommended Fund Budget Allocations for Next Month:**\n\n" + "\n".join(lines) + "\n\n💡 *Note: Recommendations are advisory; you retain full control over fund transfers.*"
            else:
                text = "🎯 **Next Month Recommendations:** Start by creating Purpose Funds for your essential categories like Grocery, Medical, and Utilities to receive personalized budget optimizations."

            return {
                "question": question,
                "answer": text,
                "source": "Offline Financial Intelligence Engine",
                "ai_powered": False,
                "online": False,
                "intent": intent,
                "suggested_actions": [{"type": "NAVIGATE_FUNDS", "label": "Adjust Funds"}]
            }

        elif intent == "ANOMALY":
            anomalies = facts['anomalies']
            if anomalies:
                lines = []
                for a in anomalies:
                    lines.append(f"• **{a['txn_id']}** (৳{a['amount']:,.2f}, {a['category']}): {a['reason']} (Score: {a['score']:.2f})")
                text = "🔍 **Flagged Unusual Transactions:**\n\n" + "\n".join(lines)
            else:
                text = "🔍 **Anomaly Audit:** No unusual or outlier transactions have been flagged on your account."

            return {
                "question": question,
                "answer": text,
                "source": "Offline Financial Intelligence Engine",
                "ai_powered": False,
                "online": False,
                "intent": intent,
                "suggested_actions": [{"type": "NAVIGATE_HISTORY", "label": "Inspect History"}]
            }

        else:  # FINANCIAL_GENERAL / default
            funds_count = len(facts['purpose_funds'])
            passes_count = len(facts['family_passes_issued']) + len(facts['family_passes_received'])
            text = (
                f"📑 **Executive Financial Health Summary:**\n\n"
                f"• Available Normal Wallet: **৳{facts['wallet_balance']:,.2f}**\n"
                f"• This Month's Income: **৳{mr['total_income']:,.2f}** | Total Spent: **৳{mr['total_spent']:,.2f}**\n"
                f"• Net Savings: **৳{mr['net_savings']:,.2f}** (Savings Rate: **{mr['savings_rate']}%**)\n"
                f"• Active Purpose Funds: **{funds_count} categories**\n"
                f"• Active FamilyPass Delegations: **{passes_count} active**\n\n"
                f"**Advice:** Keep your spending disciplined and maintain emergency reserves in your Purpose Funds."
            )
            return {
                "question": question,
                "answer": text,
                "source": "Offline Financial Intelligence Engine",
                "ai_powered": False,
                "online": False,
                "intent": intent,
                "suggested_actions": []
            }

    @classmethod
    def _suggest_actions_for_intent(cls, intent: str, facts: dict) -> list:
        if intent == "BUDGET_OVERRUN" or intent == "RECOMMENDATIONS":
            return [{"type": "NAVIGATE_FUNDS", "label": "Manage Funds"}]
        elif intent == "FAMILYPASS":
            return [{"type": "NAVIGATE_FAMILYPASS", "label": "FamilyPass"}]
        elif intent == "ANOMALY" or intent == "SPENDING_SUMMARY":
            return [{"type": "NAVIGATE_HISTORY", "label": "Transactions"}]
        return []

    @classmethod
    def answer_query(cls, user, question: str, lang: str = "en") -> dict:
        """
        Main query entry point:
        1. Matches exact predefined product questions without external calls
        2. Detects intent and attempts bounded, authorized Gemini support
        3. Preserves deterministic financial analytics on provider failure
        """
        entry = find_demo_answer(question)
        if entry:
            return demo_response(question, entry)
        intent = cls.detect_intent(question)

        # Attempt Online Gemini call first
        online_response = cls.generate_online_response(user, question, intent, {}, lang)
        if online_response:
            return online_response

        # Fallback to Deterministic Offline Analytics
        facts = cls.get_user_financial_context(user)
        response = cls.deterministic_offline_analysis(user, question, intent, facts, lang)
        response['fallback'] = True
        response['notice'] = 'Gemini is unavailable. Demo answers and local financial insights are still available.'
        return response


# Backward-compatible alias for existing imports
AICoach = FinancialAIService
