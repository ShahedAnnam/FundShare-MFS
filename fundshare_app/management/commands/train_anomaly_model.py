"""
Management command: train_anomaly_model
Trains Isolation Forest anomaly detector on chronological training split,
calibrates on validation split, evaluates on test split, and persists artifacts.
"""
from django.core.management.base import BaseCommand
from fundshare_app.ml.experiment_runner import run_anomaly_experiment


class Command(BaseCommand):
    help = "Trains Isolation Forest on historical transactions without leakage and persists artifacts."

    def add_arguments(self, parser):
        parser.add_argument('--seed', type=int, default=42, help="Random seed for reproducibility.")

    def handle(self, *args, **options):
        seed = options['seed']
        self.stdout.write(f"Initiating leakage-safe anomaly model training (random_seed={seed})...")

        res = run_anomaly_experiment(random_seed=seed)
        samples = res['samples']
        perf = res['model_performance']

        self.stdout.write(self.style.SUCCESS(f"Training completed successfully!"))
        self.stdout.write(f"  • Total samples: {samples['total']} (Train: {samples['train']}, Val: {samples['validation']}, Test: {samples['test']})")
        self.stdout.write(f"  • Test Precision: {perf['precision']:.4f}")
        self.stdout.write(f"  • Test Recall:    {perf['recall']:.4f}")
        self.stdout.write(f"  • Test F1 Score:  {perf['f1']:.4f}")
        self.stdout.write(f"  • Test ROC-AUC:   {perf['roc_auc']:.4f}")
        self.stdout.write(f"  • Test PR-AUC:    {perf['pr_auc']:.4f}")
        self.stdout.write(f"  • Calibrated Threshold: {res['calibrated_threshold']}")
        self.stdout.write(f"Artifacts saved to: ml_artifacts/anomaly/")
