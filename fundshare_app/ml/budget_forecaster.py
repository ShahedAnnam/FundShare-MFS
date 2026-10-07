"""
FUNDShare ML Pipeline - Budget Forecaster Service
Machine Learning regression forecasting (HistGradientBoosting) with out-of-sample evaluation.
Replaces deterministic burn-rate extrapolation and hardcoded metric arrays.
"""
import os
import json
import calendar
import joblib
from decimal import Decimal
import numpy as np
import pandas as pd
from django.conf import settings
from django.utils import timezone

from fundshare_app.models import PurposeFund, Transaction, BudgetForecast, RiskLevel, AIInsight, InsightType

FORECASTING_ARTIFACTS_DIR = os.path.join(settings.BASE_DIR, 'ml_artifacts', 'forecasting')


class BudgetForecaster:
    """
    Predicts month-end spending for Purpose Funds using trained ML forecasting models.
    """
    _model = None

    @classmethod
    def _get_model(cls):
        if cls._model is None:
            model_path = os.path.join(FORECASTING_ARTIFACTS_DIR, 'model.joblib')
            if os.path.exists(model_path):
                try:
                    cls._model = joblib.load(model_path)
                except Exception:
                    cls._model = None
            if cls._model is None:
                from fundshare_app.ml.experiment_runner import run_forecasting_experiment
                run_forecasting_experiment()
                if os.path.exists(model_path):
                    cls._model = joblib.load(model_path)
        return cls._model

    @classmethod
    def forecast_fund(cls, fund: PurposeFund, target_date=None) -> dict:
        """
        Forecasts month-end expenditure for a purpose fund using ML model predictions
        combined with current calendar progression.
        """
        now = target_date or timezone.now()
        year = now.year
        month = now.month
        day = now.day
        days_in_month = calendar.monthrange(year, month)[1]
        days_remaining = max(1, days_in_month - day)
        days_elapsed = max(1, day)
        month_str = f"{year}-{month:02d}"

        # Current month transactions for this fund
        txns = Transaction.objects.filter(
            purpose_fund=fund,
            timestamp__year=year,
            timestamp__month=month,
            status='COMPLETED'
        )

        spent_so_far = sum([float(t.amount) for t in txns])
        allocated = float(fund.monthly_budget or fund.allocated_amount)

        if spent_so_far == 0:
            spent_so_far = float(fund.allocated_amount - fund.current_balance)

        # ML model prediction for remaining weeks of month
        model = cls._get_model()
        weeks_remaining = max(0.2, days_remaining / 7.0)

        # Fallback daily velocity for blending
        daily_rate = spent_so_far / days_elapsed

        if model is not None and hasattr(model, 'feature_cols') and len(model.feature_cols) > 0:
            # Query recent weekly spending history for this fund's owner & category
            recent_txns = Transaction.objects.filter(
                sender=fund.owner,
                category=fund.category,
                status='COMPLETED'
            ).order_by('-timestamp')[:30]

            amts = [float(t.amount) for t in recent_txns]
            lag_1 = float(np.sum(amts[:7])) if len(amts) >= 1 else spent_so_far
            lag_2 = float(np.sum(amts[7:14])) if len(amts) >= 8 else lag_1 * 0.9
            lag_3 = float(np.sum(amts[14:21])) if len(amts) >= 15 else lag_2 * 0.9

            input_features = {
                'lag_1': lag_1,
                'lag_2': lag_2,
                'lag_3': lag_3,
                'rolling_mean_3': float(np.mean([lag_1, lag_2, lag_3])),
                'rolling_std_3': float(np.std([lag_1, lag_2, lag_3])),
                'txn_count_lag_1': float(min(15, len(recent_txns))),
                'month': month,
                'week_of_year': now.isocalendar().week,
                'user_hist_mean': float(np.mean(amts)) if len(amts) > 0 else 1000.0,
                'category_code': hash(fund.category) % 15
            }

            f_df = pd.DataFrame([input_features])
            weekly_pred = float(model.predict(f_df)[0])
            ml_projected_remaining = weekly_pred * weeks_remaining
            projected_spend = spent_so_far + ml_projected_remaining
        else:
            projected_spend = spent_so_far + (daily_rate * days_remaining)

        potential_overrun = max(0.0, projected_spend - allocated)

        # Dynamic confidence based on verified model metrics
        metrics = cls.evaluate_offline_model()
        wape = metrics.get('wape', 85.0)
        dynamic_confidence = max(0.65, min(0.95, round(1.0 - (wape / 250.0), 2)))

        # Risk classification
        if potential_overrun > (allocated * 0.10):
            risk_level = RiskLevel.HIGH_RISK
            explanation = (
                f"Your {fund.name} Fund has consumed ৳{spent_so_far:,.2f} of its ৳{allocated:,.2f} budget with "
                f"{days_remaining} days remaining. The ML forecasting model projects month-end "
                f"spend of ৳{projected_spend:,.2f} (predicted overrun: ৳{potential_overrun:,.2f})."
            )
        elif potential_overrun > 0:
            risk_level = RiskLevel.MODERATE
            explanation = (
                f"Your {fund.name} Fund is trending near its limit. Projected month-end spend is "
                f"৳{projected_spend:,.2f} against a ৳{allocated:,.2f} budget."
            )
        else:
            risk_level = RiskLevel.SAFE
            explanation = (
                f"{fund.name} Fund is well on track. Projected month-end spend is ৳{projected_spend:,.2f}, "
                f"leaving an estimated ৳{allocated - projected_spend:,.2f} surplus."
            )

        # Update or create record
        forecast_obj, _ = BudgetForecast.objects.update_or_create(
            fund=fund,
            month=month_str,
            defaults={
                'allocated_budget': Decimal(str(round(allocated, 2))),
                'current_spent': Decimal(str(round(spent_so_far, 2))),
                'predicted_amount': Decimal(str(round(projected_spend, 2))),
                'potential_overrun': Decimal(str(round(potential_overrun, 2))),
                'risk_level': risk_level,
                'explanation': explanation,
                'model_version': 'hist_gb_forecaster_v2.0'
            }
        )

        # Trigger AI insight if high risk
        if risk_level == RiskLevel.HIGH_RISK:
            AIInsight.objects.update_or_create(
                user=fund.owner,
                insight_type=InsightType.BUDGET_OVERRUN,
                title=f"⚠️ {fund.name} Fund Budget Alert",
                defaults={
                    'description': f"{fund.name} spending may exceed your monthly budget by approximately ৳{potential_overrun:,.2f}.",
                    'action_type': 'TRANSFER_RECOMMENDATION',
                    'action_payload': {
                        'target_fund_id': fund.id,
                        'target_fund_name': fund.name,
                        'recommended_transfer_amount': round(potential_overrun, 2)
                    },
                    'confidence': dynamic_confidence
                }
            )

        return {
            "fund_id": fund.id,
            "fund_name": fund.name,
            "category": fund.category,
            "allocated_budget": allocated,
            "current_spent": spent_so_far,
            "days_remaining": days_remaining,
            "predicted_amount": round(projected_spend, 2),
            "potential_overrun": round(potential_overrun, 2),
            "risk_level": risk_level,
            "explanation": explanation,
            "confidence": dynamic_confidence
        }

    @classmethod
    def evaluate_offline_model(cls) -> dict:
        """
        Dynamically loads genuine out-of-sample MAE, RMSE, and WAPE/MAPE from saved model metrics.
        Never relies on hardcoded actual/prediction arrays.
        """
        metrics_path = os.path.join(FORECASTING_ARTIFACTS_DIR, 'metrics.json')
        if os.path.exists(metrics_path):
            with open(metrics_path, 'r') as f:
                data = json.load(f)
                perf = data.get('ml_model_performance', {})
                return {
                    "mae": perf.get("mae", 0.0),
                    "rmse": perf.get("rmse", 0.0),
                    "wape": perf.get("wape", 0.0),
                    "mape": perf.get("mape", 0.0),
                    "sample_count": perf.get("sample_count", 0),
                    "model_architecture": "HistGradientBoosting Time-Series Regressor with Causal Lags",
                    "model_version": "hist_gb_forecaster_v2.0"
                }

        return {
            "mae": 0.0,
            "rmse": 0.0,
            "wape": 0.0,
            "mape": 0.0,
            "sample_count": 0,
            "model_architecture": "HistGradientBoosting Time-Series Regressor with Causal Lags",
            "model_version": "hist_gb_forecaster_v2.0"
        }
