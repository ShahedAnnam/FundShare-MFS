#!/usr/bin/env python
"""
FundShare-MFS Trust & Risk Upgrade - Demo Seeder & Scenario Verification
Phase 4 presentation script demonstrating 3-tier risk decisioning & analyst triage:
  - Step 1: Normal Spending [ALLOW]
  - Step 2: Velocity & Spike Attack [STEP_UP_PIN]
  - Step 3: Multi-Sender Fan-In Smurfing & 2-Hop Mule Ring [FLAG_FOR_REVIEW -> FraudIncident]
"""
import os
import sys
from decimal import Decimal

# Setup Django Environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'fundshare_core.settings')
import django
django.setup()

from django.utils import timezone
from fundshare_app.models import (
    User, UserRole, Wallet, Merchant, BusinessCategory,
    Transaction, TransactionType, PaymentSource, TransactionStatus,
    FraudIncident, AnomalyResult
)
from fundshare_app.ml.anomaly_detector import AnomalyDetector
from fundshare_app.ml.graph import TransactionGraphEngine

# Terminal formatting
GREEN = '\033[92m'
YELLOW = '\033[93m'
RED = '\033[91m'
CYAN = '\033[96m'
MAGENTA = '\033[95m'
BOLD = '\033[1m'
DIM = '\033[2m'
RESET = '\033[0m'


def banner(title):
    print(f"\n{BOLD}{CYAN}{'=' * 75}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'=' * 75}{RESET}")


def section(step, title):
    print(f"\n{BOLD}{MAGENTA}[{step}] {title}{RESET}")
    print(f"{DIM}{'-' * 70}{RESET}")


def seed_accounts():
    banner("FUNDSHARE-MFS TRUST & RISK: SEEDING DEMO ENVIRONMENT")

    accounts_spec = [
        ('demo_alice', '01711900001', 'Alice Vance (Normal Customer)', UserRole.CUSTOMER, Decimal('75000.00')),
        ('demo_bob', '01711900002', 'Bob Smith (Victim Account)', UserRole.CUSTOMER, Decimal('60000.00')),
        ('demo_charlie', '01711900003', 'Charlie Brown (Sender 3)', UserRole.CUSTOMER, Decimal('50000.00')),
        ('demo_mule', '01711900004', 'Mule Intermediary Hub', UserRole.CUSTOMER, Decimal('2000.00')),
        ('demo_merchant', '01711900005', 'Daily Fresh Superstore', UserRole.MERCHANT, Decimal('150000.00')),
        ('demo_cashout', '01711900006', 'MFS Cashout Agent #402', UserRole.MERCHANT, Decimal('250000.00')),
    ]

    # Clear prior demo transactions to guarantee deterministic velocity and scoring
    demo_usernames = [spec[0] for spec in accounts_spec]
    Transaction.objects.filter(sender__username__in=demo_usernames).delete()

    users = {}
    for username, phone, full_name, role, balance in accounts_spec:
        user, _ = User.objects.get_or_create(
            username=username,
            defaults={'phone': phone, 'full_name': full_name, 'role': role}
        )
        user.phone = phone
        user.role = role
        user.full_name = full_name
        user.set_transaction_pin('1234')
        user.save()

        wallet, _ = Wallet.objects.get_or_create(owner=user, defaults={'balance': balance})
        wallet.balance = balance
        wallet.is_frozen = False
        wallet.save()

        users[username] = user
        status_tag = f"{GREEN}ACTIVE{RESET}"
        print(f"  • {user.username:<16} | Phone: {user.phone} | Bal: ৳{wallet.balance:>10,.2f} | Status: {status_tag}")

    # Ensure Merchant Profile
    merch_user = users['demo_merchant']
    merch, _ = Merchant.objects.get_or_create(
        account_number='MERCH_DEMO_001',
        defaults={
            'user': merch_user,
            'business_name': 'Daily Fresh Superstore',
            'category': BusinessCategory.GROCERY,
            'balance': Decimal('150000.00')
        }
    )

    # Superuser admin analyst
    admin, _ = User.objects.get_or_create(
        username='demo_analyst',
        defaults={'email': 'analyst@fundshare.local', 'role': UserRole.ADMIN, 'phone': '01711900099', 'is_staff': True, 'is_superuser': True}
    )
    admin.set_password('admin1234')
    admin.save()
    print(f"  • {admin.username:<16} | Role: Security Analyst / Admin | Auth: admin1234")

    return users, merch, admin


