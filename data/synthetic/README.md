# FUNDShare Synthetic Historical Financial Dataset

> **CRITICAL COMPLIANCE NOTICE**:
> **SYNTHETIC DATA — NOT REAL UPAY CUSTOMER DATA**
> This dataset was generated entirely synthetically for the FUNDShare Mobile Financial Services (MFS) hackathon prototype to train and evaluate Anomaly Detection, Budget Forecasting, and AI Financial Coaching. It does not represent or contain any real customer data.

---

## 1. Dataset Overview

* **Time Horizon**: April 11, 2026 to October 07, 2026 (179 chronological days)
* **Customer Users**: 25 unique customer accounts
* **Merchants**: 32 verified merchants across 10 business categories
* **Purpose Funds**: 77 active purpose fund budgeting buckets
* **FamilyPass Delegations**: 10 active spending authorization delegations
* **Total Transactions**: 3,310 events
* **Average Volume per User**: 132.4 transactions / customer
* **Reproducibility Random Seed**: `2026`

---

## 2. Transaction Distribution

| Spending Category | Transactions | Percentage |
|:---|:---:|:---:|
| **Purpose Fund Spending** | 1162 | 35.1% |
| **FamilyPass Spending** | 400 | 12.1% |
| **Normal Wallet Spending** | 885 | 26.7% |
| **Utility & Bill Payments** | 343 | 10.4% |
| **Inflows & Fund Allocations** | 714 | 21.6% |
| **Total** | **3310** | **100.0%** |

---

## 3. Anomaly & Policy Violation Design

* **Behavioral Outliers (Ground Truth)**: 150 transactions (4.53%)
  * `LARGE_AMOUNT`: 4.5× to 6.5× higher than user's category average
  * `UNUSUAL_TIME`: Transactions between 01:00 AM and 04:30 AM
  * `SPENDING_BURST`: Multiple high-velocity transactions within 1 hour
  * `UNUSUAL_CATEGORY`: Infrequent category expenditure with high value
* **Policy Violations (Deterministic Rejections)**: 55 transactions
  * Purpose Fund category mismatches
  * FamilyPass merchant category mismatches
  * FamilyPass quota limits exceeded
  * Recorded with `status='REJECTED'` and non-empty `rejection_reason` without altering balances.

---

## 4. File Manifest

1. `users.csv`: Customer identities, profiles, salaries, and phone numbers.
2. `wallets.csv`: Customer wallet balances with initial and final states.
3. `merchants.csv`: Merchant directory with account numbers and categories.
4. `purpose_funds.csv`: Dedicated budgeting funds, allocations, and expenditures.
5. `family_passes.csv`: Authorization delegations linking owners and members.
6. `transactions.csv`: **Central chronological ledger** linking users, merchants, funds, FamilyPass, and derived balances.
7. `family_pass_transactions.csv`: Granular activity logs of FamilyPass spend.
8. `transaction_items.csv`: Itemized basket purchases for merchant payments.
9. `anomaly_ground_truth.csv`: Isolated evaluation labels and anomaly taxonomies.
10. `dataset_summary.json`: Comprehensive machine-readable dataset statistics.

---

## 5. Machine Learning Safety & Leakage Boundaries

### Safe Features for ML Models:
* `amount`, `timestamp` (hour, day of week, day of month)
* `transaction_type`, `payment_source`, `category`, `merchant_id`
* `wallet_balance_before`, `fund_balance_before`, `family_pass_limit_remaining_before`
* Rolling historical user statistics prior to the transaction timestamp.

### FORBIDDEN Features (Target Leakage):
* `status` (`COMPLETED` vs `REJECTED`)
* `rejection_reason`
* `wallet_balance_after`, `fund_balance_after`, `family_pass_limit_remaining_after`
* `ground_truth_anomaly` (Target label only, never an input feature)

---

## 6. Reproduction Command

To reproduce this exact dataset:
```powershell
python scripts/generate_synthetic_dataset.py
```
