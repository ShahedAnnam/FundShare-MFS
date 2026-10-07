"""
Django management command to load the generated synthetic historical dataset
from data/synthetic/ into the Django database using the Django ORM.

NOTICE: SYNTHETIC DATA — NOT REAL UPAY CUSTOMER DATA.
"""

import os
import csv
import json
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.utils.dateparse import parse_datetime, parse_date
from django.db import transaction as db_transaction

from fundshare_app.models import (
    Wallet, Merchant, PurposeFund, FamilyPass, Transaction,
    FamilyPassTransaction, TransactionItem, AnomalyResult,
    UserRole, BusinessCategory, FundStatus, FamilyPassStatus
)

User = get_user_model()


class Command(BaseCommand):
    help = 'Loads the synthetic historical dataset from data/synthetic/ into the database via Django ORM'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Validate CSV records without committing to database')

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        data_dir = os.path.join(base_dir, 'data', 'synthetic')

        if not os.path.exists(data_dir):
            self.stderr.write(self.style.ERROR(f"Synthetic data directory not found: {data_dir}"))
            return

        self.stdout.write(self.style.NOTICE(f"Loading synthetic dataset from {data_dir}... (dry-run={dry_run})"))

        with db_transaction.atomic():
            # 1. Load Users & Wallets
            users_file = os.path.join(data_dir, 'users.csv')
            wallets_file = os.path.join(data_dir, 'wallets.csv')
            
            # Read wallets CSV for initial/final balances
            wallet_balances = {}
            with open(wallets_file, 'r', encoding='utf-8') as f:
                for row in csv.DictReader(f):
                    wallet_balances[int(row['owner_id'])] = Decimal(row['final_balance'])

            user_map = {}
            created_users_count = 0
            with open(users_file, 'r', encoding='utf-8') as f:
                for row in csv.DictReader(f):
                    u_id = int(row['user_id'])
                    username = f"synthetic_user_{u_id:03d}"
                    if not dry_run:
                        u, created = User.objects.get_or_create(
                            username=username,
                            defaults={
                                'full_name': row['full_name'],
                                'phone': row['phone'],
                                'role': UserRole.CUSTOMER
                            }
                        )
                        if created:
                            u.set_password("password123")
                            u.set_transaction_pin("123456")
                            u.save()
                            created_users_count += 1
                        
                        # Ensure wallet with simulated balance
                        wallet, _ = Wallet.objects.get_or_create(
                            owner=u,
                            defaults={'balance': wallet_balances.get(u_id, Decimal('1000.00'))}
                        )
                        wallet.balance = wallet_balances.get(u_id, Decimal('1000.00'))
                        wallet.save()

                        user_map[u_id] = u
                    else:
                        user_map[u_id] = None

            self.stdout.write(self.style.SUCCESS(f"Processed {len(user_map)} synthetic customer users ({created_users_count} newly created)."))

            # 2. Load Merchants
            merchants_file = os.path.join(data_dir, 'merchants.csv')
            merchant_map = {}
            created_merchants_count = 0
            with open(merchants_file, 'r', encoding='utf-8') as f:
                for row in csv.DictReader(f):
                    m_id = int(row['merchant_id'])
                    if not dry_run:
                        m, created = Merchant.objects.get_or_create(
                            account_number=row['account_number'],
                            defaults={
                                'business_name': row['business_name'],
                                'category': row['category'],
                                'contact_phone': row['contact_phone'],
                                'address': row['address'],
                                'balance': Decimal(row['final_balance']),
                                'is_active': True
                            }
                        )
                        if created:
                            created_merchants_count += 1
                        merchant_map[m_id] = m
                    else:
                        merchant_map[m_id] = None

            self.stdout.write(self.style.SUCCESS(f"Processed {len(merchant_map)} synthetic merchants ({created_merchants_count} newly created)."))

            # 3. Load Purpose Funds
            funds_file = os.path.join(data_dir, 'purpose_funds.csv')
            fund_map = {}
            created_funds_count = 0
            with open(funds_file, 'r', encoding='utf-8') as f:
                for row in csv.DictReader(f):
                    f_id = int(row['fund_id'])
                    owner_id = int(row['owner_id'])
                    if not dry_run:
                        owner = user_map[owner_id]
                        pf, created = PurposeFund.objects.get_or_create(
                            owner=owner,
                            name=row['name'],
                            category=row['category'],
                            defaults={
                                'allocated_amount': Decimal(row['total_allocated']),
                                'current_balance': Decimal(row['current_balance']),
                                'monthly_budget': Decimal(row['monthly_budget']),
                                'status': FundStatus.ACTIVE,
                                'icon': 'wallet',
                                'color': '#10B981'
                            }
                        )
                        if created:
                            created_funds_count += 1
                        fund_map[f_id] = pf
                    else:
                        fund_map[f_id] = None

            self.stdout.write(self.style.SUCCESS(f"Processed {len(fund_map)} synthetic Purpose Funds ({created_funds_count} newly created)."))

            # 4. Load FamilyPasses
            fp_file = os.path.join(data_dir, 'family_passes.csv')
            fp_map = {}
            created_fp_count = 0
            with open(fp_file, 'r', encoding='utf-8') as f:
                for row in csv.DictReader(f):
                    fp_id = int(row['family_pass_id'])
                    owner_id = int(row['owner_id'])
                    member_id = int(row['member_id'])
                    if not dry_run:
                        owner = user_map[owner_id]
                        member = user_map[member_id]
                        fp, created = FamilyPass.objects.get_or_create(
                            owner=owner,
                            member=member,
                            purpose=row['purpose'],
                            defaults={
                                'limit_amount': Decimal(row['limit_amount']),
                                'used_amount': Decimal(row['used_amount']),
                                'start_date': parse_date(row['start_date']),
                                'expiry_date': parse_date(row['expiry_date']),
                                'allowed_action': row['allowed_action'],
                                'status': FamilyPassStatus.ACTIVE,
                                'purpose_label': row['purpose_label'],
                                'allowed_categories': json.loads(row['allowed_categories'])
                            }
                        )
                        if created:
                            created_fp_count += 1
                        fp_map[fp_id] = fp
                    else:
                        fp_map[fp_id] = None

            self.stdout.write(self.style.SUCCESS(f"Processed {len(fp_map)} synthetic FamilyPasses ({created_fp_count} newly created)."))

            # 5. Load Transactions
            txns_file = os.path.join(data_dir, 'transactions.csv')
            created_txns_count = 0
            txns_to_create = []
            txn_rows_buffer = []

            with open(txns_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    txn_rows_buffer.append(row)
                    if not dry_run:
                        # Check if transaction already exists
                        t_id = row['transaction_id']
                        if not Transaction.objects.filter(transaction_id=t_id).exists():
                            sender = user_map.get(int(row['sender_id']))
                            receiver = user_map.get(int(row['receiver_id'])) if row['receiver_id'] else None
                            merchant = merchant_map.get(int(row['merchant_id'])) if row['merchant_id'] else None
                            pf = fund_map.get(int(row['purpose_fund_id'])) if row['purpose_fund_id'] else None
                            fp = fp_map.get(int(row['family_pass_id'])) if row['family_pass_id'] else None

                            meta = json.loads(row['metadata_json']) if row['metadata_json'] else {}
                            meta['synthetic_data'] = True
                            meta['generator_version'] = '1.0'
                            meta['wallet_balance_before'] = float(row['wallet_balance_before'])
                            meta['wallet_balance_after'] = float(row['wallet_balance_after'])
                            if row['fund_balance_before']:
                                meta['fund_balance_before'] = float(row['fund_balance_before'])
                                meta['fund_balance_after'] = float(row['fund_balance_after'])
                            if row['family_pass_limit_remaining_before']:
                                meta['family_pass_limit_remaining_before'] = float(row['family_pass_limit_remaining_before'])
                                meta['family_pass_limit_remaining_after'] = float(row['family_pass_limit_remaining_after'])

                            txns_to_create.append(
                                Transaction(
                                    transaction_id=t_id,
                                    sender=sender,
                                    receiver=receiver,
                                    merchant=merchant,
                                    amount=Decimal(row['amount']),
                                    transaction_type=row['transaction_type'],
                                    payment_source=row['payment_source'],
                                    purpose_fund=pf,
                                    family_pass=fp,
                                    category=row['category'],
                                    status=row['status'],
                                    rejection_reason=row['rejection_reason'],
                                    reference=row['reference'],
                                    timestamp=parse_datetime(row['timestamp']),
                                    metadata=meta
                                )
                            )

            if not dry_run and txns_to_create:
                Transaction.objects.bulk_create(txns_to_create, batch_size=500)
                created_txns_count = len(txns_to_create)

            self.stdout.write(self.style.SUCCESS(f"Processed {len(txn_rows_buffer)} transactions in CSV ({created_txns_count} newly inserted)."))

            # Build map of persisted transactions for foreign key linking
            db_txns_map = {}
            if not dry_run:
                synth_codes = [r['transaction_id'] for r in txn_rows_buffer]
                for t in Transaction.objects.filter(transaction_id__in=synth_codes):
                    db_txns_map[t.transaction_id] = t

            # 6. Load FamilyPassActivity (FamilyPassTransaction)
            fpt_file = os.path.join(data_dir, 'family_pass_transactions.csv')
            created_fpt_count = 0
            fpt_to_create = []
            with open(fpt_file, 'r', encoding='utf-8') as f:
                for row in csv.DictReader(f):
                    if not dry_run:
                        t_code = row['transaction_id']
                        txn_inst = db_txns_map.get(t_code)
                        if txn_inst and not FamilyPassTransaction.objects.filter(transaction=txn_inst).exists():
                            fp_inst = fp_map.get(int(row['family_pass_id']))
                            member_inst = user_map.get(int(row['member_id']))
                            fpt_to_create.append(
                                FamilyPassTransaction(
                                    family_pass=fp_inst,
                                    transaction=txn_inst,
                                    member=member_inst,
                                    amount=Decimal(row['amount']),
                                    remaining_limit_after=Decimal(row['remaining_limit_after']),
                                    timestamp=parse_datetime(row['timestamp'])
                                )
                            )
            if not dry_run and fpt_to_create:
                FamilyPassTransaction.objects.bulk_create(fpt_to_create, batch_size=500)
                created_fpt_count = len(fpt_to_create)

            self.stdout.write(self.style.SUCCESS(f"Processed FamilyPass activity logs ({created_fpt_count} newly inserted)."))

            # 7. Load Transaction Items
            items_file = os.path.join(data_dir, 'transaction_items.csv')
            created_items_count = 0
            items_to_create = []
            with open(items_file, 'r', encoding='utf-8') as f:
                for row in csv.DictReader(f):
                    if not dry_run:
                        t_code = row['transaction_id']
                        txn_inst = db_txns_map.get(t_code)
                        if txn_inst and not TransactionItem.objects.filter(transaction=txn_inst, product_id=row['product_id']).exists():
                            items_to_create.append(
                                TransactionItem(
                                    transaction=txn_inst,
                                    name=row['name'],
                                    product_id=row['product_id'],
                                    quantity=Decimal(row['quantity']),
                                    unit_price=Decimal(row['unit_price']),
                                    discount=Decimal(row['discount']),
                                    tax=Decimal(row['tax']),
                                    total=Decimal(row['total'])
                                )
                            )
            if not dry_run and items_to_create:
                TransactionItem.objects.bulk_create(items_to_create, batch_size=500)
                created_items_count = len(items_to_create)

            self.stdout.write(self.style.SUCCESS(f"Processed itemized basket records ({created_items_count} newly inserted)."))

            # 8. Verify Anomaly Ground Truth (Preserved in Transaction metadata & CSV, NOT AnomalyResult model predictions)
            anom_file = os.path.join(data_dir, 'anomaly_ground_truth.csv')
            verified_anom_count = 0
            with open(anom_file, 'r', encoding='utf-8') as f:
                for row in csv.DictReader(f):
                    t_code = row['transaction_id']
                    txn_inst = db_txns_map.get(t_code) or Transaction.objects.filter(transaction_id=t_code).first()
                    if txn_inst and txn_inst.metadata.get('ground_truth_anomaly') is True:
                        verified_anom_count += 1

            self.stdout.write(self.style.SUCCESS(f"Verified anomaly ground-truth records ({verified_anom_count} confirmed in Transaction metadata; AnomalyResult reserved for ML models)."))

            if dry_run:
                self.stdout.write(self.style.WARNING("DRY RUN completed. Database changes were rolled back."))
                db_transaction.set_rollback(True)
            else:
                self.stdout.write(self.style.SUCCESS("All synthetic records successfully committed to Django database."))
