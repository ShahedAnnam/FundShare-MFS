"""
Management command: train_anomaly_model
Trains Isolation Forest anomaly detector on historical transactions without leakage.
Supports full validated pipeline (default) or benchmark dataset (--benchmark).
"""
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Trains Isolation Forest on historical transactions without leakage and persists artifacts."

    def add_arguments(self, parser):
        parser.add_argument('--seed', type=int, default=42, help="Random seed for reproducibility.")
        parser.add_argument('--benchmark', action='store_true', help="Train on the 480-row offline benchmark dataset.")
        parser.add_argument('--backfill', action='store_true', help="Backfill anomaly predictions after benchmark training.")

    def handle(self, *args, **options):
        if options.get('benchmark') or options.get('backfill'):
            from fundshare_app.ml.anomaly_detector import AnomalyDetector, DATASET, ARTIFACT
            try:
                metrics = AnomalyDetector.train(DATASET, ARTIFACT)
            except (ValueError, OSError) as exc:
                raise CommandError(str(exc)) from exc
            self.stdout.write(f"Saved {metrics.get('model_version')}: train={metrics.get('train_size')}, test={metrics.get('test_size')}")
            for key in ('precision', 'recall', 'f1', 'roc_auc'):
                self.stdout.write(f'{key}: {metrics.get(key)}')
            if options.get('backfill'):
                from django.core.management import call_command
                call_command('backfill_anomaly_predictions', force=True, stdout=self.stdout)
            return

        from fundshare_app.ml.experiment_runner import run_anomaly_experiment
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

