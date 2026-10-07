"""
Management command: run_anomaly_detection
Executes real ML inference across transactions using trained Isolation Forest.
Populates AnomalyResult ONLY with genuine model outputs (never synthetic labels).
"""
from django.core.management.base import BaseCommand
from fundshare_app.models import Transaction, AnomalyResult
from fundshare_app.ml.anomaly_detector import AnomalyDetector


class Command(BaseCommand):
    help = "Runs genuine ML inference across transactions and writes outputs to AnomalyResult."

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=None, help="Limit number of transactions to analyze.")
        parser.add_argument('--re-analyze-all', action='store_true', help="Re-analyze all transactions instead of only unanalyzed.")

    def handle(self, *args, **options):
        detector = AnomalyDetector.get_instance()
        if not detector.is_fitted:
            self.stdout.write("Training anomaly model first...")
            detector.train_and_evaluate()

        re_analyze = options['re_analyze_all']
        limit = options['limit']

        if re_analyze:
            AnomalyResult.objects.all().delete()

        qs = Transaction.objects.all().order_by('timestamp')
        if not re_analyze:
            existing_txn_ids = set(AnomalyResult.objects.values_list('transaction_id', flat=True))
            qs = qs.exclude(id__in=existing_txn_ids)

        if limit:
            qs = qs[:limit]

        total = qs.count()
        self.stdout.write(f"Running ML anomaly inference on {total} transactions...")

        created_count = 0
        flagged_count = 0
        batch = []

        for txn in qs:
            analysis = detector.analyze_transaction(txn)
            is_anom = bool(analysis.get('ml_is_anomaly', analysis['is_anomaly']))
            if is_anom:
                flagged_count += 1

            batch.append(AnomalyResult(
                transaction=txn,
                user=txn.sender,
                is_anomaly=is_anom,
                anomaly_score=analysis['anomaly_score'],
                reason=analysis['reason'],
                features_summary=analysis['features_summary'],
                model_version=analysis['model_version']
            ))

            if len(batch) >= 500:
                AnomalyResult.objects.bulk_create(batch)
                created_count += len(batch)
                batch = []

        if batch:
            AnomalyResult.objects.bulk_create(batch)
            created_count += len(batch)

        self.stdout.write(self.style.SUCCESS(
            f"Successfully processed {created_count} transactions with ML model. "
            f"Flagged {flagged_count} spending anomalies (Prevalence: {flagged_count/max(1, created_count)*100:.2f}%)."
        ))
        self.stdout.write("Note: AnomalyResult contains 100% genuine model outputs. Ground-truth labels remain distinct.")
