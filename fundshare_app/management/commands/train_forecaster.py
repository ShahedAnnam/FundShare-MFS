"""
Management command: train_forecaster
Trains HistGradientBoostingRegressor time-series model on historical spending panel,
evaluates out-of-sample against baselines, and persists artifacts.
"""
from django.core.management.base import BaseCommand
from fundshare_app.ml.experiment_runner import run_forecasting_experiment


class Command(BaseCommand):
    help = "Trains ML spending forecaster on causal panel data without leakage."

    def add_arguments(self, parser):
        parser.add_argument('--seed', type=int, default=42, help="Random seed for reproducibility.")

    def handle(self, *args, **options):
        seed = options['seed']
        self.stdout.write(f"Initiating leakage-safe ML forecaster training (random_seed={seed})...")

        res = run_forecasting_experiment(random_seed=seed)
        samples = res['samples']
        perf = res['ml_model_performance']

        self.stdout.write(self.style.SUCCESS("Forecasting model training completed successfully!"))
        self.stdout.write(f"  • Aggregation: {res['aggregation_level']}")
        self.stdout.write(f"  • Samples: Train={samples['train']}, Val={samples['validation']}, Test={samples['test']}")
        self.stdout.write(f"  • Test MAE:   ৳{perf['mae']:,.2f}")
        self.stdout.write(f"  • Test RMSE:  ৳{perf['rmse']:,.2f}")
        self.stdout.write(f"  • Test WAPE:  {perf['wape']:.2f}%")
        self.stdout.write(f"  • Test MAPE:  {perf['mape']:.2f}% (non-zero subset)")
        self.stdout.write("Artifacts saved to: ml_artifacts/forecasting/")
