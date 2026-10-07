from django.core.management.base import BaseCommand, CommandError
from fundshare_app.ml.anomaly_detector import AnomalyDetector
from fundshare_app.models import Transaction


class Command(BaseCommand):
    help = 'Score missing/old-version ledger entries without changing financial state.'

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true')

    def handle(self, *args, **options):
        if not AnomalyDetector.get_instance().evaluation_metrics.get('available'):
            raise CommandError('Train the model before backfilling predictions.')
        completed = failed = 0
        for pk in Transaction.objects.order_by('timestamp', 'pk').values_list('pk', flat=True).iterator(chunk_size=100):
            if AnomalyDetector.record_transaction(pk, force=options['force']):
                completed += 1
            else:
                failed += 1
        self.stdout.write(f'Predictions ready: {completed}; unavailable: {failed}')
        if failed:
            raise CommandError('Some predictions failed; investigate logs and retry backfill.')
