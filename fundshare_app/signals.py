from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from fundshare_app.models import Transaction, AnomalyResult


@receiver(post_save, sender=Transaction, dispatch_uid='fundshare_transaction_anomaly')
def score_transaction(sender, instance, created, raw, **kwargs):
    if created and not raw:
        from fundshare_app.ml.anomaly_detector import AnomalyDetector
        transaction.on_commit(lambda: AnomalyDetector.record_transaction(instance.pk), robust=True)


@receiver(post_save, sender=AnomalyResult, dispatch_uid='fundshare_anomaly_fraud_incident')
def trigger_fraud_incident_on_anomaly(sender, instance, created, raw, **kwargs):
    if not raw:
        from fundshare_app.models import FraudIncident
        FraudIncident.auto_create_from_evaluation(
            transaction=instance.transaction,
            anomaly_result=instance
        )
