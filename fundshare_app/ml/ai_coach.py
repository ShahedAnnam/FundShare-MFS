"""
FUNDShare ML Pipeline - Grounded AI Coach & Decision Support Service
Integrates:
- MLContextBuilder for single-user grounded financial facts
- Strict system prompt adhering to AI safety & anti-hallucination rules
- Conversational Gemini inference with strict advisory-only scope
- Graceful offline fallback to deterministic financial analytics
- Transaction-level explainability ("unusual != fraudulent")
"""
import json
import os
import re
from decimal import Decimal
from typing import Dict, Any, Optional

from django.conf import settings
from django.utils import timezone
from fundshare_app.models import Transaction, AnomalyResult, PurposeFund, FamilyPass
from fundshare_app.ml.context_builder import MLContextBuilder
from fundshare_app.ml.anomaly_detector import AnomalyDetector
from fundshare_app.ml.budget_forecaster import BudgetForecaster
from fundshare_app.ml.recommendation_engine import RecommendationEngine
from fundshare_app.ml.demo_qa import DEMO_QA, find_demo_answer, demo_response
from fundshare_app.ml.support_context import get_support_context, SUPPORT_INSTRUCTION


class FinancialAIService:
    """
    Authoritative Financial AI Service:
    - Gathers user-specific context via MLContextBuilder (strict user isolation)
    - Grounded natural language explanation via Gemini LLM
    - Guaranteed fallback to deterministic analytics on API failure or offline mode
    - Strict non-autonomous safety: NEVER executes transactions or changes balances
    """

    @classmethod
    def detect_intent(cls, question: str) -> str:
        q = (question or "").strip().lower()
        if not q:
            return "GENERAL"

        # Check for autonomous action attempts first
        action_keywords = [
            "transfer", "send money", "pay", "deposit", "allocate", "change limit",
            "set limit", "delete fund", "create fund", "modify", "execute",
            "টাকা পাঠাও", "ট্রান্সফার করো", "পেমেন্ট করো"
        ]
        if any(k in q for k in action_keywords):
            # Check if user is asking the AI to perform the action vs asking about an action
            action_triggers = ["transfer ৳", "send ৳", "pay ৳", "transfer money", "send money to", "pay to", "please transfer", "can you send"]
            if any(t in q for t in action_triggers):
                return "ACTION_REQUEST"

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
            "budget status", "at risk", "fund risk", "fund risks", "over budget",
            "forecast", "how much might i spend", "projected"
        ]
        familypass_keywords = [
            "familypass", "family pass", "who spent", "member spending",
            "delegation", "family spending", "pass status"
        ]
        recommend_keywords = [
            "next month", "recommend", "allocation", "allocate",
            "suggestion", "suggested fund", "budget recommendation", "what should i watch"
        ]
        anomaly_keywords = [
            "unusual", "anomaly", "anomalies", "flagged",
            "why was my", "why was this", "irregular", "flag"
        ]

        # Action Request Defense (refuse autonomous financial movements)
        action_patterns = [
            "transfer ৳", "transfer tk", "transfer bdt", "transfer money", "transfer fund",
            "send money", "pay merchant", "make payment", "pay ৳", "pay tk",
            "withdraw cash"
        ]
        is_limit_change = any(v in q for v in ["change", "set", "update", "increase", "decrease"]) and "limit" in q
        if q.startswith("transfer ") or is_limit_change or any(p in q for p in action_patterns):
            if not any(q.startswith(w) for w in ["how to", "why did", "what is", "can i see", "explain"]):
                return "ACTION_REQUEST"

        if any(k in q for k in anomaly_keywords):
            return "ANOMALY"
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
    def get_user_financial_context(cls, user) -> Dict[str, Any]:
        """Gathers context strictly for this authenticated user."""
        return MLContextBuilder.build_user_context(user)

    @classmethod
    def explain_transaction(cls, user, transaction: Transaction) -> Dict[str, Any]:
        """
        Generates an authoritative, grounded explanation for a single transaction.
        Language rule: "unusual != fraudulent".
        """
        amt = float(transaction.amount)
        cat = transaction.category or 'General'
        ts = transaction.timestamp.strftime("%Y-%m-%d %H:%M:%S")

        # Check existing ML anomaly record
        anom_res = AnomalyResult.objects.filter(transaction=transaction).first()
        is_anomaly = anom_res.is_anomaly if anom_res else False
        score = float(anom_res.anomaly_score) if anom_res else 0.0

        detector = AnomalyDetector.get_instance()
        analysis = detector.analyze_transaction(transaction)

        if is_anomaly:
            explanation = (
                f"This transaction of ৳{amt:,.2f} in {cat} was flagged as unusual by the "
                f"Isolation Forest anomaly detection model (anomaly score: {score:.2f}).\n\n"
                f"Important: An unusual transaction reflects a statistical departure from your "
                f"typical spending baseline (e.g. higher amount or non-standard timing); it does NOT "
                f"mean the transaction is fraudulent.\n\n"
                f"Key factors identified:\n{analysis['reason']}"
            )
        else:
            explanation = (
                f"This transaction of ৳{amt:,.2f} in {cat} on {ts} aligns with your normal "
                f"historical financial patterns. The anomaly score is {score:.2f}, which is within "
                f"normal statistical control thresholds."
            )

        return {
            "transaction_id": transaction.transaction_id,
            "amount": amt,
            "category": cat,
            "timestamp": ts,
            "is_anomaly": is_anomaly,
            "anomaly_score": round(score, 4),
            "model_version": anom_res.model_version if anom_res else detector.model_version,
            "explanation": explanation,
            "rules_flagged": analysis.get('rules_flagged', []),
            "features_summary": analysis.get('features_summary', {})
        }

    @classmethod
    def generate_online_response(cls, user, question: str, intent: str, facts: dict, lang: str = 'en') -> Optional[Dict[str, Any]]:
        """
        Invokes Gemini with the 19 strict grounded AI Coach guidelines.
        Returns None if Gemini key is missing, call fails, or times out.
        """
        gemini_key = getattr(settings, 'GEMINI_API_KEY', '').strip()
        if not gemini_key:
            return None

        # Autonomous action defense: Intercept action requests immediately
        if intent == "ACTION_REQUEST":
            return cls._handle_action_refusal(question, lang)

        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=gemini_key, http_options=types.HttpOptions(timeout=10000))

            mo = facts['monthly_overview']
            system_instruction = (
                "You are the AI Financial Coach for FundShare, an innovative MFS (Mobile Financial Services) platform in Bangladesh.\n"
                "Your role is STRICTLY ADVISORY. You explain information conversationally based ONLY on the supplied user context.\n\n"
                "MANDATORY OPERATIONAL RULES:\n"
                "1. Use ONLY the supplied user financial facts. Never invent balances, transactions, forecasts, anomaly scores, or dates.\n"
                "2. Never access, infer, or discuss another user's information.\n"
                "3. Never claim an anomaly means fraud. Explicitly state that unusual behavior does not mean fraudulent activity.\n"
                "4. Clearly distinguish: (a) ML model predictions, (b) deterministic business rules, (c) historical ledger facts, and (d) AI explanation.\n"
                "5. If requested information is missing, state truthfully that sufficient historical data is unavailable.\n"
                "6. Do not fabricate confidence values or future transactions.\n"
                "7. DO NOT authorize payments, DO NOT transfer money, DO NOT modify funds, and DO NOT change limits.\n"
                "8. If the user asks you to execute a financial action (e.g. transfer money), explain that you cannot execute actions directly and guide them to use FundShare's authorized PIN confirmation flow.\n"
                "9. When discussing forecasts, use phrases like 'the model predicts', 'based on recent spending', 'the system detected'. Never present predictions as guaranteed outcomes.\n"
                "10. All currency in Bangladeshi Taka (৳). Language: " + ('Bengali' if lang == 'bn' else 'English') + ".\n"
            )

            user_prompt = (
                f"AUTHENTICATED USER FINANCIAL CONTEXT:\n"
                f"- Name: {facts['user']['name']} ({facts['user']['username']})\n"
                f"- Wallet Balance: ৳{facts['wallet']['balance']:,.2f}\n"
                f"- This Month's Income: ৳{mo['total_income']:,.2f}\n"
                f"- This Month's Spent: ৳{mo['total_spent']:,.2f}\n"
                f"- Net Savings: ৳{mo['net_savings']:,.2f} (Savings Rate: {mo['savings_rate_pct']}%)\n"
                f"- Category Breakdown: {mo['by_category']}\n"
                f"- Active Purpose Funds & Forecasts: {facts['purpose_funds']}\n"
                f"- FamilyPass Issued: {facts['family_passes_issued']}\n"
                f"- FamilyPass Received: {facts['family_passes_received']}\n"
                f"- Recent Transactions: {facts['recent_spending']}\n"
                f"- Flagged Anomalies: {facts['anomalies']}\n"
                f"- Financial Health Signals: {facts['financial_signals']}\n\n"
                f"USER QUESTION: {question}\n\n"
                f"Provide a concise, grounded, empathetic answer:"
            )

            # Build support context and contents
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
                    "answer": response.text.strip(),
                    "source": f"{model_name} (AI-Grounded)",
                    "ai_powered": True,
                    "online": True,
                    "intent": intent,
                    "grounded_facts": context,
                    "suggested_actions": cls._suggest_actions_for_intent(intent, context),
                }

        except Exception:
            pass

        return None

    @classmethod
    def _handle_action_refusal(cls, question: str, lang: str = 'en') -> Dict[str, Any]:
        """Refuses autonomous financial action execution with safe guidance."""
        if lang == 'bn':
            text = (
                "🛡️ **নিরাপত্তা সতর্কতা:**\n\n"
                "আমি আপনার পরামর্শক এআই কোচ, তাই আমি নিজে কোনো লেনদেন বা টাকা স্থানান্তর সম্পাদন করতে পারি না।\n\n"
                "আপনার সুরক্ষার জন্য সকল লেনদেন অবশ্যই ফান্ডশেয়ার অ্যাপের মাধ্যমে আপনার **গোপন ট্রানজ্যাকশন পিন (PIN)** দিয়ে সম্পন্ন করতে হবে।\n"
                "অনুগ্রহ করে ড্যাশবোর্ডের 'Send Money' বা 'Purpose Funds' মেনু থেকে লেনদেনটি সম্পন্ন করুন।"
            )
        else:
            text = (
                "🛡️ **Security Safeguard:**\n\n"
                "As your advisory AI Financial Coach, I cannot directly execute financial transfers, make payments, or alter balances on your account.\n\n"
                "For your security, all financial actions require explicit authorization and your **secure transaction PIN** through FundShare's authorized payment flows.\n\n"
                "Please use the **Send Money** or **Purpose Funds** section in your dashboard to perform this transfer."
            )
        return {
            "question": question,
            "answer": text,
            "source": "Security Policy Enforcement",
            "ai_powered": False,
            "online": True,
            "intent": "ACTION_REQUEST",
            "is_action_refusal": True,
            "suggested_actions": [{"type": "NAVIGATE_FUNDS", "label": "Manage Funds"}]
        }

    @classmethod
    def deterministic_offline_analysis(cls, user, question: str, intent: str, facts: dict, lang: str = 'en') -> Dict[str, Any]:
        """
        Robust offline fallback providing 100% grounded analytics directly from ledger data.
        Ensures the application functions smoothly without crashing when Gemini is offline.
        """
        mo = facts['monthly_overview']
        wallet_bal = facts['wallet']['balance']

        if intent == "ACTION_REQUEST":
            return cls._handle_action_refusal(question, lang)

        if intent == "ANOMALY":
            anoms = facts['anomalies']
            if anoms:
                latest = anoms[0]
                text = (
                    f"🔍 **Unusual Spending Analysis:**\n\n"
                    f"Transaction **{latest['transaction_id']}** (৳{latest['amount']:,.2f} in {latest['category']}) "
                    f"was flagged as unusual by the anomaly detection model (Score: **{latest['anomaly_score']:.2f}**).\n\n"
                    f"**Why?** {latest['reason']}\n\n"
                    f"ℹ️ *Note: An anomaly flag indicates statistical variation from your typical baseline, not fraud.*"
                )
            else:
                text = (
                    f"✅ **No Unusual Activity Detected:**\n\n"
                    f"None of your recent transactions deviate significantly from your historical spending benchmarks."
                )
            return {
                "question": question,
                "answer": text,
                "source": "Deterministic ML Analytics (Offline)",
                "ai_powered": False,
                "online": False,
                "intent": intent,
                "suggested_actions": [{"type": "NAVIGATE_HISTORY", "label": "View History"}]
            }

        elif intent == "BUDGET_OVERRUN":
            funds = facts['purpose_funds']
            overruns = [f for f in funds if f['potential_overrun'] > 0]
            if overruns:
                lines = [
                    f"• **{f['name']} ({f['category']}):** Predicted spend ৳{f['predicted_month_end_spend']:,.2f} "
                    f"vs budget ৳{f['allocated_budget']:,.2f} (Potential overrun: **৳{f['potential_overrun']:,.2f}**)"
                    for f in overruns
                ]
                text = (
                    f"⚠️ **Purpose Fund Budget Forecast Alert:**\n\n"
                    f"The machine learning forecaster predicts potential overruns in {len(overruns)} fund(s):\n" +
                    "\n".join(lines) +
                    f"\n\n**Recommendation:** Review allocations or rebalance from surplus funds."
                )
            else:
                text = (
                    f"✅ **All Purpose Funds On Track:**\n\n"
                    f"The ML forecasting model projects that all {len(funds)} active funds will remain within their allocated monthly budgets."
                )
            return {
                "question": question,
                "answer": text,
                "source": "Deterministic ML Forecasting (Offline)",
                "ai_powered": False,
                "online": False,
                "intent": intent,
                "suggested_actions": [{"type": "NAVIGATE_FUNDS", "label": "Review Funds"}]
            }

        elif intent == "RECOMMENDATIONS":
            recs = RecommendationEngine.generate_recommendations(user)
            if recs:
                rec_lines = [f"• **{r['title']}:** {r['message']}" for r in recs[:3]]
                text = "💡 **Grounded Financial Recommendations:**\n\n" + "\n\n".join(rec_lines)
            else:
                text = "💡 **Recommendations:** Your spending and budget allocations are well-aligned. Continue your current savings discipline."
            return {
                "question": question,
                "answer": text,
                "source": "Deterministic Recommendation Engine",
                "ai_powered": False,
                "online": False,
                "intent": intent,
                "suggested_actions": [{"type": "NAVIGATE_FUNDS", "label": "Manage Funds"}]
            }

        elif intent == "FAMILYPASS":
            issued = facts['family_passes_issued']
            received = facts['family_passes_received']
            lines = []
            for fp in issued:
                lines.append(f"• **Issued to {fp['member_name']} ({fp['purpose']}):** Limit ৳{fp['limit_amount']:,.2f}, Used ৳{fp['used_amount']:,.2f}, Remaining: **৳{fp['remaining_limit']:,.2f}**")
            for fp in received:
                lines.append(f"• **Received from {fp['owner_name']} ({fp['purpose']}):** Remaining quota: **৳{fp['remaining_limit']:,.2f}**")

            summary = "\n".join(lines) if lines else "No active FamilyPass delegations found."
            text = f"👥 **FamilyPass Status Overview:**\n\n{summary}"
            return {
                "question": question,
                "answer": text,
                "source": "Deterministic FamilyPass Ledger",
                "ai_powered": False,
                "online": False,
                "intent": intent,
                "suggested_actions": [{"type": "NAVIGATE_FAMILYPASS", "label": "FamilyPass Dashboard"}]
            }

        elif intent == "SPENDING_SUMMARY" or intent == "CATEGORY_SPENDING":
            total_spent = mo['total_spent']
            txns_count = mo['total_transactions']
            by_cat = mo['by_category']
            cat_lines = "\n".join([f"  • **{cat}:** ৳{amt:,.2f}" for cat, amt in by_cat.items()]) if by_cat else "  • No category expenses recorded."

            text = (
                f"📊 **Monthly Spending Overview:**\n\n"
                f"• **Total Spent This Month:** **৳{total_spent:,.2f}** across {txns_count} completed transactions.\n"
                f"• **Current Normal Wallet Balance:** **৳{wallet_bal:,.2f}**\n\n"
                f"**Category Breakdown:**\n{cat_lines}"
            )
            return {
                "question": question,
                "answer": text,
                "source": "Deterministic Financial Engine",
                "ai_powered": False,
                "online": False,
                "intent": intent,
                "suggested_actions": [{"type": "NAVIGATE_HISTORY", "label": "View History"}]
            }

        else:
            funds_cnt = len(facts['purpose_funds'])
            text = (
                f"📑 **Executive Financial Health Summary:**\n\n"
                f"• Available Normal Wallet: **৳{wallet_bal:,.2f}**\n"
                f"• This Month's Income: **৳{mo['total_income']:,.2f}** | Total Spent: **৳{mo['total_spent']:,.2f}**\n"
                f"• Net Savings: **৳{mo['net_savings']:,.2f}** (Savings Rate: **{mo['savings_rate_pct']}%**)\n"
                f"• Active Purpose Funds: **{funds_cnt} categories**\n\n"
                f"Ask me specific questions about your **fund risks, forecasts, anomalies, or spending trends**!"
            )
            return {
                "question": question,
                "answer": text,
                "source": "Deterministic Financial Engine",
                "ai_powered": False,
                "online": False,
                "intent": intent,
                "suggested_actions": []
            }

    @classmethod
    def _suggest_actions_for_intent(cls, intent: str, facts: dict) -> list:
        if intent in ["BUDGET_OVERRUN", "RECOMMENDATIONS"]:
            return [{"type": "NAVIGATE_FUNDS", "label": "Manage Funds"}]
        elif intent == "FAMILYPASS":
            return [{"type": "NAVIGATE_FAMILYPASS", "label": "FamilyPass"}]
        elif intent in ["ANOMALY", "SPENDING_SUMMARY"]:
            return [{"type": "NAVIGATE_HISTORY", "label": "Transactions"}]
        return []

    @classmethod
    def answer_query(cls, user, question: str, lang: str = "en") -> Dict[str, Any]:
        """
        Main query entry point:
        1. Checks exact predefined product demo QA first
        2. Gathers ground-truth user financial facts
        3. Detects intent (Action Refusal vs Anomaly vs Budget vs General)
        4. Attempts Online Gemini Generation (with timeout)
        5. Falls back seamlessly to Deterministic Offline Analytics if offline or on error
        """
        # Exact predefined demo QA bypasses online LLM and ledger
        entry = find_demo_answer(question)
        if entry:
            return demo_response(question, entry)

        facts = cls.get_user_financial_context(user)
        intent = cls.detect_intent(question)

        # Immediate refusal of any autonomous financial action
        if intent == "ACTION_REQUEST":
            return cls._handle_action_refusal(question, lang)

        # Attempt Online Gemini call first
        online_response = cls.generate_online_response(user, question, intent, facts, lang)
        if online_response:
            return online_response

        # Fallback to Deterministic Offline Analytics
        fallback_res = cls.deterministic_offline_analysis(user, question, intent, facts, lang)
        fallback_res['fallback'] = True
        fallback_res['notice'] = 'Gemini is unavailable. Demo answers and local financial insights are still available.'
        return fallback_res


# Backward-compatible alias
AICoach = FinancialAIService
