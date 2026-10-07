# Transaction anomaly model

The repository CSV contains 480 transactions (402 Normal, 78 Anomaly), all merchant
payments. It is not evidence of production fraud-detection performance.

## Reproduce

```powershell
$env:DEBUG='True'
.venv/Scripts/python.exe manage.py migrate
.venv/Scripts/python.exe manage.py train_anomaly_model --backfill
```

Install `requirements.txt` first. Training saves `artifacts/anomaly.joblib` and an
evaluation manifest. Deploy this trusted artifact outside static/media directories.
Never load an uploaded or untrusted joblib/pickle file. Retrain after changing the
feature schema or scikit-learn version; restart backend workers after retraining.

Training is unsupervised Isolation Forest (300 trees, seed 42, fixed contamination
0.15). The earlier 336 rows train the model; the later 144 rows evaluate it. The
vectorizer is fitted only on training data. Labels, anomaly types and account/
transaction/merchant IDs are excluded from inputs. Labels are not training targets
and do not determine the threshold. Precomputed historical features are assumed
to be prior-only as provided by the dataset; their provenance is not independently
validated. No hyperparameter selection is performed on the test labels.

The binary result is stored in the one-to-one `AnomalyResult.is_anomaly` field;
`prediction` exposes the same stored value as integer 0/1. Severity is the percentile
of the negative Isolation Forest score against training scores, NOT a calibrated
probability or confidence. Raw and decision scores, causal input features, model
version and out-of-domain warnings are retained for administrator review.

New ORM-created transactions are scored after commit across all transaction types,
including failed/rejected attempts. The model never rejects payments, moves money
or changes permissions. Runtime history contains only earlier completed sender
transactions; timestamp ties use primary-key order. Hours use Asia/Dhaka local time.
Results for unseen categories/sources or non-merchant transactions are explicitly
marked outside the evaluated domain. Cold-start behavior needs further validation.

If inference fails, settlement remains intact. An unscored row is NOT Normal.
Recover the artifact and run `manage.py backfill_anomaly_predictions` to retry missing
or old-version results. Use `--force` to rescore all entries. Bulk-created/imported
records bypass Django save signals and require this backfill command.

## Access

ADMIN: **More > AI / ML Transaction Report**. API:
`GET /api/admin/ml/transactions/?prediction=1&page=1`.
Filters: `prediction` (`0`, `1`, `unscored`), transaction `type`, transaction-ID
`search`. Page size is 20. Evaluation metrics remain at `/api/evaluation/metrics/`.
Both APIs and the ML intelligence dashboard enforce active ADMIN authorization.
Public transaction serializers, replay responses, reports, notifications and chat
context exclude anomaly classifications. Ordinary personal budgeting stays available.

The saved evaluation manifest includes Precision, Recall, F1, ROC-AUC, a confusion
matrix with rows actual 0/1 and columns predicted 0/1, dataset SHA-256, time boundaries,
library version and limitations. Zero scores are kept as zero; undefined ROC-AUC is
`null`, never a fabricated fallback.
