"""
Management command: evaluate_anomaly_model
Outputs comprehensive out-of-sample evaluation metrics, baselines, and ablation study.
"""
import os
import json
from django.conf import settings
from django.core.management.base import BaseCommand
from fundshare_app.ml.experiment_runner import run_anomaly_experiment

ANOMALY_METRICS_PATH = os.path.join(settings.BASE_DIR, 'ml_artifacts', 'anomaly', 'metrics.json')


class Command(BaseCommand):
    help = "Displays rigorous out-of-sample evaluation metrics, baselines, and ablation study for Anomaly Detection."

    def add_arguments(self, parser):
        parser.add_argument('--re-run', action='store_true', help="Re-run evaluation from database.")

    def handle(self, *args, **options):
        if options['re_run'] or not os.path.exists(ANOMALY_METRICS_PATH):
            self.stdout.write("Running evaluation pipeline...")
            data = run_anomaly_experiment()
        else:
            with open(ANOMALY_METRICS_PATH, 'r') as f:
                data = json.load(f)

        perf = data['model_performance']
        b1 = data['baselines']['amount_percentile_baseline']
        b2 = data['baselines']['statistical_deviation_baseline']
        samples = data['samples']
        anoms = data['anomalies']

        self.stdout.write(self.style.MIGRATE_HEADING("\n" + "=" * 65))
        self.stdout.write(self.style.MIGRATE_HEADING("FUNDShare Anomaly Detection Evaluation Report"))
        self.stdout.write(self.style.MIGRATE_HEADING("=" * 65))

        self.stdout.write(f"\n[DATA SPLITS]")
        self.stdout.write(f"  • Total Transactions: {samples['total']}")
        self.stdout.write(f"  • Train Split:        {samples['train']} samples ({anoms['train']} anomalies, {anoms['train']/samples['train']*100:.2f}%)")
        self.stdout.write(f"  • Validation Split:   {samples['validation']} samples ({anoms['validation']} anomalies, {anoms['validation']/samples['validation']*100:.2f}%)")
        self.stdout.write(f"  • Test Split:         {samples['test']} samples ({anoms['test']} anomalies, {anoms['test']/samples['test']*100:.2f}%)")
        self.stdout.write(f"  • Test Time Range:    {data['test_period']}")

        self.stdout.write(f"\n[MODEL VS BASELINES ON UNTOUCHED TEST SPLIT]")
        self.stdout.write(f"{'Model / Approach':<30} | {'Prec':<7} | {'Rec':<7} | {'F1':<7} | {'ROC-AUC':<7} | {'PR-AUC':<7}")
        self.stdout.write("-" * 75)
        self.stdout.write(f"{'Baseline 1 (Amount Percentile)':<30} | {b1['precision']:<7.4f} | {b1['recall']:<7.4f} | {b1['f1']:<7.4f} | {b1['roc_auc']:<7.4f} | {b1['pr_auc']:<7.4f}")
        self.stdout.write(f"{'Baseline 2 (Statistical 3σ)':<30} | {b2['precision']:<7.4f} | {b2['recall']:<7.4f} | {b2['f1']:<7.4f} | {b2['roc_auc']:<7.4f} | {b2['pr_auc']:<7.4f}")
        self.stdout.write(f"{'Isolation Forest (Ours)':<30} | {perf['precision']:<7.4f} | {perf['recall']:<7.4f} | {perf['f1']:<7.4f} | {perf['roc_auc']:<7.4f} | {perf['pr_auc']:<7.4f}")

        self.stdout.write(f"\n[CONFUSION MATRIX (Test)]")
        cm = perf['confusion_matrix']
        self.stdout.write(f"  • TN: {cm[0][0]}, FP: {cm[0][1]}")
        self.stdout.write(f"  • FN: {cm[1][0]}, TP: {cm[1][1]}")

        self.stdout.write(f"\n[CONTROLLED ABLATION STUDY]")
        self.stdout.write(f"{'Experiment':<32} | {'Prec':<7} | {'Rec':<7} | {'F1':<7} | {'ROC-AUC':<7} | {'PR-AUC':<7}")
        self.stdout.write("-" * 77)
        for k, v in data.get('ablation_study', {}).items():
            self.stdout.write(f"{v['label']:<32} | {v['precision']:<7.4f} | {v['recall']:<7.4f} | {v['f1']:<7.4f} | {v['roc_auc']:<7.4f} | {v['pr_auc']:<7.4f}")
        self.stdout.write("\n")
