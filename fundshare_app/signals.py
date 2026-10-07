from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from fundshare_app.models import Transaction


@receiver(post_save, sender=Transaction, dispatch_uid='fundshare_transaction_anomaly')
def score_transaction(sender, instance, created, raw, **kwargs):
    if created and not raw:
        from fundshare_app.ml.anomaly_detector import AnomalyDetector
        transaction.on_commit(lambda: AnomalyDetector.record_transaction(instance.pk), robust=True)