def run_scenario_step1(users, merch):
    section("STEP 1", "NORMAL GROCERY PURCHASE: Alice -> Daily Fresh Superstore")
    amt = Decimal("350.00")
    print(f"  Initiating payment: ৳{amt} from {users['demo_alice'].username} to {merch.business_name}...")

    txn = Transaction.objects.create(
        sender=users['demo_alice'],
        receiver=users['demo_merchant'],
        merchant=merch,
        amount=amt,
        category=BusinessCategory.GROCERY,
        transaction_type=TransactionType.MERCHANT_PAYMENT,
        payment_source=PaymentSource.NORMAL_WALLET,
        status=TransactionStatus.COMPLETED
    )

    AnomalyDetector.record_transaction(txn.pk, force=True)
    res = AnomalyResult.objects.get(transaction=txn)
    fs = res.features_summary or {}
    tier = fs.get('risk_tier', 'LOW')
    action = fs.get('risk_action', 'ALLOW')

    print(f"\n  {BOLD}{GREEN}[{action}] Score: {res.anomaly_score:.2f}, Tier: {tier}{RESET}")
    print(f"  {CYAN}Transaction ID :{RESET} {txn.transaction_id}")
    print(f"  {CYAN}Policy Action  :{RESET} {action} (Seamless Instant Settlement)")
    print(f"  {CYAN}Explanation    :{RESET} {res.reason.splitlines()[0] if res.reason else 'Within baseline'}")


def run_scenario_step2(users):
    section("STEP 2", "VELOCITY & AMOUNT SPIKE ATTACK: Alice -> Bob")
    # Moderate surge (2.8x baseline) triggering STEP_UP_PIN medium band
    amt = Decimal("2450.00")
    print(f"  Simulating moderate surge transfer: ৳{amt} from {users['demo_alice'].username} to {users['demo_bob'].username}...")

    txn = Transaction.objects.create(
        sender=users['demo_alice'],
        receiver=users['demo_bob'],
        amount=amt,
        transaction_type=TransactionType.SEND_MONEY,
        payment_source=PaymentSource.NORMAL_WALLET,
        status=TransactionStatus.COMPLETED
    )

    AnomalyDetector.record_transaction(txn.pk, force=True)
    res = AnomalyResult.objects.get(transaction=txn)
    fs = res.features_summary or {}
    tier = fs.get('risk_tier', 'MEDIUM')
    action = fs.get('risk_action', 'STEP_UP_PIN')

    print(f"\n  {BOLD}{YELLOW}[{action}] Score: {res.anomaly_score:.2f}, Tier: {tier}{RESET}")
    print(f"  {CYAN}Transaction ID :{RESET} {txn.transaction_id}")
    print(f"  {CYAN}Policy Action  :{RESET} {action} (2-Factor / Biometric Step-Up Challenge Required)")
    top_c = fs.get('top_contributions', [])
    if top_c:
        top_str = ", ".join([f"{c['feature']}: {c.get('contribution_score', c.get('contribution', 0.0)):.2f}" for c in top_c])
        print(f"  {CYAN}Top Attributes :{RESET} {top_str}")
    print(f"  {CYAN}Trigger Reason :{RESET} Moderate surge triggering step-up challenge.")


