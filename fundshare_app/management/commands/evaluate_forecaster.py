"""
Management command: evaluate_forecaster
Outputs comprehensive out-of-sample forecasting evaluation metrics, baselines, and ablation study.
"""
import os
import json
from django.conf import settings
from django.core.management.base import BaseCommand
from fundshare_app.ml.experiment_runner import run_forecasting_experiment

FORECASTING_METRICS_PATH = os.path.join(settings.BASE_DIR, 'ml_artifacts', 'forecasting', 'metrics.json')


class Command(BaseCommand):
    help = "Displays rigorous out-of-sample evaluation metrics, baselines, and ablation study for Budget Forecasting."

    def add_arguments(self, parser):
        parser.add_argument('--re-run', action='store_true', help="Re-run forecasting evaluation.")

    def handle(self, *args, **options):
        if options['re_run'] or not os.path.exists(FORECASTING_METRICS_PATH):
            self.stdout.write("Running forecasting evaluation pipeline...")
            data = run_forecasting_experiment()
        else:
            with open(FORECASTING_METRICS_PATH, 'r') as f:
                data = json.load(f)

        perf = data['ml_model_performance']
        b1 = data['baselines']['last_value_baseline']
        b2 = data['baselines']['moving_average_baseline']
        samples = data['samples']

        self.stdout.write(self.style.MIGRATE_HEADING("\n" + "=" * 65))
        self.stdout.write(self.style.MIGRATE_HEADING("FUNDShare Budget Forecasting Evaluation Report"))
        self.stdout.write(self.style.MIGRATE_HEADING("=" * 65))

        self.stdout.write(f"\n[DATA SPLITS]")
        self.stdout.write(f"  • Aggregation Level:  {data['aggregation_level']}")
        self.stdout.write(f"  • Train Split:        {samples['train']} samples ({data['train_period']})")
        self.stdout.write(f"  • Validation Split:   {samples['validation']} samples ({data['validation_period']})")
        self.stdout.write(f"  • Test Split:         {samples['test']} samples ({data['test_period']})")

        self.stdout.write(f"\n[MODEL VS BASELINES ON UNTOUCHED TEST SPLIT]")
        self.stdout.write(f"{'Model / Approach':<32} | {'MAE (৳)':<10} | {'RMSE (৳)':<10} | {'WAPE (%)':<10} | {'MAPE (%)':<10}")
        self.stdout.write("-" * 82)
        self.stdout.write(f"{'Baseline 1 (Last Value)':<32} | {b1['mae']:<10.2f} | {b1['rmse']:<10.2f} | {b1['wape']:<10.2f} | {b1['mape']:<10.2f}")
        self.stdout.write(f"{'Baseline 2 (Moving Average)':<32} | {b2['mae']:<10.2f} | {b2['rmse']:<10.2f} | {b2['wape']:<10.2f} | {b2['mape']:<10.2f}")
        self.stdout.write(f"{'HistGradientBoosting (Ours)':<32} | {perf['mae']:<10.2f} | {perf['rmse']:<10.2f} | {perf['wape']:<10.2f} | {perf['mape']:<10.2f}")

        self.stdout.write(f"\n[CONTROLLED ABLATION STUDY]")
        self.stdout.write(f"{'Experiment':<36} | {'MAE (৳)':<10} | {'RMSE (৳)':<10} | {'WAPE (%)':<10} | {'MAPE (%)':<10}")
        self.stdout.write("-" * 86)
        for k, v in data.get('ablation_study', {}).items():
            self.stdout.write(f"{v['label']:<36} | {v['mae']:<10.2f} | {v['rmse']:<10.2f} | {v['wape']:<10.2f} | {v['mape']:<10.2f}")
        self.stdout.write("\n")
