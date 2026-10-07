# FUNDShare

**Your money. Shared purpose.**

FUNDShare is a Bangladesh mobile financial services (MFS) hackathon prototype with an Upay-inspired interface. It combines a wallet, category-restricted Purpose Funds, recipient-assigned Shared Funds, controlled FamilyPass spending, financial reports, a hybrid support chatbot, and administrator-only transaction anomaly reporting.

The central idea is **controlled sharing without sharing account credentials**: customers can budget their own money, delegate a limited allowance, and use allowances received from other customers through the same account.

> This is an independent prototype, not a live Upay integration or a production banking system. Payments update the application's PostgreSQL accounting records; they do not settle external payments, deliver mobile recharge, withdraw cash, or send SMS. Anomaly classifications are review signals, not proof of fraud.

## Contents

- [Features and Roles](#features-and-roles)
- [Screenshots](#screenshots)
- [Architecture and Technology](#architecture-and-technology)
- [Repository Structure](#repository-structure)
- [Run Locally](#run-locally)
- [Configuration](#configuration)
- [Reviewer Walkthrough](#reviewer-walkthrough)
- [Transaction Safety](#transaction-safety)
- [Anomaly Detection and Evaluation](#anomaly-detection-and-evaluation)
- [Hybrid AI Chat](#hybrid-ai-chat)
- [Financial Insights and Forecasting](#financial-insights-and-forecasting)
- [API Reference](#api-reference)
- [Tests and Verification](#tests-and-verification)
- [Legacy Data Import](#legacy-data-import)
- [Deployment and Integrations](#deployment-and-integrations)
- [Troubleshooting and Limitations](#troubleshooting-and-limitations)

## Features and Roles

### Implemented Features

| Feature | Actual behavior |
|---|---|
| Registration and authentication | Register a CUSTOMER account with a unique username and normalized Bangladesh phone number; sign in with username or phone and password. Registration creates a zero-balance wallet and signs the customer in. |
| Wallet | View available balance, allocate money to funds, and use prototype Add Money, Send Money, Mobile Recharge, Pay Bill, and Cash Out flows. Simulated Add Money is development-only. |
| Send Money | Resolve a registered recipient by phone, check balances, confirm the sender's PIN, and update both wallets atomically. Contacts and recipient usernames are not required. |
| Purpose Funds | Create, edit, allocate, transfer between, and close owned funds. Merchant spending requires an active fund, adequate balance, and a matching registered merchant category. Closing refunds the remaining balance; funds with financial history are archived. |
| Shared Funds | Assign an optional registered recipient by phone to an owned Purpose Fund. Assignment remains an owner-managed association; it does not transfer ownership or grant payment permission. |
| FamilyPass | Issue, receive, edit, revoke, and review delegated spending access with limits, dates, permitted actions, purposes, and categories. A customer can issue and receive passes simultaneously. |
| Merchant payments | Pay an active registered merchant from the normal wallet, an eligible owned Purpose Fund, or an eligible received FamilyPass. Optional checkout items preserve quantity, price, discounts, tax, and line totals. |
| History and receipts | Filter the visible ledger and open transaction receipts. FamilyPass owners can review delegated spending and itemized pass activity. |
| Contacts and notifications | Maintain a private optional address book; receive and mark in-app transaction and FamilyPass notifications as read. Contacts do not grant access. |
| Reports and financial insights | Weekly, monthly, and yearly spending summaries, category breakdowns, fund forecasts, budget risk indicators, and advisory allocation/transfer suggestions. |
| AI Chat | Eighteen local demo Q&A entries, Gemini-backed free-form support, and deterministic financial fallback responses. |
| Admin AI/ML report | Paginated transaction details, stored binary predictions, severity scores, model metadata, held-out evaluation results, and unscored/out-of-domain indicators. |
| Evaluation APIs | ADMIN-only model metrics and experiment record endpoints. Seeded experiment comparisons are synthetic examples, not measured participant-study outcomes. |

### Roles and Ownership

| Role | Permissions and boundaries |
|---|---|
| `CUSTOMER` | All normal wallet users have equal standard features. Each controls their own wallet, funds, contacts, and issued passes, and can spend through eligible received passes. No anomaly predictions or ML evaluation access. |
| `MERCHANT` | View the account's linked business dashboard and received payments. Cannot use customer spending/delegation APIs or view anomaly/ML reports. |
| `ADMIN` | Access protected ML reports, evaluation, experiment APIs, and development reset when enabled. Ordinary wallet/fund actions still enforce ownership. FamilyPass creation/use is CUSTOMER-only. |

FamilyPass is **a feature, not a role**. Receiving, spending, revoking, or expiring a pass never changes an account's role. The `member` relationship and some compatibility API names mean "pass recipient," not a separate account type. Active Django superusers retain the application's effective ADMIN behavior; `is_staff` alone does not grant ADMIN access. The Django admin site also requires staff status.

### Important Fund-Sharing Distinction

Purpose Fund recipient assignment and FamilyPass are separate mechanisms. FamilyPass spending debits the **issuer's normal wallet**, not a recipient-assigned Purpose Fund. Granting a pass establishes an allowance; it does not reserve or transfer its limit into a separate balance. The issuer must still have enough wallet money when spending occurs. Recipients use their **own** login and transaction PIN and do not receive the issuer's wallet balance or credentials.

Registered merchant categories are `Grocery`, `Medicine`, `Treatment`, `Education`, `Electricity`, `Restaurant/Food`, `Transport`, `Rent`, `Shopping`, and `Other`. FamilyPass purpose labels map to allowed categories unless explicitly configured otherwise. An empty allowed-category list means unrestricted categories, not unrestricted actions or unlimited spending. Even the `ALL` action option does not enable currently unsupported payment-source combinations.

## Screenshots

These images come from the repository's [images folder](images/). Names, balances, dates, transaction counts, and pass states reflect the capture session, not guaranteed fresh-install values. Review screenshots for personal information before publishing them externally.

| Account | Purpose Funds | FamilyPass |
|---|---|---|
| <img src="images/Screenshot%202026-10-07%20124529.png" alt="Mobile Account view with wallet and Purpose Fund balances" width="240"> | <img src="images/Screenshot%202026-10-07%20124439.png" alt="Mobile Purpose Funds with balances and budget risk indicators" width="240"> | <img src="images/Screenshot%202026-10-07%20124604.png" alt="Mobile FamilyPass view with issued permissions and revocation controls" width="240"> |

**ADMIN model evaluation**

![Admin report showing measured Precision, Recall, F1-score, and ROC-AUC](images/Screenshot%202026-10-07%20124323.png)

**ADMIN transaction predictions**

![Admin transaction report with Normal and Anomaly labels, severity percentiles, filters, and review details](images/Screenshot%202026-10-07%20124228.png)

## Architecture and Technology

The frontend and API are served by the same Django application. There is **no separate Node.js frontend, npm build, or frontend development server** required to run the app.

```text
Browser: Django HTML templates + vanilla JavaScript + CSS + local Lucide icons
    |
    | Same-origin requests, session cookie, CSRF token
    v
Django REST Framework views
    |-- Authentication, role/ownership checks, PIN and idempotency wrapper
    |-- TransactionService: validation, ordered row locks, atomic accounting
    |-- Reports / forecasts / recommendations: read-only financial advice
    |-- AI Chat: local demo Q&A or backend Google Gemini request
    v
PostgreSQL: accounts, balances, funds, passes, ledger, requests, predictions
    |
    | New Transaction saved -> after-commit callback
    v
Causal feature extraction -> saved Isolation Forest -> AnomalyResult
    |
    v
ADMIN-only report API and UI
```

| Component | Implementation |
|---|---|
| Backend | Python, Django 5.2, Django REST Framework; session authentication and CSRF protection |
| Database | PostgreSQL only for runtime and tests; `psycopg[binary]` driver and `dj-database-url` configuration |
| Frontend | Server-rendered shell, vanilla JavaScript, custom CSS, locally vendored Lucide 0.468.0; optional Google-hosted Inter font |
| Anomaly ML | scikit-learn **1.9.1** Isolation Forest, `DictVectorizer`, NumPy, pandas; saved with joblib |
| Support LLM | Google `google-genai` Python SDK; configured model defaults to `gemini-3.1-flash-lite` |
| Environment | `python-dotenv` plus process environment variables; existing process values take precedence over `.env` |
| Throttling cache | In-process local cache for development; shared Redis required when `DEBUG=False` |
| Static/deployment | WhiteNoise; WSGI/ASGI entry points; Gunicorn for Linux/WSL production deployment |

Verified local environment on **2026-10-07**: Windows PowerShell, Python **3.11.9**, Django **5.2.18**, PostgreSQL **17.11**, scikit-learn **1.9.1**, joblib **1.6.0**, pandas **3.0.6**, NumPy **2.4.6**, and google-genai **2.28.0**. Most requirements use version ranges, not a full dependency lock; only the model's scikit-learn version is pinned. See [requirements.txt](requirements.txt).

The main data models are `User`, `Wallet`, `Merchant`, `PurposeFund`, `FundTransfer`, `FamilyPass`, `FamilyPassTransaction`, `Transaction`, `TransactionItem`, `FinancialRequest`, `Contact`, `Notification`, `AnomalyResult`, `BudgetForecast`, `AIInsight`, and `ExperimentRecord`. Money uses database decimal fields; balance, limit, amount, phone uniqueness, and idempotency constraints supplement service-layer checks. Time zone: `Asia/Dhaka`. Currency: BDT.

## Repository Structure

```text
FUNDShare-MFS/
  README.md                         Project guide and setup
  .env.example                      Safe configuration template
  requirements.txt                  Python dependencies
  manage.py                         Django management entry point
  build.sh                          Install, collectstatic, migrate
  fundshare_core/                    Settings, root routes, WSGI/ASGI, test settings
  fundshare_app/
    models.py                       Accounts and financial/audit models
    admin.py, admin_site.py          Restricted Django administration
    forms.py                        Registration validation and atomic signup
    signals.py                      Post-commit transaction anomaly scoring
    views/                          UI, REST endpoints, authorization/idempotency
    serializers/                    API output and public ML-field redaction
    services/                       Transactions, PIN/throttling, reports, contacts, phones
    ml/                             Detector, chat, demo Q&A, support context, forecasting
    migrations/                     Database schema, role/phone normalization, indexes
    management/commands/            Train, backfill, seed, legacy import
    tests.py, test_*.py              Business, security, ML, UI, PostgreSQL tests
  templates/                        Login, signup, dashboard, reusable view sections
  static/                           app.js, UI helpers/styles, ML report UI, local assets
    vendor/                         Pinned Lucide bundle and its license
  model/
    fundshare_anomaly_dataset_480.csv   Training/evaluation input
    fundshare_anomaly_dataset_480.xlsx  Accompanying spreadsheet; trainer uses CSV
    artifacts/anomaly.joblib         Trusted saved model/vectorizer/reference scores
    artifacts/evaluation.json        Evaluation and reproducibility metadata
    README.md                       Detector-specific operational notes
  images/                           Screenshots embedded above
  scripts/local-postgres.ps1         Start/Stop/Status for an already initialized local instance
  Project_Report/                   Historical hackathon narrative; may describe an older version
  .local/                           Ignored local PostgreSQL runtime and private backups
```

## Run Locally

### 1. Prerequisites and Clone

Install Git, **Python 3.11** with pip/venv support, PostgreSQL with the `psql` client, and a modern browser. Python 3.11 is the verified interpreter; the pinned scikit-learn package requires Python 3.11 or later. PostgreSQL 17 is the verified server. Use the [official PostgreSQL downloads](https://www.postgresql.org/download/) for your operating system. Internet access is needed to install dependencies; a Gemini key is **not** required for demo Q&A or local financial analytics.

Replace `REPOSITORY_URL` with this repository's clone URL. Do not include a personal access token in a documented URL.

```text
git clone REPOSITORY_URL FUNDShare-MFS
cd FUNDShare-MFS
```

### 2. Create a Virtual Environment and Install Dependencies

**Windows PowerShell**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if (!(Test-Path .env)) { Copy-Item .env.example .env }
```

If activation is blocked by PowerShell policy, activation is optional: use `.\.venv\Scripts\python.exe` instead of `python` in subsequent commands. Keep existing `.env` files; do not overwrite another developer's secrets.

**Linux / macOS**

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
test -f .env || cp .env.example .env
```

The platform-specific shell commands are provided for portability; the verification environment above was Windows. Gunicorn is not the Windows development server.

### 3. Create a Local PostgreSQL Database

Start your installed PostgreSQL service. Open `psql` as its administrative database user; enter the install-time administrator password when prompted. On Windows, use SQL Shell or the full path to `psql.exe` if it is not on `PATH`.

```text
psql -h 127.0.0.1 -U postgres -d postgres
```

Run these commands **inside psql**, choosing your own application password at the prompt:

```sql
CREATE ROLE fundshare LOGIN;
\password fundshare
CREATE DATABASE fundshare OWNER fundshare;
```

For **local automated tests only**, also allow this development role to create Django's separate test database:

```sql
ALTER ROLE fundshare CREATEDB;
\q
```

Do not use a PostgreSQL superuser as the application's runtime account. Do not grant production accounts `CREATEDB` solely for tests; use a dedicated test role/environment.

The repository's `scripts/local-postgres.ps1` is an alternative **only for an existing portable setup** with `.local/postgresql/pgsql/bin/pg_ctl.exe` and initialized `.local/postgresql/data`. These binaries/data are ignored and are **not installed by cloning the repository**. The script does not download PostgreSQL, initialize a cluster, create a database, or generate credentials.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/local-postgres.ps1 Start
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/local-postgres.ps1 Status
# Stop that portable instance when it is no longer needed:
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/local-postgres.ps1 Stop
```

Do not run a portable instance and an installed service on the same port. Its `Start` action binds to `127.0.0.1:5432`; it is not an automatically starting Windows service.

### 4. Configure the Private Environment

Edit the ignored root `.env` using the template below. Replace placeholders; do not use them as real secrets. `DATABASE_URL` must match the role, password, host, port, and database created above. URL-encode URL-reserved characters in the database password.

```dotenv
DEBUG=True
SECRET_KEY=REPLACE_WITH_YOUR_OWN_RANDOM_SECRET
ALLOWED_HOSTS=localhost,127.0.0.1
DATABASE_URL=postgresql://fundshare:YOUR_URL_ENCODED_DB_PASSWORD@127.0.0.1:5432/fundshare
ENABLE_DEMO_RESET=False
ENABLE_SIMULATED_CASH_IN=True
GEMINI_API_KEY=
GEMINI_MODEL=gemini-3.1-flash-lite
```

Generate a random Django secret locally, then put the generated value into your private environment configuration:

```text
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Keep Gemini blank for local-only support. To enable external answers, follow [Google's Gemini API key instructions](https://ai.google.dev/gemini-api/docs/api-key), create an authorized key in Google AI Studio, and set `GEMINI_API_KEY` in `.env`. Check provider quotas, billing, model access, and data-sharing requirements. Never put a key into JavaScript, a screenshot, a README, or a Git commit. Restart Django after environment changes.

### 5. Apply Migrations and Prepare the Model

From the repository root with the virtual environment active:

```text
python manage.py check
python manage.py migrate
python manage.py train_anomaly_model
```

Training reads the repository CSV and writes the saved artifact and evaluation manifest; it does not train on live wallet data. A valid bundled artifact can be reused instead of retraining, but the command makes a fresh installation reproducible. If this database already contains transactions, run:

```text
python manage.py backfill_anomaly_predictions
```

### 6. Choose Fresh Accounts or Optional Demo Data

**Fresh accounts:** create an administrator with a password you choose:

```text
python manage.py createsuperuser
```

Normal customers register through `/register/` after startup. They begin with zero balance, set their own transaction PIN, and can use development-only Add Money to demonstrate flows.

**Optional seeded demonstration:** only in a disposable, empty development database, and with `DEBUG=True`:

```text
python manage.py seed_fundshare
python manage.py backfill_anomaly_predictions
```

The generator creates demo customers (`shahed`, `rahim`, `karim`, `fatima`), merchant accounts such as `agora_super_shop`, an `admin` reviewer account, funds, passes, historical ledger entries, and illustrative experiment records. It contains known fixed demo credentials in [data_generator.py](fundshare_app/ml/data_generator.py); **do not deploy these accounts to production**. To avoid publishing passwords here, choose new local passwords before signing in:

```text
python manage.py changepassword admin
python manage.py changepassword shahed
python manage.py changepassword rahim
python manage.py changepassword agora_super_shop
```

Set each spending user's separate PIN through **More > Change PIN** using their chosen account password. Freshly seeded accounts have no PIN set by the generator. Existing accounts may already require their current PIN to change it.

**Seeding is not a safe merge/import operation.** Even without `--wipe`, it resets some existing demo-account passwords/balances and may duplicate or conflict with historical identifiers. Never run it on a database containing financial data you need to preserve. `seed_fundshare --wipe` is destructive. Seeding reuses the saved dataset model when available; it does not replace training data with live ledger labels.

### 7. Start the App

```text
python manage.py runserver 127.0.0.1:8000
```

Open **http://127.0.0.1:8000/**. Registration: `/register/`. Login: `/login/`. Django admin: `/admin/`. There is one app server, not separate frontend/backend ports. If port 8000 is occupied, use 8001 and update `CORS_ALLOWED_ORIGINS` and `CSRF_TRUSTED_ORIGINS` in settings if cross-origin/API tooling requires the new origin.

## Configuration

| Setting | Required/default and purpose |
|---|---|
| `SECRET_KEY` | Required. Unique random Django signing secret; never commit its real value. |
| `DATABASE_URL` | Required PostgreSQL URL. SQLite URLs are explicitly rejected for runtime/tests. |
| `DEBUG` | Defaults to false; use the literal `True` locally. Production enables HTTPS/cookie requirements and requires Redis. |
| `ALLOWED_HOSTS` | Comma-separated hosts; development automatically includes localhost and 127.0.0.1. Set the production hostname explicitly. |
| `GEMINI_API_KEY` | Optional backend secret. Blank/missing keys preserve demo Q&A and local analytics. |
| `GEMINI_MODEL` | Optional; defaults to `gemini-3.1-flash-lite`. Select only a model available to your provider account. |
| `ENABLE_SIMULATED_CASH_IN` | Defaults to true in development; always disabled when `DEBUG=False`. |
| `ENABLE_DEMO_RESET` | Defaults to false; effective only in development and still ADMIN-only through the API. |
| `REDIS_URL` | Required when `DEBUG=False`; optional in development. Used for shared login/signup throttling, not a payment queue. |
| `TRUST_PROXY_HTTPS` | Optional false by default. Enable only behind a proxy that strips spoofed forwarding headers and sets the correct HTTPS header. |
| `RENDER_EXTERNAL_HOSTNAME` | Optional hosting-provided hostname; adds that host and HTTPS origin to configured host/CORS/CSRF lists. |

`AUTH_LOCKOUT_SECONDS=60`, `LOGIN_MAX_FAILED_ATTEMPTS=10`, `LOGIN_FAILURE_WINDOW_SECONDS=300`, and `TRANSACTION_PIN_MAX_FAILED_ATTEMPTS=5` are **settings.py constants**, not currently environment-parsed options. Signup allows five attempts per IP per five minutes. Sessions use a 24-hour age refreshed on requests. Changing configuration requires restarting backend processes. Shell/IDE environment variables override `.env` values.

`.gitignore` excludes `.env`, other secret environment files, virtual environments, Python caches, local database data/backups, logs, and collected static files. `.env.example` intentionally remains tracked and must contain placeholders only.

## Reviewer Walkthrough

1. Register two CUSTOMER accounts, choose passwords and transaction PINs, and top up the issuer's wallet using development Add Money. Use seeded merchants or an authorized merchant setup for payments.
2. Create a Grocery Purpose Fund and allocate money. Pay a Grocery merchant from it; try an Education fund at that same merchant to demonstrate deterministic category rejection without losing funds.
3. Assign a recipient to a fund to demonstrate the Shared Fund association. Explain that this does not itself authorize spending.
4. Issue a Grocery FamilyPass to the second customer's registered phone **without saving a Contact**. Sign in as that recipient, select the received pass, and confirm an eligible merchant payment with the recipient's own PIN.
5. Review activity as the issuer. Demonstrate a wrong PIN, a category/limit violation, or a revoked pass being rejected. Compare wallet, pass usage, and History before/after.
6. Open Financial Insights. Select a suggested demo question for an immediate local answer; type a new financial question to use Gemini when configured or the disclosed local fallback otherwise.
7. Sign in as ADMIN and open **More > AI / ML Transaction Report**. Review predictions, severity, features, model version, held-out metrics, and out-of-domain warnings. Customers and merchants must receive 403 from the protected report endpoints, not merely lack a menu item.

Desktop uses a persistent sidebar. Customer mobile navigation keeps **Home, Account, FamilyPass, History, More**, with other services available from Home/Account. Account reports and budget guidance remain available to customers independently of the privileged ML report.

## Transaction Safety

- Sessions identify the requester; client-supplied role/account-switch fields do not authorize actions. Resource queries and the transaction service enforce ownership and recipient eligibility.
- Financial `POST` operations through `FinancialAPIView` and fund-closing `DELETE` require the requester's own **six-digit transaction PIN**, an `Idempotency-Key`, and valid CSRF. This includes fund creation even with zero initial allocation. Wrong/missing/locked PINs prevent execution.
- Set/change PIN with the account password; changing an existing PIN also requires its current value. Repeated or sequential PINs are rejected. PINs use Django hashing, are omitted from saved request payloads/API responses, and are never passed to Gemini.
- Ten failed login attempts within the five-minute failure window trigger a one-minute account/IP lockout. Five incorrect PIN attempts trigger a one-minute financial lockout. Blocked PIN attempts do not extend the deadline.
- `Idempotency-Key` permits 8-128 letters, digits, underscores, periods, colons, or hyphens. A UUID is suitable. Retry with the **same route/action, resource, key, and unchanged payload**; changed details produce `409 IDEMPOTENCY_CONFLICT`. Successful/deterministic rejected responses are persisted; replays include `Idempotency-Replayed: true`. PIN failures do not reserve a key; replay still requires a valid PIN.
- PostgreSQL atomic blocks and ordered row locks protect sender/recipient wallets, funds, pass usage, and merchant balances. Database checks prevent negative balances and allowance overruns. Accounting, items, notifications, and the financial request record commit together.
- Purpose Funds support matching-category merchant payments, not arbitrary wallet actions. Send Money, recharge, and cash-out use the normal wallet. FamilyPass supports eligible merchant/bill flows; unsupported combinations remain rejected.
- FamilyPass verifies the active CUSTOMER issuer/recipient, assigned recipient, active status, start/expiry dates, permitted action/category, remaining allowance, and issuer wallet sufficiency. Spending is never permitted merely because a Contact or fund recipient assignment exists.
- Category-restriction rejections can retain a rejected ledger entry without changing money. Not every validation failure creates a transaction record. ML runs after a transaction commits and never decides whether a payment is allowed.

Non-financial fund metadata edits and pass grant/edit/revoke operations still require authentication, ownership, and CSRF but do not use the money-moving PIN/idempotency wrapper. ADMIN reporting is read-only. The Django admin exposes wallets, funds, passes, ledgers, and anomaly records through financial read-only handlers; merchant balances are read-only too. Financial request records are not registered for Django admin editing.

## Anomaly Detection and Evaluation

### Dataset, Training, and Features

The trainer uses [fundshare_anomaly_dataset_480.csv](model/fundshare_anomaly_dataset_480.csv), not the accompanying XLSX or synthetic records created by `seed_fundshare`. The CSV has **480 labeled demo transactions: 402 Normal and 78 Anomaly**, all `MERCHANT_PAYMENT`, across eight categories and the three payment sources.

Rows are sorted chronologically. The earlier **336 rows (70%)** train an **unsupervised Isolation Forest**; the later **144 rows (30%)** are held out for evaluation. The encoder is fitted only on training rows. Configuration: 300 trees, `random_state=42`, fixed `contamination=0.15`, `n_jobs=1`; no test-label threshold tuning. The saved model is the training-split model, not a model refitted on the evaluated rows.

Input allowlist:

```text
amount_bdt, category, payment_source, transaction_type, hour, day_of_week,
is_weekend, is_new_merchant, minutes_since_prev_txn, user_avg_amount_prior,
category_avg_amount_prior, rolling_7d_spend_prior, rolling_30d_spend_prior,
prior_txn_count
```

Feature engineering includes log transforms of amounts/history/spend/gaps/counts, ratios to prior averages capped at 50, rapid-repeat and cold-start flags, hour/off-hour/weekday/weekend flags, new-merchant status, and deterministic categorical encoding using `DictVectorizer`. **Transaction/user/merchant identifiers, `anomaly_label`, and `anomaly_type` are never model inputs. Labels are used only to validate the dataset and compute held-out metrics, not as training targets.**

Runtime history includes only earlier completed sender transactions; the current/future transaction is excluded and primary-key order breaks timestamp ties. Hours use local `Asia/Dhaka` time. The precomputed historical fields in the CSV are assumed to be prior-only as supplied; their provenance has not been independently audited.

### Measured Held-Out Results

The current [evaluation manifest](model/artifacts/evaluation.json) records model version **`iforest_v2_0c0c2eb846f6`**. Predictions were independently recomputed from the saved artifact and held-out CSV on 2026-10-07; the dataset SHA-256 matched the manifest.

| Metric | Measured value |
|---|---:|
| Accuracy | **0.861111 / 86.11%** |
| Precision, Anomaly class | **0.500000 / 50.00%** |
| Recall, Anomaly class | **0.650000 / 65.00%** |
| F1-score, Anomaly class | **0.565217** |
| ROC-AUC, continuous negative Isolation Forest score | **0.852419** |

Confusion matrix (rows = actual; columns = predicted):

| Actual / Predicted | Normal (0) | Anomaly (1) |
|---|---:|---:|
| Normal (0) | 111 true negatives | 13 false positives |
| Anomaly (1) | 7 false negatives | 13 true positives |

Accuracy is derived from the saved confusion matrix: `(111 + 13) / 144`. It is **not a separate stored manifest field or UI metric**. The held-out labels contain 124 Normal and 20 Anomaly transactions. Predicting every row as Normal would also obtain 86.11% accuracy, so accuracy alone is misleading. This model detects 13/20 labeled anomalies, while half of its 26 flags are false positives. These are honest demo results, not production fraud-detection claims.

Training ends at `2026-09-02 18:57`; evaluation runs from `2026-09-02 19:56` through `2026-09-30 11:05` in the dataset's timestamp representation. The manifest includes these boundaries, training/test sizes, confusion matrix, label counts, seed, contamination, input schema, library version, dataset SHA-256, score definition, and limitations. Zero evaluation metrics remain zero; undefined ROC-AUC is null, not a fabricated fallback.

### Saved Artifact and Live Flow

```text
Committed Transaction
  -> prior-only feature extraction
  -> trusted saved Isolation Forest
  -> 0 = Normal / 1 = Anomaly
  -> PostgreSQL AnomalyResult
  -> ADMIN-only API/UI review
```

- Artifact: `model/artifacts/anomaly.joblib`, containing the fitted forest, vectorizer, training reference scores, and metadata. Load only trusted local deployment artifacts; joblib/pickle files can execute code. Do not place the artifact in static/media directories or accept model uploads.
- Persistence: the one-to-one `AnomalyResult.is_anomaly` boolean stores the binary classification; its `prediction` property/API field exposes the same value as integer 0/1. Stored data also includes severity, reason, feature snapshot, raw anomaly/decision scores, model version, and creation time.
- Severity: `anomaly_score` is a **0-1 percentile rank against training severity scores**, displayed as a percentile. It is not a fraud probability, calibrated confidence, or accuracy. The binary class uses the forest's decision threshold, not a separate percentile cutoff. See the [Isolation Forest documentation](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.IsolationForest.html) for its native outlier scoring convention.
- Coverage: new ORM-created `Transaction` records are scored after commit, including recorded rejected/failed attempts. Other transaction types and unseen categories/sources still get binary predictions but carry an **outside-training-domain** warning; they were not covered by the reported evaluation.
- Failures: scoring errors are logged and do not roll back settled money. Missing/obsolete results appear as **Unscored**, never implicitly Normal. Bulk-created/imported entries bypass normal save signals and need backfill. Cold-start and live-data distribution behavior need further validation.
- Access: active ADMIN authorization is checked by the backend for reports, evaluation, and the ML intelligence dashboard. Public ledgers, old financial replay responses, customer reports/notifications, and customer/merchant chat context exclude anomaly classifications. The frontend also omits the Admin report and anomaly prompt for non-admins.

### Model Commands

Run in the configured virtual environment. These commands modify model artifacts/prediction records, not wallet balances:

```text
python manage.py train_anomaly_model
python manage.py train_anomaly_model --backfill
python manage.py backfill_anomaly_predictions
python manage.py backfill_anomaly_predictions --force
```

`--backfill` after training rescans the existing ledger. Normal backfill retries missing/old-version records; `--force` rescans all records. The runtime refuses artifacts with a mismatched scikit-learn version/input schema. Retrain after model/schema/library changes, and **restart all backend workers after retraining** because each process caches its loaded model. Extended operational notes: [model/README.md](model/README.md).

## Hybrid AI Chat

| Question path | Behavior |
|---|---|
| Click one of the 18 suggested demo questions | Browser returns the embedded predefined answer immediately; no chat API or Gemini request. |
| Type an exactly matching predefined question/alias | Backend normalizes case/punctuation/spacing and returns local Q&A; no Gemini call. |
| Type a new question | Authenticated backend supplies support instructions plus a bounded authorized financial snapshot to Gemini. |
| Gemini missing/unavailable/timeout/empty/blocked response | Backend returns existing deterministic financial analytics with a fallback notice. Demo Q&A stays available. |
| Ask for restricted anomaly classifications as a customer/merchant | Local access-restricted guidance; no privileged model results are disclosed. |

The shared catalog is [demo_qa.py](fundshare_app/ml/demo_qa.py). Topics include Purpose/Shared Funds, FamilyPass grant/use/restrictions/revocation, Send Money, merchant payments, PIN/security/retries, budgeting, insights, History, Contacts, and general app use. Matching is predefined-question matching, not a broad keyword substitution for arbitrary support questions.

The frontend calls `/api/ai/query/`; only [ai_coach.py](fundshare_app/ml/ai_coach.py) calls the external provider. The SDK receives the backend environment key, the configured model, a 15-second HTTP timeout, one configured attempt, and at most 1,200 output tokens. Question length is limited to 2,000 characters; API `lang` accepts `en` or `bn`. Predefined demo answers are currently English; the disabled app-wide language switch is not implemented.

[support_context.py](fundshare_app/ml/support_context.py) includes a limited wallet/monthly summary, up to six owned active funds with forecasts, four active issued and four active received passes with up to two activity entries each, eight visible recent transactions, up to six category totals, and up to four non-anomaly insight types. Ledger visibility follows sender, receiver, or issuer of the used pass. Recipient assignment alone does not expose someone else's funds/wallet. ADMIN context can include a small authorized anomaly summary; non-admin context cannot.

Account names/usernames/phones, private references, password/PIN hashes, and API keys are not intentionally included in the provider snapshot. User-entered fund names, purpose text, and questions can still contain personal information: **never put credentials or unnecessary personal data in them**. Gemini receives some authorized financial data, so enabling it is not wholly offline/private processing; production requires appropriate consent, retention, and provider data-handling review.

The assistant is a concise, friendly, **read-only product helpline**. It has no transaction tools and cannot move money, execute a payment, alter access, or bypass PIN rules. Provider text is generated, not guaranteed correct or hallucination-free. Offline financial answers are deterministic; unsupported open-ended conversation without Gemini receives local guidance rather than invented facts. Suggested demo Q&A is local, but live wallet operations still require the backend/database.

## Financial Insights and Forecasting

The budgeting components are separate from the saved anomaly classifier and the LLM:

- `ReportService` aggregates recorded completed spending, income, categories, funds, and issuer-funded FamilyPass usage over the selected period. Reports distinguish delegated spending from a recipient's own money. History's Transaction Summary covers loaded records, not a complete statement.
- `BudgetForecaster` uses a deterministic daily burn rate and remaining days to project month-end expenditure, producing `SAFE`, `MODERATE`, or `HIGH_RISK`. When no matching period spend is recorded, it can fall back to allocation-minus-current-balance. It persists forecast records and high-risk budget insights; it is not a separately trained neural or time-series model.
- `RecommendationEngine` derives allocation and inter-fund transfer advice from those forecasts/balances. Advice never automatically transfers money; accepting changes must use normal authorized, PIN-confirmed financial flows. Heuristic confidence fields are not calibrated prediction probabilities.

The forecast evaluation helper currently calculates **MAE 347.50 BDT, RMSE 398.81 BDT, MAPE 3.62%** from **eight fixed synthetic actual/prediction pairs in code**. These arithmetic fixture results are exposed to ADMIN evaluation, but are **not a backtest generated from historical ledger months or evidence of forecast accuracy on users**. Similarly, the seed generator's spreadsheet/prototype experiment comparisons use generated times/outcomes; do not present them as real research results.

## API Reference

All paths below use `/api/`. Only login and registration permit unauthenticated API use; they still require CSRF. Other endpoints require a session. Unsafe requests require CSRF, and financial routes additionally require the PIN/idempotency contract above. There is no JWT/API-key account authentication or automatic OpenAPI/Swagger endpoint in this repository.

**Access legend:** Auth = signed-in user scoped to accessible data; Wallet = CUSTOMER/ADMIN with relevant ownership checks; Customer = CUSTOMER-only; Admin = active ADMIN/effective superuser. A merchant business dashboard requires a MERCHANT account with its own linked business; ADMIN status does not bypass that endpoint's role check.

| Method | Canonical path | Access / main fields or filters |
|---|---|---|
| POST | `auth/register/` | Public + CSRF; `full_name`, `username`, `phone`, `password1`, `password2`; CUSTOMER-only signup |
| POST | `auth/login/` | Public + CSRF; `username` accepts username/phone; `password` |
| POST | `auth/logout/` | Auth; terminate session |
| GET | `auth/me/` | Auth; current profile, effective role, wallet summary, visible unread count |
| POST | `auth/pin/` | Auth; `password`, `new_pin`, existing `current_pin` when changing |
| GET | `wallet/summary/` | Auth; current wallet, owned funds, accessible pass summary, recent records |
| POST | `wallet/cash-in/` | Wallet + financial contract + development flag; `amount`, optional `reference` |
| POST | `wallet/send/` | Wallet + financial contract; `receiver_phone`, `amount`, optional `reference` |
| POST | `wallet/utility/` | Wallet + financial contract; `action_type=RECHARGE|BILL|CASHOUT`, `amount`, optional provider/account/reference; bill provider must be approved |
| GET, POST | `funds/` | Wallet; list owned active funds / create with `name`, `category`, optional `allocated_amount`, `monthly_budget`, recipient phone in `recipient`; POST financial contract |
| GET, PATCH, PUT, DELETE | `funds/<id>/` | Owner; metadata edit or safe close/archive; DELETE financial contract |
| POST | `funds/<id>/allocate/` | Owner + financial contract; `amount` |
| POST | `funds/transfer/` | Owned funds + financial contract; `source_fund_id`, `destination_fund_id`, `amount`, optional `reason` |
| GET | `funds/<id>/details/` | Owner; fund/forecast and up to 15 recent transactions |
| GET | `merchants/` | Auth; active registered merchants |
| POST | `pay/` | Wallet + financial contract; `merchant_id`, `amount` or valid `items`, `payment_source`, relevant fund/pass ID, optional reference |
| GET | `merchant/dashboard/` | MERCHANT with a linked business; own business and received payments |
| GET, POST | `family-pass/` | Customer; issued/received passes / grant using `recipient_phone`, `limit_amount`, `duration_days`, `purpose`, optional allowed action/categories/custom purpose |
| GET, PATCH, PUT, POST | `family-pass/<id>/` | Owner/assigned recipient for read; only owner can edit; cannot change ownership/recipient |
| POST | `family-pass/<id>/revoke/` | Customer owner; stop new spending, preserve history |
| GET | `family-pass/<id>/activity/` | Customer issuer/assigned recipient; pass activity/items |
| GET | `familypass/recipients/` | Customer; eligible active customer discovery, not permission to spend |
| GET, POST | `contacts/` | Auth, private address book; optional `q` / `name`, `phone`, optional stored username |
| GET, PATCH, PUT, DELETE | `contacts/<id>/` | Contact owner; view/update/delete |
| GET | `contacts/search/` | Auth, own contacts; `q` |
| GET, POST | `recipients/resolve/` | Auth; `phone`, `feature`; phone-only registered account lookup, independent of Contacts |
| GET | `transactions/` | Auth; visible sender/receiver/pass-issuer records; `type`, `category`, `source`, `fund_id`, `status`; newest 50 |
| GET | `notifications/` | Auth, own visible notifications; newest 25; non-admin anomaly alerts excluded |
| POST | `notifications/<id>/read/` | Notification owner; mark read |
| POST | `ai/query/` | Auth; `question`, optional `lang=en|bn` |
| GET | `reports/` | Auth, own financial report; `period=weekly|monthly|yearly` |
| GET | `intelligence/dashboard/` | **Admin**; privileged intelligence dashboard |
| GET | `admin/ml/transactions/` | **Admin**; `prediction=0|1|unscored`, `type`, transaction-ID `search` (max 64 chars), `page`; 20 rows/page |
| GET | `evaluation/metrics/` | **Admin**; saved anomaly metadata and forecast fixture metrics |
| GET, POST | `evaluation/experiments/` | **Admin**; comparison records / validated experiment record fields |
| POST | `seed/` | **Admin**, development reset flag; optional `wipe` is destructive |

Compatibility aliases route to the same views/permissions: `wallet/send-money/`, `payments/merchant/`, `familypass/` and its `<id>/`, edit/revoke/activity variants, `family-pass/<id>/edit/`, `contacts/resolve/`, `familypass/members-list/`, `intelligence/coach/`, and `admin/seed-data/`. Prefer canonical paths; aliases do not introduce new roles or privileges.

### Recipient Lookup

`SEND_MONEY`, `FAMILY_PASS`, and fund recipient assignment use registered phone numbers, not usernames/account IDs. Accepted Bangladesh formats such as `+8801712345678`, `008801712345678`, and `1712345678` normalize to the unique canonical `01712345678` format. Phones are not SMS-verified in this prototype. Saved contact usernames cannot override the matched phone identity.

The resolver returns HTTP 200 with eligibility fields, including `is_eligible`, `is_registered`, `normalized_phone`, `error_message`, `code`, and a limited matched account identity. A valid unknown number produces `RECIPIENT_NOT_REGISTERED` and **"This account is not registered yet."** The actual Send Money/FamilyPass action rejects an ineligible recipient; resolving a phone does not grant authorization or reveal wallet balances. Legacy `receiver`, `member`, and `member_identifier` inputs accept phone numbers only.

### Browser/API Request Example

From an authenticated, same-origin browser session, use the latest `csrftoken` cookie (login rotates it). The following is a **template**, not a command with real credentials. Substitute an existing recipient and the user's chosen PIN. Retain the same key/payload when retrying; do not run this in an automatic loop.

```javascript
const csrf = decodeURIComponent(document.cookie.split('; ').find(v => v.startsWith('csrftoken=')).slice('csrftoken='.length));
const requestKey = crypto.randomUUID();
const response = await fetch('/api/wallet/send/', {
  method: 'POST',
  credentials: 'same-origin',
  headers: {
    'Content-Type': 'application/json',
    'X-CSRFToken': csrf,
    'Idempotency-Key': requestKey,
  },
  body: JSON.stringify({receiver_phone: 'REGISTERED_RECIPIENT_PHONE', amount: '100.00', pin: 'YOUR_SIX_DIGIT_PIN'}),
});
const result = await response.json();
```

An external API client must first GET `/login/` to obtain CSRF, POST `auth/login/` with that token, retain its session cookie, and then use the refreshed CSRF token for protected mutations. Do not put passwords/PINs into URLs or committed command histories. Use resource IDs returned by the API for merchants/funds/passes; do not assume seed IDs are identical across machines. Checkout item fields are `name`, optional `product_id`, `quantity`, `unit_price`, optional `discount`, `tax`; the backend validates line totals and any supplied overall amount. Bill provider/category mappings are defined in `TransactionService.BILL_PROVIDER_CATEGORIES`; clients cannot relabel a bill to bypass category checks.

Common outcomes: 201 for creation, 200 for successful reads/actions/replays, 400 for invalid details/restrictions, 401 for missing API authentication or bad login, 403 for authorization/CSRF/wrong PIN, 404 for missing/inaccessible resources, 409 for conflicting requests/state, 429 for lockouts/throttling, and 503 for retryable database confirmation errors. Many API errors include `error` and `code`, but resource/CSRF/validation shapes vary; do not assume every error has the same JSON schema. Check History after an uncertain financial response before starting a new payment.

## Tests and Verification

Run tests against a **disposable PostgreSQL test database**, never by switching runtime to SQLite. With the configured local role's `CREATEDB` permission:

```text
python manage.py test fundshare_app --noinput --settings=fundshare_core.test_settings --verbosity 1
```

The test settings disable Gemini keys and use fast fixture hashing/local cache; they are not production settings. Dedicated security coverage checks the normal production PIN hasher. The standard-settings suite is also available with `python manage.py test fundshare_app --noinput`, but the isolated test configuration above is the reproducible no-external-AI choice.

Focused checks:

```text
python manage.py test fundshare_app.test_anomaly_model fundshare_app.test_ai_chat --noinput --settings=fundshare_core.test_settings
python manage.py check
python manage.py makemigrations --check --dry-run
git diff --check
```

The current suite contains **268 tests**, covering registration, canonical phone lookup, optional Contacts, CUSTOMER/FamilyPass boundaries, PIN/CSRF/authentication, idempotent replay, rollback, concurrent balance/allowance protection, PostgreSQL indexes/constraints, legacy import, hybrid AI privacy/failure, saved-model training/inference/evaluation, restricted ML outputs, and UI DOM contracts. UI DOM tests are not a full browser end-to-end suite; also exercise actual responsive payment/PIN, FamilyPass, report filters/pagination, empty/error/loading states, and customer/merchant access restrictions manually or with your own browser test tooling. There is no npm-based browser-test runner shipped as a required application dependency.

## Legacy Data Import

SQLite is supported **only as a read-only legacy import source**, not as the app/test database. Stop all writers, preserve the original source, and use an empty migrated PostgreSQL destination. Source `fundshare_app` migration `0009_canonical_phones_and_lockouts` must already be applied; upgrade an older source copy with the earlier SQLite-capable release first.

```text
python manage.py migrate
python manage.py import_legacy_sqlite --source PATH_TO_LEGACY.sqlite3
python manage.py backfill_anomaly_predictions
```

The importer creates a consistent private backup under `.local/backups`, refuses a populated destination, retains IDs/credential hashes/financial relationships/sessions, checks constraints and serialized record equality inside one PostgreSQL transaction, and resets primary-key sequences. Invalid fields or mismatches roll back the import; it does not merge accounts or silently truncate values. Backups contain private data and must not be committed. Imported records require model backfill after a valid artifact is prepared.

Migrations include static CUSTOMER roles (`0008`), canonical unique phones and shortened lockouts (`0009`), PostgreSQL accounting indexes/positive-amount constraints (`0010`), and nullable preserved anomaly-user audit linkage, score-range constraints, and prediction filter indexes (`0011`). Invalid/colliding legacy phones must be resolved before normalization; migration does not automatically merge accounts.

## Deployment and Integrations

### Deployment Checklist

This checklist describes configuration supported by the code, not a claim that the prototype is certified for real money:

1. Provision PostgreSQL and Redis with separate least-privilege credentials. Configure `DEBUG=False`, a unique `SECRET_KEY`, production `ALLOWED_HOSTS`, `DATABASE_URL`, and `REDIS_URL` through a private environment/secret manager.
2. Serve behind HTTPS. Production enables secure session/CSRF cookies, HTTPS redirects, HSTS, and browser security headers. Set `TRUST_PROXY_HTTPS=True` only with a trusted correctly configured reverse proxy. Add non-Render deployment origins to CORS/CSRF settings as needed; do not enable wildcard credentialed CORS.
3. Deploy the trusted model artifact with its pinned library version outside publicly served assets. Train if needed, backfill missing predictions, restart workers, and verify ADMIN restrictions.
4. Apply migrations, collect static files, run deployment checks, and create secured ADMIN access. Do not enable/seeding-reset known demo accounts on production data.

```text
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py check --deploy
```

For a Linux/WSL host behind the reverse proxy, a basic WSGI command is:

```text
gunicorn fundshare_core.wsgi:application --bind 127.0.0.1:8000 --workers 2
```

Windows local development uses `runserver`, not Gunicorn. `build.sh` only installs dependencies, collects static files, and migrates; it does not provision services, configure secrets, train the model, or start an app server. Production backups, reconciliation, monitoring, identity verification, operational access control, and external settlement remain additional work.

### Supported and Future Integrations

| Integration | Status / how to configure or extend |
|---|---|
| PostgreSQL | Implemented; configure `DATABASE_URL`, migrate, and use the validated accounting service rather than direct balance writes. |
| Redis | Implemented shared throttling cache; configure `REDIS_URL`. Not a Celery/job queue. |
| Gemini | Implemented backend support integration; set `GEMINI_API_KEY`/`GEMINI_MODEL`. Frontend must call the existing backend chat endpoint, never Google with a browser key. |
| Upay, banks, bill/recharge/cash-out providers | Not connected. Adding keys alone does not enable settlement. Implement a server-side provider adapter, verified initiation/confirmation/webhook handling, authorization, idempotency, reconciliation, and tests before claiming real payment support. |
| SMS/OTP, KYC, password recovery/email delivery | Not implemented as verified production flows. They require provider code, verification/state management, secure credentials, and tests. |

To add an API/provider, follow existing modules: routes in `fundshare_app/urls.py`, authenticated/role-scoped views, structured serializers/validation, and a narrowly scoped service. Money-moving routes must preserve `FinancialAPIView`, PIN/CSRF/idempotency and `TransactionService` locking/accounting behavior. Keep new secrets in backend environment configuration, document placeholder names in `.env.example`, add migrations where needed, and test unauthorized, failed, retried, and concurrent requests. Do not invent a UI action for an unimplemented integration.

## Troubleshooting and Limitations

| Symptom | Check / remedy |
|---|---|
| `SECRET_KEY` / `DATABASE_URL` required | Configure the ignored root `.env`; replace placeholders, activate the correct interpreter, and restart Django. |
| Redis required locally or HTTPS redirect loop | Verify `DEBUG=True`. Shell/IDE values override `.env`; e.g. PowerShell `$env:DEBUG='True'` for this development session. Production needs Redis and actual HTTPS/proxy configuration. |
| PostgreSQL connection refused/password failure | Start the server, check port/role/database/password and URL escaping. The portable start script requires an already initialized `.local` instance. |
| Tests cannot create database | Give the local disposable test role `CREATEDB` using a database administrator; never test against valuable app data. |
| Table/column missing | Run `python manage.py migrate` against the correct PostgreSQL database. |
| PIN not set/incorrect/locked | Set it via More > Change PIN with the account password; use your own PIN for shared payments. Wait one minute after lockout. Do not disable verification. |
| Recipient not registered | Check the normalized Bangladesh phone and register the recipient. A Contact entry alone is not a wallet account. |
| Purpose Fund/FamilyPass rejected | Review category, status, dates, permitted action, recipient, remaining balance/limit, and issuer wallet funds. Pass `ALL` is still limited to supported flows. |
| 403 on a mutation | Confirm session/ownership, refreshed CSRF token, and valid PIN for financial actions. Do not solve it by disabling CSRF. |
| `IDEMPOTENCY_KEY_REQUIRED` / `IDEMPOTENCY_CONFLICT` | Include a valid key; retry only the same action/details with that key. For an intentionally different new action, first confirm the prior outcome. |
| Missing/incompatible model or Unscored rows | Install the pinned requirements, train the trusted artifact, run backfill, inspect scoring logs, and restart backend workers. Do not display missing predictions as Normal. |
| ML report missing for a normal user | Intended behavior: only ADMIN can view classifications/evaluation; personal spending reports remain available. |
| Gemini unavailable | Check the backend key, model access, quotas, and network; restart after config changes. Offline Q&A and local financial fallback still work; provider errors do not expose secrets. |
| Seeding conflicts or unexpectedly changes demo data | Do not repeatedly seed existing data. Use fresh disposable databases; import/backfill is the preservation path. |
| Static icons/styles missing in deployment | Run `collectstatic` and verify WhiteNoise/static hosting. Inter may fall back to a system font without internet. |
| Screenshot not visible on GitHub | Keep `images/` in the checkout/commit. Links preserve the supplied filenames with URL-encoded spaces. |

**Known limitations:** no external financial settlement or SMS-verified ownership; no identity/KYC checks, production password recovery, QR payment scanner, Request Money, prepaid/linked cards, biometric login, or app-wide language switch. Unsupported UI controls are disabled/Coming Soon rather than fake services. Notifications are stored in-app, not a WebSocket/SMS delivery integration. The ML dataset is small and merchant-only; false positives/negatives and cold-start/distribution shifts require human review and better validation. LLM outputs remain fallible and external context needs privacy review. Daily-rate forecasts and seeded experiments are prototype heuristics/fixtures, not independently validated studies.

The code and this README describe the current implementation. [Project_Report/FUNDShare_Hackathon_Report.md](Project_Report/FUNDShare_Hackathon_Report.md) is historical presentation material and may contain older feature/metric claims; do not substitute those for the saved evaluation results above. No root project license file is currently included; do not assume a project-wide open-source license. Vendored Lucide has its own [license](static/vendor/lucide-LICENSE).