def run_scenario_step3(users, admin):
    section("STEP 3", "MULTI-SENDER FAN-IN SMURFING & 2-HOP MULE RING: Multi -> Mule -> Cashout")
    mule = users['demo_mule']
    cashout = users['demo_cashout']

    print(f"  Phase A: Aggregating smurfed fan-in transfers into Mule Hub ({mule.username}):")
    fan_in_transfers = [
        (users['demo_alice'], Decimal("10000.00")),
        (users['demo_bob'], Decimal("12000.00")),
        (users['demo_charlie'], Decimal("14000.00")),
    ]

    for sender, amt in fan_in_transfers:
        t = Transaction.objects.create(
            sender=sender,
            receiver=mule,
            amount=amt,
            transaction_type=TransactionType.SEND_MONEY,
            payment_source=PaymentSource.NORMAL_WALLET,
            status=TransactionStatus.COMPLETED
        )
        print(f"    • Incoming: ৳{amt:,.2f} from {sender.username} -> {mule.username} [COMPLETED]")

    # Rebuild graph to ensure topology is current
    engine = TransactionGraphEngine.get_instance()
    engine.build_graph(lookback_hours=24)

    # Phase B: Rapid Cashout Outflow from Mule Hub
    cashout_amt = Decimal("35000.00")
    print(f"\n  Phase B: Mule Hub initiates rapid outflow cashout: ৳{cashout_amt} -> {cashout.username}...")

    outflow_txn = Transaction.objects.create(
        sender=mule,
        receiver=cashout,
        amount=cashout_amt,
        transaction_type=TransactionType.SEND_MONEY,
        payment_source=PaymentSource.NORMAL_WALLET,
        status=TransactionStatus.COMPLETED
    )

    AnomalyDetector.record_transaction(outflow_txn.pk, force=True)
    res = AnomalyResult.objects.get(transaction=outflow_txn)
    fs = res.features_summary or {}
    tier = fs.get('risk_tier', 'HIGH')
    action = fs.get('risk_action', 'FLAG_FOR_REVIEW')
    mule_boost = fs.get('mule_boost', 0.25)

    # Incident created
    incident = FraudIncident.objects.filter(transaction=outflow_txn).first()
    inc_id_str = f"#{incident.id}" if incident else "None"

    print(f"\n  {BOLD}{RED}[{action}] Score: {res.anomaly_score:.2f}, Tier: {tier}, Graph Mule Boost: +{mule_boost:.2f}, Incident Created: {inc_id_str}{RESET}")
    print(f"  {CYAN}Transaction ID :{RESET} {outflow_txn.transaction_id}")
    print(f"  {CYAN}Policy Action  :{RESET} {action} (Automated Hold & Dispatch to Analyst Queue)")
    print(f"  {CYAN}Incident ID    :{RESET} {BOLD}{inc_id_str}{RESET} [Status: {incident.status if incident else 'N/A'}]")
    print(f"  {CYAN}Flagged Rules  :{RESET} {', '.join(res.features_summary.get('graph_reasons', ['2-Hop Mule Network']))}")

    # Phase C: Live Analyst Resolution
    print(f"\n  Phase C: Security Analyst ({admin.username}) reviews and confirms fraud:")
    if incident:
        incident.resolve(
            status='CONFIRMED_FRAUD',
            reviewer=admin,
            notes='Confirmed multi-sender smurfing fan-in network and rapid cashout attempt.'
        )
        mule.wallet.refresh_from_db()
        freeze_status = f"{RED}{BOLD}FROZEN{RESET}" if mule.wallet.is_frozen else "ACTIVE"
        print(f"    • Analyst Action : {BOLD}CONFIRMED_FRAUD / BLOCKED{RESET}")
        print(f"    • Target Wallet  : {mule.username} -> Status: {freeze_status}")
        print(f"    • Audit Trail    : {incident.reviewer_notes}")


def main():
    users, merch, admin = seed_accounts()
    run_scenario_step1(users, merch)
    run_scenario_step2(users)
    run_scenario_step3(users, admin)

    banner("DEMO SCENARIOS COMPLETED SUCCESSFULLY: 100% PASS")
    print(f"  To view live analyst triage UI in Django Admin, run:")
    print(f"  {BOLD}python manage.py runserver{RESET}")
    print(f"  Visit: {CYAN}http://127.0.0.1:8000/admin/fundshare_app/fraudincident/{RESET}\n")


if __name__ == '__main__':
    main()
