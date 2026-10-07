from django.core.management.base import BaseCommand, CommandError
from fundshare_app.ml.anomaly_detector import AnomalyDetector, DATASET, ARTIFACT


class Command(BaseCommand):
    help = 'Train the repository dataset, evaluate held-out labels, save the private model artifact.'

    def add_arguments(self, parser):
        parser.add_argument('--backfill', action='store_true')

    def handle(self, *args, **options):
        try:
            metrics = AnomalyDetector.train(DATASET, ARTIFACT)
        except (ValueError, OSError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"Saved {metrics['model_version']}: train={metrics['train_size']}, test={metrics['test_size']}")
        for key in ('precision', 'recall', 'f1', 'roc_auc'):
            self.stdout.write(f'{key}: {metrics[key]}')
        if options['backfill']:
            from django.core.management import call_command
            call_command('backfill_anomaly_predictions', force=True, stdout=self.stdout)
