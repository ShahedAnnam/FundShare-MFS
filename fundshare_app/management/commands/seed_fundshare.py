from django.core.management.base import BaseCommand
from fundshare_app.ml.data_generator import SyntheticDataGenerator
from fundshare_app.ml.anomaly_detector import AnomalyDetector


class Command(BaseCommand):
    help = 'Seeds synthetic Bangladesh fintech data and trains anomaly models for Hackathon evaluation'

    def add_arguments(self, parser):
        parser.add_argument('--wipe', action='store_true', help='Wipe existing transactions before seeding')

    def handle(self, *args, **options):
        wipe = options.get('wipe', False)
        self.stdout.write(self.style.NOTICE('Generating realistic synthetic data for FUNDShare (upay prototype)...'))
        stats = SyntheticDataGenerator.populate_database(wipe_existing=wipe)
        self.stdout.write(self.style.SUCCESS(f'Synthetic data created: {stats}'))

        self.stdout.write(self.style.NOTICE('Training Isolation Forest Anomaly Detection and computing metrics...'))
        detector = AnomalyDetector.get_instance()
        metrics = detector.train_and_evaluate()
        self.stdout.write(self.style.SUCCESS(f'Model validation metrics: {metrics}'))
        self.stdout.write(self.style.SUCCESS('FUNDShare is ready for demo!'))
