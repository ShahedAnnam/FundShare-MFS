"""
FUNDShare - Synthetic Historical Dataset Generator
Generates realistic financial behavior dataset for ML anomaly detection,
budget forecasting, and AI financial coach evaluation.

NOTICE: SYNTHETIC DATA — NOT REAL UPAY CUSTOMER DATA.
"""

import os
import csv
import json
import random
import datetime
from decimal import Decimal, ROUND_HALF_UP
from collections import defaultdict

# Fixed seed for complete reproducibility
RANDOM_SEED = 2026
random.seed(RANDOM_SEED)

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "synthetic")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 180-day time window: April 11, 2026 to October 7, 2026
START_DATE = datetime.datetime(2026, 4, 11, 8, 0, 0)
END_DATE = datetime.datetime(2026, 10, 7, 10, 0, 0)
TOTAL_DAYS = (END_DATE - START_DATE).days

def quantize(val):
    if isinstance(val, (int, float, str)):
        val = Decimal(str(val))
    return val.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

# Business categories matching FUNDShare repository
CATEGORIES = [
    "Grocery", "Medicine", "Treatment", "Education", "Electricity",
    "Restaurant/Food", "Transport", "Rent", "Shopping", "Other"
]

PURPOSE_TO_CATEGORIES = {
    "Grocery": ["Grocery"],
    "Medical": ["Medicine", "Treatment"],
    "Dining": ["Restaurant/Food"],
    "Bills & Utilities": ["Electricity", "Rent"],
    "Education": ["Education"],
    "Transport": ["Transport"],
    "Shopping": ["Shopping"],
    "Emergency": [],  # unrestricted
    "Other": [],      # unrestricted
}

# 30 Synthetic Merchants across all categories
MERCHANTS_DATA = [
    {"id": 1, "name": "Agora Super Shop", "category": "Grocery", "acc": "AGR-1001", "phone": "01720000001", "address": "Gulshan 2, Dhaka"},
    {"id": 2, "name": "Shwapno Superstore", "category": "Grocery", "acc": "SHW-1002", "phone": "01720000002", "address": "Dhanmondi 27, Dhaka"},
    {"id": 3, "name": "Unimart Hypermarket", "category": "Grocery", "acc": "UNI-1003", "phone": "01720000003", "address": "Chef's Table, Gulshan, Dhaka"},
    {"id": 4, "name": "Meena Bazar", "category": "Grocery", "acc": "MNB-1004", "phone": "01720000004", "address": "Uttara Sector 3, Dhaka"},
    {"id": 5, "name": "Chaldal Grocery Express", "category": "Grocery", "acc": "CHL-1005", "phone": "01720000005", "address": "Banasree, Dhaka"},
    {"id": 6, "name": "Karwan Bazar Wholesale", "category": "Grocery", "acc": "KBW-1006", "phone": "01720000006", "address": "Karwan Bazar, Dhaka"},
    
    {"id": 7, "name": "Labaid Pharmacy", "category": "Medicine", "acc": "LAB-2001", "phone": "01720000007", "address": "Dhanmondi, Dhaka"},
    {"id": 8, "name": "Tamanna Pharmacy", "category": "Medicine", "acc": "TAM-2002", "phone": "01720000008", "address": "Mirpur 10, Dhaka"},
    {"id": 9, "name": "Green Life Model Pharmacy", "category": "Medicine", "acc": "GLP-2003", "phone": "01720000009", "address": "Green Road, Dhaka"},
    {"id": 10, "name": "Square Hospital Pharmacy", "category": "Medicine", "acc": "SQP-2004", "phone": "01720000010", "address": "Panthapath, Dhaka"},
    
    {"id": 11, "name": "Square Hospital Diagnostic", "category": "Treatment", "acc": "SQR-3001", "phone": "01720000011", "address": "Panthapath, Dhaka"},
    {"id": 12, "name": "Evercare Hospital Lab", "category": "Treatment", "acc": "EVR-3002", "phone": "01720000012", "address": "Bashundhara R/A, Dhaka"},
    {"id": 13, "name": "Popular Diagnostic Centre", "category": "Treatment", "acc": "POP-3003", "phone": "01720000013", "address": "Shantinagar, Dhaka"},
    
    {"id": 14, "name": "Scholastica School", "category": "Education", "acc": "SCH-4001", "phone": "01720000014", "address": "Uttara Sector 1, Dhaka"},
    {"id": 15, "name": "Sunnydale Academy", "category": "Education", "acc": "SUN-4002", "phone": "01720000015", "address": "Dhanmondi 6, Dhaka"},
    {"id": 16, "name": "Daffodil University Tuition", "category": "Education", "acc": "DIU-4003", "phone": "01720000016", "address": "Ashulia, Dhaka"},
    {"id": 17, "name": "Mastermind School", "category": "Education", "acc": "MST-4004", "phone": "01720000017", "address": "Dhanmondi 12, Dhaka"},
    
    {"id": 18, "name": "DESCO Prepaid Utility", "category": "Electricity", "acc": "DSC-5001", "phone": "01720000018", "address": "Nikunja 2, Dhaka"},
    {"id": 19, "name": "DPDC Electricity Payment", "category": "Electricity", "acc": "DPD-5002", "phone": "01720000019", "address": "Motijheel C/A, Dhaka"},
    {"id": 20, "name": "Link3 Internet Utilities", "category": "Electricity", "acc": "LNK-5003", "phone": "01720000020", "address": "Mohakhali DOHS, Dhaka"},
    
    {"id": 21, "name": "Sultan's Dine Kacchi", "category": "Restaurant/Food", "acc": "SLT-6001", "phone": "01720000021", "address": "Dhanmondi, Dhaka"},
    {"id": 22, "name": "Star Kabab & Restaurant", "category": "Restaurant/Food", "acc": "STR-6002", "phone": "01720000022", "address": "Banani 11, Dhaka"},
    {"id": 23, "name": "Kacchi Bhai Biryani", "category": "Restaurant/Food", "acc": "KCH-6003", "phone": "01720000023", "address": "Bashundhara Gate, Dhaka"},
    {"id": 24, "name": "Takeout Gourmet Burgers", "category": "Restaurant/Food", "acc": "TKO-6004", "phone": "01720000024", "address": "Mirpur 2, Dhaka"},
    
    {"id": 25, "name": "Shohoz Interdistrict Ride", "category": "Transport", "acc": "SHZ-7001", "phone": "01720000025", "address": "Kawran Bazar, Dhaka"},
    {"id": 26, "name": "Uber Bangladesh Mobility", "category": "Transport", "acc": "UBR-7002", "phone": "01720000026", "address": "Gulshan 1, Dhaka"},
    {"id": 27, "name": "Pathao Transportation", "category": "Transport", "acc": "PTH-7003", "phone": "01720000027", "address": "Niketon, Dhaka"},
    
    {"id": 28, "name": "Eastern Housing Rental", "category": "Rent", "acc": "EST-8001", "phone": "01720000028", "address": "Kakrail, Dhaka"},
    {"id": 29, "name": "Rangs Living Rent", "category": "Rent", "acc": "RNG-8002", "phone": "01720000029", "address": "Tejgaon I/A, Dhaka"},
    
    {"id": 30, "name": "Aarong Lifestyle Retail", "category": "Shopping", "acc": "AAR-9001", "phone": "01720000030", "address": "Lalmatia, Dhaka"},
    {"id": 31, "name": "General Utility & Services", "category": "Other", "acc": "OTH-9002", "phone": "01720000031", "address": "Motijheel C/A, Dhaka"},
    {"id": 32, "name": "Beximco Digital Services", "category": "Other", "acc": "OTH-9003", "phone": "01720000032", "address": "Gulshan 1, Dhaka"}
]

for m in MERCHANTS_DATA:
    m["balance"] = Decimal('50000.00')

MERCHANTS_BY_CAT = defaultdict(list)
for m in MERCHANTS_DATA:
    MERCHANTS_BY_CAT[m["category"]].append(m)

# 25 Synthetic Customer User Specifications
USER_SPECS = [
    # 9 Salaried Family Heads (High/Medium Income, Multiple Funds, Issues FamilyPass)
    {"id": 1, "username": "tariq_rahman", "name": "Tariq Rahman", "phone": "01710000001", "profile": "Salaried Family Head", "salary": 85000, "discipline": "STRICT", "funds": [("Grocery", 18000), ("Electricity", 4500), ("Education", 12000), ("Medicine", 6000)], "issues_fp": True},
    {"id": 2, "username": "anisul_haque", "name": "Anisul Haque", "phone": "01710000002", "profile": "Salaried Family Head", "salary": 95000, "discipline": "MODERATE", "funds": [("Grocery", 20000), ("Rent", 25000), ("Electricity", 5000), ("Medicine", 5000)], "issues_fp": True},
    {"id": 3, "username": "farhan_kabir", "name": "Farhan Kabir", "phone": "01710000003", "profile": "Salaried Family Head", "salary": 78000, "discipline": "STRICT", "funds": [("Grocery", 16000), ("Education", 14000), ("Electricity", 4000), ("Transport", 5000)], "issues_fp": True},
    {"id": 4, "username": "mahbub_alam", "name": "Mahbub Alam", "phone": "01710000004", "profile": "Salaried Family Head", "salary": 110000, "discipline": "MODERATE", "funds": [("Grocery", 22000), ("Rent", 30000), ("Education", 16000), ("Medicine", 8000)], "issues_fp": True},
    {"id": 5, "username": "kamrul_hasan", "name": "Kamrul Hasan", "phone": "01710000005", "profile": "Salaried Family Head", "salary": 72000, "discipline": "STRICT", "funds": [("Grocery", 15000), ("Electricity", 4200), ("Medicine", 6000), ("Education", 10000)], "issues_fp": True},
    {"id": 6, "username": "zahid_iqbal", "name": "Zahid Iqbal", "phone": "01710000006", "profile": "Salaried Family Head", "salary": 88000, "discipline": "MODERATE", "funds": [("Grocery", 18000), ("Rent", 24000), ("Electricity", 4500), ("Shopping", 6000)], "issues_fp": False},
    {"id": 7, "username": "delwar_hossain", "name": "Delwar Hossain", "phone": "01710000007", "profile": "Salaried Family Head", "salary": 68000, "discipline": "STRICT", "funds": [("Grocery", 15000), ("Electricity", 3800), ("Medicine", 5000), ("Transport", 4000)], "issues_fp": False},
    {"id": 8, "username": "saifur_rehman", "name": "Saifur Rehman", "phone": "01710000008", "profile": "Salaried Family Head", "salary": 105000, "discipline": "MODERATE", "funds": [("Grocery", 20000), ("Education", 18000), ("Electricity", 5500), ("Treatment", 10000)], "issues_fp": False},
    {"id": 9, "username": "shahidul_islam", "name": "Shahidul Islam", "phone": "01710000009", "profile": "Salaried Family Head", "salary": 90000, "discipline": "STRICT", "funds": [("Grocery", 19000), ("Rent", 22000), ("Electricity", 4000), ("Medicine", 6000)], "issues_fp": False},
    
    # 6 Students / Dependents (Low/Moderate allowance, Receives FamilyPass, Focused funds)
    {"id": 10, "username": "samiul_tariq", "name": "Samiul Tariq", "phone": "01710000010", "profile": "Student", "salary": 12000, "discipline": "MODERATE", "funds": [("Education", 5000), ("Transport", 3000)], "issues_fp": False},
    {"id": 11, "username": "tanvir_haque", "name": "Tanvir Haque", "phone": "01710000011", "profile": "Student", "salary": 10000, "discipline": "IMPULSIVE", "funds": [("Education", 4000), ("Restaurant/Food", 3000)], "issues_fp": False},
    {"id": 12, "username": "rafid_kabir", "name": "Rafid Kabir", "phone": "01710000012", "profile": "Student", "salary": 11000, "discipline": "MODERATE", "funds": [("Education", 4500), ("Transport", 2500)], "issues_fp": False},
    {"id": 13, "username": "nahian_hasan", "name": "Nahian Hasan", "phone": "01710000013", "profile": "Student", "salary": 9000, "discipline": "STRICT", "funds": [("Education", 4000), ("Transport", 2000)], "issues_fp": False},
    {"id": 14, "username": "sakib_chowdhury", "name": "Sakib Chowdhury", "phone": "01710000014", "profile": "Student", "salary": 14000, "discipline": "IMPULSIVE", "funds": [("Restaurant/Food", 5000), ("Shopping", 4000)], "issues_fp": False},
    {"id": 15, "username": "zubair_ahmed", "name": "Zubair Ahmed", "phone": "01710000015", "profile": "Student", "salary": 10500, "discipline": "MODERATE", "funds": [("Education", 4500), ("Transport", 2500)], "issues_fp": False},
    
    # 4 Moderate Family Members / Homemakers (Receives FamilyPass for Household items)
    {"id": 16, "username": "nasrin_rahman", "name": "Nasrin Rahman", "phone": "01710000016", "profile": "Moderate Family Member", "salary": 20000, "discipline": "STRICT", "funds": [("Grocery", 8000), ("Medicine", 4000)], "issues_fp": False},
    {"id": 17, "username": "farzana_haque", "name": "Farzana Haque", "phone": "01710000017", "profile": "Moderate Family Member", "salary": 22000, "discipline": "STRICT", "funds": [("Grocery", 9000), ("Medicine", 4500)], "issues_fp": False},
    {"id": 18, "username": "rumana_alam", "name": "Rumana Alam", "phone": "01710000018", "profile": "Moderate Family Member", "salary": 25000, "discipline": "MODERATE", "funds": [("Grocery", 10000), ("Shopping", 5000)], "issues_fp": False},
    {"id": 19, "username": "sadia_chowdhury", "name": "Sadia Chowdhury", "phone": "01710000019", "profile": "Moderate Family Member", "salary": 28000, "discipline": "MODERATE", "funds": [("Grocery", 12000), ("Medicine", 5000)], "issues_fp": False},
    
    # 3 High-Spending Professionals (High Income, High Volume & Limit)
    {"id": 20, "username": "asif_chowdhury", "name": "Asif Chowdhury", "phone": "01710000020", "profile": "High-Spending User", "salary": 185000, "discipline": "MODERATE", "funds": [("Grocery", 28000), ("Rent", 40000), ("Shopping", 20000), ("Treatment", 15000)], "issues_fp": True},
    {"id": 21, "username": "tanzeem_morshed", "name": "Tanzeem Morshed", "phone": "01710000021", "profile": "High-Spending User", "salary": 210000, "discipline": "MODERATE", "funds": [("Grocery", 32000), ("Rent", 45000), ("Restaurant/Food", 18000), ("Shopping", 22000)], "issues_fp": False},
    {"id": 22, "username": "nafis_fuad", "name": "Nafis Fuad", "phone": "01710000022", "profile": "High-Spending User", "salary": 165000, "discipline": "MODERATE", "funds": [("Grocery", 25000), ("Treatment", 20000), ("Education", 22000), ("Shopping", 15000)], "issues_fp": False},
    
    # 3 Impulsive Spenders (Irregular income, spikes, higher anomaly tendency)
    {"id": 23, "username": "shafiqul_huda", "name": "Shafiqul Huda", "phone": "01710000023", "profile": "Impulsive Spender", "salary": 65000, "discipline": "IMPULSIVE", "funds": [("Restaurant/Food", 12000), ("Shopping", 14000), ("Transport", 6000)], "issues_fp": True},
    {"id": 24, "username": "emon_khandaker", "name": "Emon Khandaker", "phone": "01710000024", "profile": "Impulsive Spender", "salary": 55000, "discipline": "IMPULSIVE", "funds": [("Restaurant/Food", 10000), ("Shopping", 11000), ("Transport", 5000)], "issues_fp": False},
    {"id": 25, "username": "arif_shariar", "name": "Arif Shariar", "phone": "01710000025", "profile": "Impulsive Spender", "salary": 70000, "discipline": "IMPULSIVE", "funds": [("Restaurant/Food", 13000), ("Shopping", 15000), ("Grocery", 10000)], "issues_fp": False},
]

# Configure 10 FamilyPass Delegations: Owner -> Member
FAMILY_PASS_CONFIGS = [
    {"id": 1, "owner_id": 1, "member_id": 10, "limit": 4500, "purpose": "Education", "cats": ["Education"], "action": "MERCHANT_PAYMENT", "label": "Tuition & Exam Allowance"},
    {"id": 2, "owner_id": 1, "member_id": 16, "limit": 9000, "purpose": "Grocery", "cats": ["Grocery"], "action": "MERCHANT_PAYMENT", "label": "Household Grocery Allowance"},
    {"id": 3, "owner_id": 2, "member_id": 11, "limit": 3500, "purpose": "Dining", "cats": ["Restaurant/Food"], "action": "MERCHANT_PAYMENT", "label": "Campus Food Allowance"},
    {"id": 4, "owner_id": 2, "member_id": 17, "limit": 10000, "purpose": "Grocery", "cats": ["Grocery"], "action": "MERCHANT_PAYMENT", "label": "Kitchen & Food Allowance"},
    {"id": 5, "owner_id": 3, "member_id": 12, "limit": 4000, "purpose": "Transport", "cats": ["Transport"], "action": "MERCHANT_PAYMENT", "label": "Commute & Transit Allowance"},
    {"id": 6, "owner_id": 4, "member_id": 18, "limit": 12000, "purpose": "Grocery", "cats": ["Grocery", "Medicine"], "action": "GROCERY_MEDICINE", "label": "Family Grocery & Pharmacy Allowance"},
    {"id": 7, "owner_id": 5, "member_id": 13, "limit": 3000, "purpose": "Education", "cats": ["Education"], "action": "MERCHANT_PAYMENT", "label": "Books & Study Materials"},
    {"id": 8, "owner_id": 20, "member_id": 14, "limit": 6000, "purpose": "Dining", "cats": ["Restaurant/Food"], "action": "MERCHANT_PAYMENT", "label": "Social & Campus Dining"},
    {"id": 9, "owner_id": 20, "member_id": 19, "limit": 15000, "purpose": "Grocery", "cats": ["Grocery"], "action": "MERCHANT_PAYMENT", "label": "Monthly Estate Groceries"},
    {"id": 10, "owner_id": 23, "member_id": 15, "limit": 3500, "purpose": "Transport", "cats": ["Transport"], "action": "MERCHANT_PAYMENT", "label": "Ride Share Allowance"},
]

def generate_dataset():
    print("Initializing FUNDShare synthetic financial simulation...")
    
    # Trackers for live state during simulation
    wallets = {}
    purpose_funds = {}
    family_passes = {}
    merchants = {m["id"]: dict(m) for m in MERCHANTS_DATA}
    for m in merchants.values():
        m["balance"] = Decimal('50000.00')

    # Initialize users & wallets
    fund_id_seq = 1
    user_funds_map = defaultdict(list)
    for u in USER_SPECS:
        init_balance = quantize(Decimal(str(u["salary"])) * Decimal('0.35'))
        wallets[u["id"]] = {
            "wallet_id": u["id"],
            "owner_id": u["id"],
            "balance": init_balance,
            "initial_balance": init_balance
        }
        # Create Purpose Funds for this user
        for cat, monthly_bgt in u["funds"]:
            pf = {
                "fund_id": fund_id_seq,
                "owner_id": u["id"],
                "name": f"{u['name'].split()[0]}'s {cat} Fund",
                "category": cat,
                "monthly_budget": quantize(monthly_bgt),
                "allocated_amount": Decimal('0.00'),
                "current_balance": Decimal('0.00'),
                "total_allocated": Decimal('0.00'),
                "total_spent": Decimal('0.00'),
                "status": "ACTIVE",
                "created_at": START_DATE.strftime("%Y-%m-%d %H:%M:%S")
            }
            purpose_funds[fund_id_seq] = pf
            user_funds_map[u["id"]].append(pf)
            fund_id_seq += 1

    # Initialize FamilyPasses
    for fp_cfg in FAMILY_PASS_CONFIGS:
        fp_id = fp_cfg["id"]
        family_passes[fp_id] = {
            "family_pass_id": fp_id,
            "owner_id": fp_cfg["owner_id"],
            "member_id": fp_cfg["member_id"],
            "limit_amount": quantize(fp_cfg["limit"]),
            "used_amount": Decimal('0.00'),
            "start_date": START_DATE.strftime("%Y-%m-%d"),
            "expiry_date": (END_DATE + datetime.timedelta(days=15)).strftime("%Y-%m-%d"),
            "allowed_action": fp_cfg["action"],
            "status": "ACTIVE",
            "purpose": fp_cfg["purpose"],
            "allowed_categories": fp_cfg["cats"],
            "purpose_label": fp_cfg["label"],
            "created_at": START_DATE.strftime("%Y-%m-%d %H:%M:%S")
        }

    # Simulation Collections
    all_transactions = []
    all_fp_activities = []
    all_items = []
    all_anomalies = []
    
    txn_id_counter = 1
    fp_activity_counter = 1
    item_counter = 1

    # User Target Transaction counts: between 102 and 119 per user
    user_target_counts = {}
    for u in USER_SPECS:
        # Realistic slight variation per user
        user_target_counts[u["id"]] = random.randint(104, 118)

    print(f"Total customers: {len(USER_SPECS)}")
    print(f"Target transaction volume: ~{sum(user_target_counts.values())} transactions across {TOTAL_DAYS} days.")

    # Day-by-Day Event Generation
    # Generates monthly salary cycles, allocations, bills, daily spending, FamilyPass spending, and controlled anomalies
    
    # Pre-map passes by member and owner
    passes_by_member = defaultdict(list)
    passes_by_owner = defaultdict(list)
    for fp in family_passes.values():
        passes_by_member[fp["member_id"]].append(fp)
        passes_by_owner[fp["owner_id"]].append(fp)

    # Simulation Loop across 180 days
    current_time = START_DATE
    
    # Store daily scheduled events
    for day_idx in range(TOTAL_DAYS):
        day_date = START_DATE + datetime.timedelta(days=day_idx)
        is_weekend = day_date.weekday() in (4, 5) # Friday, Saturday in Bangladesh
        is_month_start = day_date.day == 1 or day_idx == 0

        # 1. Monthly Cycle: Inflows (Salary / Allowance)
        if is_month_start:
            for u in USER_SPECS:
                u_id = u["id"]
                salary_amt = quantize(u["salary"] * (1.0 + random.uniform(-0.03, 0.03)))
                salary_time = day_date.replace(hour=random.randint(9, 11), minute=random.randint(0, 59))
                
                w = wallets[u_id]
                w_before = w["balance"]
                w["balance"] += salary_amt
                w_after = w["balance"]

                txn_code = f"TXN-{salary_time.strftime('%Y%m%d')}-{txn_id_counter:06d}"
                txn_id_counter += 1
                
                all_transactions.append({
                    "transaction_id": txn_code,
                    "sender_id": u_id,
                    "receiver_id": u_id,
                    "merchant_id": "",
                    "timestamp": salary_time.strftime("%Y-%m-%d %H:%M:%S"),
                    "amount": salary_amt,
                    "transaction_type": "CASH_IN",
                    "payment_source": "NORMAL_WALLET",
                    "purpose_fund_id": "",
                    "family_pass_id": "",
                    "category": "Deposit",
                    "status": "COMPLETED",
                    "rejection_reason": "",
                    "reference": "Monthly Salary / Bank Add Money",
                    "wallet_balance_before": w_before,
                    "wallet_balance_after": w_after,
                    "fund_balance_before": "",
                    "fund_balance_after": "",
                    "family_pass_limit_remaining_before": "",
                    "family_pass_limit_remaining_after": "",
                    "metadata_json": json.dumps({"source": "Bank Deposit", "ground_truth_anomaly": False}),
                    "is_itemized": False
                })

                # Purpose Fund Monthly Allocations from Wallet
                for pf in user_funds_map[u_id]:
                    alloc_amt = quantize(pf["monthly_budget"])
                    if w["balance"] >= alloc_amt:
                        w_b = w["balance"]
                        w["balance"] -= alloc_amt
                        w_a = w["balance"]

                        f_b = pf["current_balance"]
                        pf["current_balance"] += alloc_amt
                        pf["allocated_amount"] += alloc_amt
                        pf["total_allocated"] += alloc_amt
                        f_a = pf["current_balance"]

                        alloc_time = salary_time + datetime.timedelta(minutes=random.randint(5, 30))
                        t_code = f"TXN-{alloc_time.strftime('%Y%m%d')}-{txn_id_counter:06d}"
                        txn_id_counter += 1

                        all_transactions.append({
                            "transaction_id": t_code,
                            "sender_id": u_id,
                            "receiver_id": "",
                            "merchant_id": "",
                            "timestamp": alloc_time.strftime("%Y-%m-%d %H:%M:%S"),
                            "amount": alloc_amt,
                            "transaction_type": "FUND_ALLOCATION",
                            "payment_source": "NORMAL_WALLET",
                            "purpose_fund_id": pf["fund_id"],
                            "family_pass_id": "",
                            "category": pf["category"],
                            "status": "COMPLETED",
                            "rejection_reason": "",
                            "reference": f"Allocated ৳{alloc_amt} to {pf['name']}",
                            "wallet_balance_before": w_b,
                            "wallet_balance_after": w_a,
                            "fund_balance_before": f_b,
                            "fund_balance_after": f_a,
                            "family_pass_limit_remaining_before": "",
                            "family_pass_limit_remaining_after": "",
                            "metadata_json": json.dumps({"fund_name": pf["name"], "ground_truth_anomaly": False}),
                            "is_itemized": False
                        })

            # Refresh monthly used amounts on FamilyPasses each month
            if day_idx > 0 and day_date.day == 1:
                for fp in family_passes.values():
                    fp["used_amount"] = Decimal('0.00')

        # 2. Monthly Bills (Rent on day 4-7, Electricity on day 10-14)
        for u in USER_SPECS:
            u_id = u["id"]
            w = wallets[u_id]

            # Rent Bill (if user has rent fund or head/high profile)
            if day_date.day == 5 and u["profile"] in ("Salaried Family Head", "High-Spending User"):
                rent_fund = next((f for f in user_funds_map[u_id] if f["category"] == "Rent"), None)
                rent_amt = quantize(Decimal(str(random.randint(20000, 35000) if u["profile"] == "High-Spending User" else random.randint(18000, 25000))))
                bill_time = day_date.replace(hour=random.randint(11, 16), minute=random.randint(0, 59))

                if rent_fund and rent_fund["current_balance"] >= rent_amt:
                    # Purpose fund payment
                    fb = rent_fund["current_balance"]
                    rent_fund["current_balance"] -= rent_amt
                    rent_fund["total_spent"] += rent_amt
                    fa = rent_fund["current_balance"]

                    m = random.choice(MERCHANTS_BY_CAT["Rent"])
                    m["balance"] += rent_amt

                    t_code = f"TXN-{bill_time.strftime('%Y%m%d')}-{txn_id_counter:06d}"
                    txn_id_counter += 1

                    all_transactions.append({
                        "transaction_id": t_code,
                        "sender_id": u_id,
                        "receiver_id": "",
                        "merchant_id": m["id"],
                        "timestamp": bill_time.strftime("%Y-%m-%d %H:%M:%S"),
                        "amount": rent_amt,
                        "transaction_type": "MERCHANT_PAYMENT",
                        "payment_source": "PURPOSE_FUND",
                        "purpose_fund_id": rent_fund["fund_id"],
                        "family_pass_id": "",
                        "category": "Rent",
                        "status": "COMPLETED",
                        "rejection_reason": "",
                        "reference": f"Monthly Apartment Rent to {m['name']}",
                        "wallet_balance_before": w["balance"],
                        "wallet_balance_after": w["balance"],
                        "fund_balance_before": fb,
                        "fund_balance_after": fa,
                        "family_pass_limit_remaining_before": "",
                        "family_pass_limit_remaining_after": "",
                        "metadata_json": json.dumps({"merchant": m["name"], "ground_truth_anomaly": False}),
                        "is_itemized": False
                    })
                elif w["balance"] >= rent_amt:
                    # Normal wallet bill payment
                    wb = w["balance"]
                    w["balance"] -= rent_amt
                    wa = w["balance"]

                    t_code = f"TXN-{bill_time.strftime('%Y%m%d')}-{txn_id_counter:06d}"
                    txn_id_counter += 1

                    all_transactions.append({
                        "transaction_id": t_code,
                        "sender_id": u_id,
                        "receiver_id": "",
                        "merchant_id": "",
                        "timestamp": bill_time.strftime("%Y-%m-%d %H:%M:%S"),
                        "amount": rent_amt,
                        "transaction_type": "BILL_PAYMENT",
                        "payment_source": "NORMAL_WALLET",
                        "purpose_fund_id": "",
                        "family_pass_id": "",
                        "category": "Rent",
                        "status": "COMPLETED",
                        "rejection_reason": "",
                        "reference": "Monthly Housing Rental Bill Payment",
                        "wallet_balance_before": wb,
                        "wallet_balance_after": wa,
                        "fund_balance_before": "",
                        "fund_balance_after": "",
                        "family_pass_limit_remaining_before": "",
                        "family_pass_limit_remaining_after": "",
                        "metadata_json": json.dumps({"provider": "Eastern Housing Rental", "bill_type": "Housing", "account_number": "EHR-88219", "ground_truth_anomaly": False}),
                        "is_itemized": False
                    })

            # Electricity Bill (Monthly around day 12)
            if day_date.day == 12 and u["profile"] in ("Salaried Family Head", "High-Spending User", "Moderate Family Member"):
                elec_amt = quantize(Decimal(str(random.randint(2200, 4800))))
                elec_fund = next((f for f in user_funds_map[u_id] if f["category"] == "Electricity"), None)
                b_time = day_date.replace(hour=random.randint(14, 18), minute=random.randint(0, 59))

                if elec_fund and elec_fund["current_balance"] >= elec_amt:
                    m = random.choice(MERCHANTS_BY_CAT["Electricity"])
                    fb = elec_fund["current_balance"]
                    elec_fund["current_balance"] -= elec_amt
                    elec_fund["total_spent"] += elec_amt
                    fa = elec_fund["current_balance"]
                    m["balance"] += elec_amt

                    t_code = f"TXN-{b_time.strftime('%Y%m%d')}-{txn_id_counter:06d}"
                    txn_id_counter += 1

                    all_transactions.append({
                        "transaction_id": t_code,
                        "sender_id": u_id,
                        "receiver_id": "",
                        "merchant_id": m["id"],
                        "timestamp": b_time.strftime("%Y-%m-%d %H:%M:%S"),
                        "amount": elec_amt,
                        "transaction_type": "MERCHANT_PAYMENT",
                        "payment_source": "PURPOSE_FUND",
                        "purpose_fund_id": elec_fund["fund_id"],
                        "family_pass_id": "",
                        "category": "Electricity",
                        "status": "COMPLETED",
                        "rejection_reason": "",
                        "reference": f"Electricity recharge at {m['name']}",
                        "wallet_balance_before": w["balance"],
                        "wallet_balance_after": w["balance"],
                        "fund_balance_before": fb,
                        "fund_balance_after": fa,
                        "family_pass_limit_remaining_before": "",
                        "family_pass_limit_remaining_after": "",
                        "metadata_json": json.dumps({"provider": m["name"], "ground_truth_anomaly": False}),
                        "is_itemized": False
                    })
                elif w["balance"] >= elec_amt:
                    wb = w["balance"]
                    w["balance"] -= elec_amt
                    wa = w["balance"]

                    t_code = f"TXN-{b_time.strftime('%Y%m%d')}-{txn_id_counter:06d}"
                    txn_id_counter += 1

                    all_transactions.append({
                        "transaction_id": t_code,
                        "sender_id": u_id,
                        "receiver_id": "",
                        "merchant_id": "",
                        "timestamp": b_time.strftime("%Y-%m-%d %H:%M:%S"),
                        "amount": elec_amt,
                        "transaction_type": "BILL_PAYMENT",
                        "payment_source": "NORMAL_WALLET",
                        "purpose_fund_id": "",
                        "family_pass_id": "",
                        "category": "Electricity",
                        "status": "COMPLETED",
                        "rejection_reason": "",
                        "reference": "DESCO Prepaid Meter Utility Recharge",
                        "wallet_balance_before": wb,
                        "wallet_balance_after": wa,
                        "fund_balance_before": "",
                        "fund_balance_after": "",
                        "family_pass_limit_remaining_before": "",
                        "family_pass_limit_remaining_after": "",
                        "metadata_json": json.dumps({"provider": "DESCO", "bill_type": "Electricity", "account_number": "MTR-99410", "ground_truth_anomaly": False}),
                        "is_itemized": False
                    })

        # 3. Daily Transactions across users:
        # A mix of Purpose Fund spend (~40%), FamilyPass spend (~25%), Normal wallet (~15%), P2P/recharge (~10%)
        # Pick 10-18 users each day to perform activities
        active_users_today = random.sample(USER_SPECS, k=random.randint(12, 18))
        
        for u in active_users_today:
            u_id = u["id"]
            w = wallets[u_id]
            u_funds = user_funds_map[u_id]
            u_passes = passes_by_member[u_id]

            # Decide transaction count for this user on this day (1 or 2)
            day_txns = 1 if random.random() < 0.75 else 2
            
            for _ in range(day_txns):
                # Check if this user reached target count
                current_user_txns = sum(1 for t in all_transactions if t["sender_id"] == u_id)
                if current_user_txns >= user_target_counts[u_id]:
                    continue

                # Generate event timestamp
                hour = random.choices(
                    [8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23],
                    weights=[4, 6, 8, 9, 7, 7, 6, 8, 9, 10, 12, 14, 13, 10, 5, 2]
                )[0]
                txn_time = day_date.replace(hour=hour, minute=random.randint(0, 59), second=random.randint(0, 59))

                # Decide Payment Mode based on profile & availability
                # Priority:
                # If user has FamilyPass and needs food/grocery/transport: ~45% chance to use FamilyPass
                # Else if user has matching PurposeFund: ~50% chance to use PurposeFund
                # Else: Normal Wallet
                use_fp = False
                selected_fp = None
                if u_passes and random.random() < 0.45:
                    available_fps = [fp for fp in u_passes if (fp["limit_amount"] - fp["used_amount"]) > Decimal('100.00')]
                    if available_fps:
                        selected_fp = random.choice(available_fps)
                        # Owner wallet must have balance
                        owner_w = wallets[selected_fp["owner_id"]]
                        if owner_w["balance"] > Decimal('300.00'):
                            use_fp = True

                if use_fp and selected_fp:
                    # FAMILYPASS SPENDING
                    owner_w = wallets[selected_fp["owner_id"]]
                    fp_rem = selected_fp["limit_amount"] - selected_fp["used_amount"]
                    
                    # Target category from allowed categories
                    allowed_c = selected_fp["allowed_categories"]
                    target_cat = random.choice(allowed_c) if allowed_c else "Grocery"
                    m = random.choice(MERCHANTS_BY_CAT[target_cat])
                    
                    # Amount tailored to category
                    if target_cat == "Grocery":
                        spend_amt = quantize(random.gauss(650, 180))
                    elif target_cat == "Restaurant/Food":
                        spend_amt = quantize(random.gauss(450, 120))
                    elif target_cat == "Transport":
                        spend_amt = quantize(random.gauss(220, 60))
                    elif target_cat == "Education":
                        spend_amt = quantize(random.gauss(1200, 300))
                    else:
                        spend_amt = quantize(random.gauss(500, 150))
                    
                    spend_amt = max(Decimal('80.00'), min(spend_amt, fp_rem, owner_w["balance"]))
                    
                    if spend_amt > Decimal('50.00'):
                        # Atomic accounting
                        ow_before = owner_w["balance"]
                        owner_w["balance"] -= spend_amt
                        ow_after = owner_w["balance"]

                        rem_before = fp_rem
                        selected_fp["used_amount"] += spend_amt
                        rem_after = selected_fp["limit_amount"] - selected_fp["used_amount"]

                        m["balance"] += spend_amt

                        t_code = f"TXN-{txn_time.strftime('%Y%m%d')}-{txn_id_counter:06d}"
                        txn_id_counter += 1

                        # Itemization for groceries/restaurants
                        is_item = target_cat in ("Grocery", "Restaurant/Food") and random.random() < 0.35
                        
                        all_transactions.append({
                            "transaction_id": t_code,
                            "sender_id": u_id,
                            "receiver_id": "",
                            "merchant_id": m["id"],
                            "timestamp": txn_time.strftime("%Y-%m-%d %H:%M:%S"),
                            "amount": spend_amt,
                            "transaction_type": "MERCHANT_PAYMENT",
                            "payment_source": "FAMILY_PASS",
                            "purpose_fund_id": "",
                            "family_pass_id": selected_fp["family_pass_id"],
                            "category": target_cat,
                            "status": "COMPLETED",
                            "rejection_reason": "",
                            "reference": f"FamilyPass spending by {u['name']} at {m['name']}",
                            "wallet_balance_before": ow_before,
                            "wallet_balance_after": ow_after,
                            "fund_balance_before": "",
                            "fund_balance_after": "",
                            "family_pass_limit_remaining_before": rem_before,
                            "family_pass_limit_remaining_after": rem_after,
                            "metadata_json": json.dumps({"owner_id": selected_fp["owner_id"], "member_id": u_id, "merchant": m["name"], "ground_truth_anomaly": False}),
                            "is_itemized": is_item
                        })

                        # Activity record
                        all_fp_activities.append({
                            "activity_id": fp_activity_counter,
                            "family_pass_id": selected_fp["family_pass_id"],
                            "transaction_id": t_code,
                            "member_id": u_id,
                            "amount": spend_amt,
                            "remaining_limit_after": rem_after,
                            "timestamp": txn_time.strftime("%Y-%m-%d %H:%M:%S")
                        })
                        fp_activity_counter += 1

                        if is_item:
                            all_items.append({
                                "item_id": item_counter,
                                "transaction_id": t_code,
                                "name": f"{target_cat} Daily Essentials Pack",
                                "product_id": f"SKU-{random.randint(100, 999)}",
                                "quantity": Decimal('1.00'),
                                "unit_price": spend_amt,
                                "discount": Decimal('0.00'),
                                "tax": Decimal('0.00'),
                                "total": spend_amt
                            })
                            item_counter += 1

                elif u_funds and random.random() < 0.60:
                    # PURPOSE FUND SPENDING
                    # Pick a fund with available balance
                    usable_funds = [f for f in u_funds if f["current_balance"] > Decimal('100.00')]
                    if usable_funds:
                        chosen_fund = random.choice(usable_funds)
                        cat = chosen_fund["category"]
                        m = random.choice(MERCHANTS_BY_CAT[cat])

                        if cat == "Grocery":
                            spend_amt = quantize(random.gauss(850, 250))
                        elif cat == "Medicine":
                            spend_amt = quantize(random.gauss(420, 160))
                        elif cat == "Treatment":
                            spend_amt = quantize(random.gauss(2800, 900))
                        elif cat == "Education":
                            spend_amt = quantize(random.gauss(4500, 1200))
                        elif cat == "Restaurant/Food":
                            spend_amt = quantize(random.gauss(950, 350))
                        elif cat == "Transport":
                            spend_amt = quantize(random.gauss(320, 110))
                        elif cat == "Shopping":
                            spend_amt = quantize(random.gauss(1800, 600))
                        else:
                            spend_amt = quantize(random.gauss(600, 200))

                        spend_amt = max(Decimal('100.00'), min(spend_amt, chosen_fund["current_balance"]))
                        
                        if spend_amt > Decimal('50.00'):
                            fb = chosen_fund["current_balance"]
                            chosen_fund["current_balance"] -= spend_amt
                            chosen_fund["total_spent"] += spend_amt
                            fa = chosen_fund["current_balance"]

                            m["balance"] += spend_amt

                            t_code = f"TXN-{txn_time.strftime('%Y%m%d')}-{txn_id_counter:06d}"
                            txn_id_counter += 1

                            is_item = cat in ("Grocery", "Shopping") and random.random() < 0.35

                            all_transactions.append({
                                "transaction_id": t_code,
                                "sender_id": u_id,
                                "receiver_id": "",
                                "merchant_id": m["id"],
                                "timestamp": txn_time.strftime("%Y-%m-%d %H:%M:%S"),
                                "amount": spend_amt,
                                "transaction_type": "MERCHANT_PAYMENT",
                                "payment_source": "PURPOSE_FUND",
                                "purpose_fund_id": chosen_fund["fund_id"],
                                "family_pass_id": "",
                                "category": cat,
                                "status": "COMPLETED",
                                "rejection_reason": "",
                                "reference": f"Payment to {m['name']} via {chosen_fund['name']}",
                                "wallet_balance_before": w["balance"],
                                "wallet_balance_after": w["balance"],
                                "fund_balance_before": fb,
                                "fund_balance_after": fa,
                                "family_pass_limit_remaining_before": "",
                                "family_pass_limit_remaining_after": "",
                                "metadata_json": json.dumps({"merchant": m["name"], "fund": chosen_fund["name"], "ground_truth_anomaly": False}),
                                "is_itemized": is_item
                            })

                            if is_item:
                                all_items.append({
                                    "item_id": item_counter,
                                    "transaction_id": t_code,
                                    "name": f"{cat} Basket Items",
                                    "product_id": f"SKU-{random.randint(100, 999)}",
                                    "quantity": Decimal('1.00'),
                                    "unit_price": spend_amt,
                                    "discount": Decimal('0.00'),
                                    "tax": Decimal('0.00'),
                                    "total": spend_amt
                                })
                                item_counter += 1

                else:
                    # NORMAL WALLET TRANSACTION
                    # Mobile recharge, P2P transfer, merchant payment, cash out
                    action_choice = random.choices(
                        ["RECHARGE", "P2P", "MERCHANT", "CASH_OUT"],
                        weights=[40, 25, 25, 10]
                    )[0]

                    if action_choice == "RECHARGE" and w["balance"] >= Decimal('100.00'):
                        r_amt = quantize(Decimal(str(random.choice([50, 100, 200, 300, 500]))))
                        r_amt = min(r_amt, w["balance"])
                        wb = w["balance"]
                        w["balance"] -= r_amt
                        wa = w["balance"]

                        t_code = f"TXN-{txn_time.strftime('%Y%m%d')}-{txn_id_counter:06d}"
                        txn_id_counter += 1

                        all_transactions.append({
                            "transaction_id": t_code,
                            "sender_id": u_id,
                            "receiver_id": "",
                            "merchant_id": "",
                            "timestamp": txn_time.strftime("%Y-%m-%d %H:%M:%S"),
                            "amount": r_amt,
                            "transaction_type": "MOBILE_RECHARGE",
                            "payment_source": "NORMAL_WALLET",
                            "purpose_fund_id": "",
                            "family_pass_id": "",
                            "category": "Recharge",
                            "status": "COMPLETED",
                            "rejection_reason": "",
                            "reference": f"Mobile Recharge to {u['phone']}",
                            "wallet_balance_before": wb,
                            "wallet_balance_after": wa,
                            "fund_balance_before": "",
                            "fund_balance_after": "",
                            "family_pass_limit_remaining_before": "",
                            "family_pass_limit_remaining_after": "",
                            "metadata_json": json.dumps({"operator": "Grameenphone", "ground_truth_anomaly": False}),
                            "is_itemized": False
                        })

                    elif action_choice == "P2P" and w["balance"] >= Decimal('500.00'):
                        recip = random.choice([other for other in USER_SPECS if other["id"] != u_id])
                        send_amt = quantize(Decimal(str(random.choice([300, 500, 1000, 1500]))))
                        send_amt = min(send_amt, w["balance"])

                        wb = w["balance"]
                        w["balance"] -= send_amt
                        wa = w["balance"]

                        rw = wallets[recip["id"]]
                        rw["balance"] += send_amt

                        t_code = f"TXN-{txn_time.strftime('%Y%m%d')}-{txn_id_counter:06d}"
                        txn_id_counter += 1

                        all_transactions.append({
                            "transaction_id": t_code,
                            "sender_id": u_id,
                            "receiver_id": recip["id"],
                            "merchant_id": "",
                            "timestamp": txn_time.strftime("%Y-%m-%d %H:%M:%S"),
                            "amount": send_amt,
                            "transaction_type": "SEND_MONEY",
                            "payment_source": "NORMAL_WALLET",
                            "purpose_fund_id": "",
                            "family_pass_id": "",
                            "category": "Transfer",
                            "status": "COMPLETED",
                            "rejection_reason": "",
                            "reference": f"Sent money to {recip['name']}",
                            "wallet_balance_before": wb,
                            "wallet_balance_after": wa,
                            "fund_balance_before": "",
                            "fund_balance_after": "",
                            "family_pass_limit_remaining_before": "",
                            "family_pass_limit_remaining_after": "",
                            "metadata_json": json.dumps({"recipient_phone": recip["phone"], "ground_truth_anomaly": False}),
                            "is_itemized": False
                        })

                    elif action_choice == "CASH_OUT" and w["balance"] >= Decimal('1000.00'):
                        co_amt = quantize(Decimal(str(random.choice([500, 1000, 2000]))))
                        co_amt = min(co_amt, w["balance"])

                        wb = w["balance"]
                        w["balance"] -= co_amt
                        wa = w["balance"]

                        t_code = f"TXN-{txn_time.strftime('%Y%m%d')}-{txn_id_counter:06d}"
                        txn_id_counter += 1

                        all_transactions.append({
                            "transaction_id": t_code,
                            "sender_id": u_id,
                            "receiver_id": "",
                            "merchant_id": "",
                            "timestamp": txn_time.strftime("%Y-%m-%d %H:%M:%S"),
                            "amount": co_amt,
                            "transaction_type": "CASH_OUT",
                            "payment_source": "NORMAL_WALLET",
                            "purpose_fund_id": "",
                            "family_pass_id": "",
                            "category": "Cash Out",
                            "status": "COMPLETED",
                            "rejection_reason": "",
                            "reference": "Agent Cash Out Withdrawal",
                            "wallet_balance_before": wb,
                            "wallet_balance_after": wa,
                            "fund_balance_before": "",
                            "fund_balance_after": "",
                            "family_pass_limit_remaining_before": "",
                            "family_pass_limit_remaining_after": "",
                            "metadata_json": json.dumps({"agent_code": "AGT-7712", "ground_truth_anomaly": False}),
                            "is_itemized": False
                        })

                    elif w["balance"] >= Decimal('300.00'):
                        # Normal wallet merchant purchase
                        cat = random.choice(["Restaurant/Food", "Shopping", "Transport"])
                        m = random.choice(MERCHANTS_BY_CAT[cat])
                        p_amt = quantize(random.gauss(500, 150))
                        p_amt = max(Decimal('100.00'), min(p_amt, w["balance"]))

                        wb = w["balance"]
                        w["balance"] -= p_amt
                        wa = w["balance"]
                        m["balance"] += p_amt

                        t_code = f"TXN-{txn_time.strftime('%Y%m%d')}-{txn_id_counter:06d}"
                        txn_id_counter += 1

                        all_transactions.append({
                            "transaction_id": t_code,
                            "sender_id": u_id,
                            "receiver_id": "",
                            "merchant_id": m["id"],
                            "timestamp": txn_time.strftime("%Y-%m-%d %H:%M:%S"),
                            "amount": p_amt,
                            "transaction_type": "MERCHANT_PAYMENT",
                            "payment_source": "NORMAL_WALLET",
                            "purpose_fund_id": "",
                            "family_pass_id": "",
                            "category": cat,
                            "status": "COMPLETED",
                            "rejection_reason": "",
                            "reference": f"Payment to {m['name']} from Normal Wallet",
                            "wallet_balance_before": wb,
                            "wallet_balance_after": wa,
                            "fund_balance_before": "",
                            "fund_balance_after": "",
                            "family_pass_limit_remaining_before": "",
                            "family_pass_limit_remaining_after": "",
                            "metadata_json": json.dumps({"merchant": m["name"], "ground_truth_anomaly": False}),
                            "is_itemized": False
                        })

    print(f"Base chronological transactions generated: {len(all_transactions)}")

    # 4. Injected Controlled Anomalies and Policy Violations (~6-7% of total)
    # A. Completed Behavioral/Statistical Anomalies (Large amount, Off-hours, Spikes, Bursts)
    # B. Rejected Policy Violations (Category mismatch, Pass limit exceeded, Expired pass)
    
    print("Injecting controlled behavioral anomalies and policy violations...")
    
    # We will inject ~150 completed behavioral anomalies and ~55 rejected policy violations
    # Anchored across realistic days throughout the 180-day history
    
    sample_days = random.sample(range(5, TOTAL_DAYS - 5), k=150)
    for s_day in sample_days:
        day_date = START_DATE + datetime.timedelta(days=s_day)
        u = random.choice(USER_SPECS)
        u_id = u["id"]
        w = wallets[u_id]
        u_funds = user_funds_map[u_id]

        anom_kind = random.choice(["LARGE_AMOUNT", "UNUSUAL_TIME", "SPENDING_BURST", "UNUSUAL_CATEGORY"])

        if anom_kind == "LARGE_AMOUNT":
            # 4.5x - 6.5x average transaction
            cat = "Shopping" if u_funds else "Grocery"
            m = random.choice(MERCHANTS_BY_CAT[cat])
            spike_amt = quantize(Decimal(str(random.randint(9500, 18500))))
            # Ensure sufficient wallet balance
            if w["balance"] < spike_amt:
                w["balance"] += spike_amt * Decimal('1.5')
            
            wb = w["balance"]
            w["balance"] -= spike_amt
            wa = w["balance"]
            m["balance"] += spike_amt

            a_time = day_date.replace(hour=random.randint(14, 20), minute=random.randint(0, 59))
            t_code = f"TXN-ANOM-{a_time.strftime('%Y%m%d')}-{txn_id_counter:06d}"
            txn_id_counter += 1

            t_obj = {
                "transaction_id": t_code,
                "sender_id": u_id,
                "receiver_id": "",
                "merchant_id": m["id"],
                "timestamp": a_time.strftime("%Y-%m-%d %H:%M:%S"),
                "amount": spike_amt,
                "transaction_type": "MERCHANT_PAYMENT",
                "payment_source": "NORMAL_WALLET",
                "purpose_fund_id": "",
                "family_pass_id": "",
                "category": cat,
                "status": "COMPLETED",
                "rejection_reason": "",
                "reference": f"High value purchase at {m['name']}",
                "wallet_balance_before": wb,
                "wallet_balance_after": wa,
                "fund_balance_before": "",
                "fund_balance_after": "",
                "family_pass_limit_remaining_before": "",
                "family_pass_limit_remaining_after": "",
                "metadata_json": json.dumps({"ground_truth_anomaly": True, "anomaly_type": "LARGE_AMOUNT"}),
                "is_itemized": True
            }
            all_transactions.append(t_obj)
            all_anomalies.append({
                "transaction_id": t_code,
                "is_anomaly": True,
                "anomaly_type": "LARGE_AMOUNT",
                "reason": f"Amount (৳{spike_amt}) is over 4.5× higher than user's typical {cat} average",
                "amount": spike_amt,
                "category": cat,
                "payment_source": "NORMAL_WALLET",
                "timestamp": a_time.strftime("%Y-%m-%d %H:%M:%S")
            })

        elif anom_kind == "UNUSUAL_TIME":
            # Off-peak hours between 01:00 AM and 04:30 AM
            cat = "Transport"
            m = random.choice(MERCHANTS_BY_CAT[cat])
            amt = quantize(Decimal(str(random.randint(1200, 3200))))
            if w["balance"] < amt:
                w["balance"] += amt * Decimal('2')
            
            wb = w["balance"]
            w["balance"] -= amt
            wa = w["balance"]
            m["balance"] += amt

            a_time = day_date.replace(hour=random.randint(1, 4), minute=random.randint(5, 50))
            t_code = f"TXN-ANOM-{a_time.strftime('%Y%m%d')}-{txn_id_counter:06d}"
            txn_id_counter += 1

            t_obj = {
                "transaction_id": t_code,
                "sender_id": u_id,
                "receiver_id": "",
                "merchant_id": m["id"],
                "timestamp": a_time.strftime("%Y-%m-%d %H:%M:%S"),
                "amount": amt,
                "transaction_type": "MERCHANT_PAYMENT",
                "payment_source": "NORMAL_WALLET",
                "purpose_fund_id": "",
                "family_pass_id": "",
                "category": cat,
                "status": "COMPLETED",
                "rejection_reason": "",
                "reference": f"Late night inter-district transport fare via {m['name']}",
                "wallet_balance_before": wb,
                "wallet_balance_after": wa,
                "fund_balance_before": "",
                "fund_balance_after": "",
                "family_pass_limit_remaining_before": "",
                "family_pass_limit_remaining_after": "",
                "metadata_json": json.dumps({"ground_truth_anomaly": True, "anomaly_type": "UNUSUAL_TIME"}),
                "is_itemized": False
            }
            all_transactions.append(t_obj)
            all_anomalies.append({
                "transaction_id": t_code,
                "is_anomaly": True,
                "anomaly_type": "UNUSUAL_TIME",
                "reason": f"Transaction executed at {a_time.strftime('%I:%M %p')}, deviating from daytime pattern",
                "amount": amt,
                "category": cat,
                "payment_source": "NORMAL_WALLET",
                "timestamp": a_time.strftime("%Y-%m-%d %H:%M:%S")
            })

        elif anom_kind == "SPENDING_BURST":
            # 2 back-to-back rapid charges in dining/shopping
            cat = "Restaurant/Food"
            m = random.choice(MERCHANTS_BY_CAT[cat])
            amt1 = quantize(Decimal(str(random.randint(2200, 3800))))
            if w["balance"] < amt1:
                w["balance"] += amt1 * Decimal('2')
            
            wb = w["balance"]
            w["balance"] -= amt1
            wa = w["balance"]
            m["balance"] += amt1

            a_time = day_date.replace(hour=21, minute=random.randint(10, 25))
            t_code = f"TXN-ANOM-{a_time.strftime('%Y%m%d')}-{txn_id_counter:06d}"
            txn_id_counter += 1

            t_obj = {
                "transaction_id": t_code,
                "sender_id": u_id,
                "receiver_id": "",
                "merchant_id": m["id"],
                "timestamp": a_time.strftime("%Y-%m-%d %H:%M:%S"),
                "amount": amt1,
                "transaction_type": "MERCHANT_PAYMENT",
                "payment_source": "NORMAL_WALLET",
                "purpose_fund_id": "",
                "family_pass_id": "",
                "category": cat,
                "status": "COMPLETED",
                "rejection_reason": "",
                "reference": f"Large banquet charge at {m['name']}",
                "wallet_balance_before": wb,
                "wallet_balance_after": wa,
                "fund_balance_before": "",
                "fund_balance_after": "",
                "family_pass_limit_remaining_before": "",
                "family_pass_limit_remaining_after": "",
                "metadata_json": json.dumps({"ground_truth_anomaly": True, "anomaly_type": "SPENDING_BURST"}),
                "is_itemized": True
            }
            all_transactions.append(t_obj)
            all_anomalies.append({
                "transaction_id": t_code,
                "is_anomaly": True,
                "anomaly_type": "SPENDING_BURST",
                "reason": "Sudden spending burst (>3× category baseline within 1 hour)",
                "amount": amt1,
                "category": cat,
                "payment_source": "NORMAL_WALLET",
                "timestamp": a_time.strftime("%Y-%m-%d %H:%M:%S")
            })

        else: # UNUSUAL_CATEGORY
            cat = "Treatment"
            m = random.choice(MERCHANTS_BY_CAT[cat])
            amt = quantize(Decimal(str(random.randint(8500, 16000))))
            if w["balance"] < amt:
                w["balance"] += amt * Decimal('2')
            
            wb = w["balance"]
            w["balance"] -= amt
            wa = w["balance"]
            m["balance"] += amt

            a_time = day_date.replace(hour=random.randint(10, 17), minute=random.randint(0, 59))
            t_code = f"TXN-ANOM-{a_time.strftime('%Y%m%d')}-{txn_id_counter:06d}"
            txn_id_counter += 1

            t_obj = {
                "transaction_id": t_code,
                "sender_id": u_id,
                "receiver_id": "",
                "merchant_id": m["id"],
                "timestamp": a_time.strftime("%Y-%m-%d %H:%M:%S"),
                "amount": amt,
                "transaction_type": "MERCHANT_PAYMENT",
                "payment_source": "NORMAL_WALLET",
                "purpose_fund_id": "",
                "family_pass_id": "",
                "category": cat,
                "status": "COMPLETED",
                "rejection_reason": "",
                "reference": f"Emergency diagnostic package at {m['name']}",
                "wallet_balance_before": wb,
                "wallet_balance_after": wa,
                "fund_balance_before": "",
                "fund_balance_after": "",
                "family_pass_limit_remaining_before": "",
                "family_pass_limit_remaining_after": "",
                "metadata_json": json.dumps({"ground_truth_anomaly": True, "anomaly_type": "UNUSUAL_CATEGORY"}),
                "is_itemized": True
            }
            all_transactions.append(t_obj)
            all_anomalies.append({
                "transaction_id": t_code,
                "is_anomaly": True,
                "anomaly_type": "UNUSUAL_CATEGORY",
                "reason": f"Infrequent category expenditure ({cat}) with high monetary impact",
                "amount": amt,
                "category": cat,
                "payment_source": "NORMAL_WALLET",
                "timestamp": a_time.strftime("%Y-%m-%d %H:%M:%S")
            })

    # B. Inject Rejected Policy Violations (~55 events)
    # Preserving exact FUNDShare rules:
    # 1. Purpose Fund Category Mismatch
    # 2. FamilyPass Category Mismatch
    # 3. FamilyPass Limit Exceeded
    rej_days = random.sample(range(10, TOTAL_DAYS - 5), k=55)
    for r_day in rej_days:
        day_date = START_DATE + datetime.timedelta(days=r_day)
        r_type = random.choice(["FUND_CAT_MISMATCH", "FP_CAT_MISMATCH", "FP_LIMIT_EXCEEDED"])
        
        if r_type == "FUND_CAT_MISMATCH":
            u = random.choice([x for x in USER_SPECS if user_funds_map[x["id"]]])
            u_id = u["id"]
            pf = random.choice(user_funds_map[u_id])
            # Pick a merchant with DIFFERENT category
            available_cats = [c for c in MERCHANTS_BY_CAT.keys() if len(MERCHANTS_BY_CAT[c]) > 0]
            wrong_cats = [c for c in available_cats if c != pf["category"]]
            wrong_cat = random.choice(wrong_cats)
            m = random.choice(MERCHANTS_BY_CAT[wrong_cat])
            
            amt = quantize(Decimal(str(random.randint(500, 2000))))
            r_time = day_date.replace(hour=random.randint(12, 19), minute=random.randint(0, 59))
            t_code = f"TXN-REJ-{r_time.strftime('%Y%m%d')}-{txn_id_counter:06d}"
            txn_id_counter += 1

            reason = f"Category Restriction Mismatch: Merchant '{m['name']}' is registered as '{m['category']}', but '{pf['name']}' can ONLY be used for '{pf['category']}' payments."
            
            all_transactions.append({
                "transaction_id": t_code,
                "sender_id": u_id,
                "receiver_id": "",
                "merchant_id": m["id"],
                "timestamp": r_time.strftime("%Y-%m-%d %H:%M:%S"),
                "amount": amt,
                "transaction_type": "MERCHANT_PAYMENT",
                "payment_source": "PURPOSE_FUND",
                "purpose_fund_id": pf["fund_id"],
                "family_pass_id": "",
                "category": m["category"],
                "status": "REJECTED",
                "rejection_reason": reason,
                "reference": f"Attempted payment to {m['name']} via {pf['name']}",
                "wallet_balance_before": wallets[u_id]["balance"],
                "wallet_balance_after": wallets[u_id]["balance"],
                "fund_balance_before": pf["current_balance"],
                "fund_balance_after": pf["current_balance"],
                "family_pass_limit_remaining_before": "",
                "family_pass_limit_remaining_after": "",
                "metadata_json": json.dumps({"ground_truth_anomaly": False, "policy_violation": "CATEGORY_RESTRICTION_ERROR"}),
                "is_itemized": False
            })

        elif r_type == "FP_CAT_MISMATCH":
            fp = random.choice(list(family_passes.values()))
            u_id = fp["member_id"]
            allowed_cats = fp["allowed_categories"]
            available_cats = [c for c in MERCHANTS_BY_CAT.keys() if len(MERCHANTS_BY_CAT[c]) > 0]
            wrong_cats = [c for c in available_cats if c not in allowed_cats]
            wrong_cat = random.choice(wrong_cats) if wrong_cats else "Shopping"
            m = random.choice(MERCHANTS_BY_CAT[wrong_cat])
            
            amt = quantize(Decimal(str(random.randint(400, 1500))))
            r_time = day_date.replace(hour=random.randint(12, 19), minute=random.randint(0, 59))
            t_code = f"TXN-REJ-{r_time.strftime('%Y%m%d')}-{txn_id_counter:06d}"
            txn_id_counter += 1

            reason = f"Category Restriction Mismatch: Merchant '{m['name']}' category '{m['category']}' is not allowed for this FamilyPass."
            
            all_transactions.append({
                "transaction_id": t_code,
                "sender_id": u_id,
                "receiver_id": "",
                "merchant_id": m["id"],
                "timestamp": r_time.strftime("%Y-%m-%d %H:%M:%S"),
                "amount": amt,
                "transaction_type": "MERCHANT_PAYMENT",
                "payment_source": "FAMILY_PASS",
                "purpose_fund_id": "",
                "family_pass_id": fp["family_pass_id"],
                "category": m["category"],
                "status": "REJECTED",
                "rejection_reason": reason,
                "reference": f"Attempted FamilyPass spending at {m['name']}",
                "wallet_balance_before": wallets[fp["owner_id"]]["balance"],
                "wallet_balance_after": wallets[fp["owner_id"]]["balance"],
                "fund_balance_before": "",
                "fund_balance_after": "",
                "family_pass_limit_remaining_before": fp["limit_amount"] - fp["used_amount"],
                "family_pass_limit_remaining_after": fp["limit_amount"] - fp["used_amount"],
                "metadata_json": json.dumps({"ground_truth_anomaly": False, "policy_violation": "FAMILYPASS_CATEGORY_MISMATCH"}),
                "is_itemized": False
            })

        else: # FP_LIMIT_EXCEEDED
            fp = random.choice(list(family_passes.values()))
            u_id = fp["member_id"]
            rem = fp["limit_amount"] - fp["used_amount"]
            excess_amt = rem + quantize(Decimal(str(random.randint(800, 2500))))
            cat = fp["allowed_categories"][0] if fp["allowed_categories"] else "Grocery"
            m = random.choice(MERCHANTS_BY_CAT[cat])

            r_time = day_date.replace(hour=random.randint(12, 19), minute=random.randint(0, 59))
            t_code = f"TXN-REJ-{r_time.strftime('%Y%m%d')}-{txn_id_counter:06d}"
            txn_id_counter += 1

            reason = f"FamilyPass spending limit exceeded. Remaining allowance: ৳{rem:,.2f}, requested: ৳{excess_amt:,.2f}"

            all_transactions.append({
                "transaction_id": t_code,
                "sender_id": u_id,
                "receiver_id": "",
                "merchant_id": m["id"],
                "timestamp": r_time.strftime("%Y-%m-%d %H:%M:%S"),
                "amount": excess_amt,
                "transaction_type": "MERCHANT_PAYMENT",
                "payment_source": "FAMILY_PASS",
                "purpose_fund_id": "",
                "family_pass_id": fp["family_pass_id"],
                "category": cat,
                "status": "REJECTED",
                "rejection_reason": reason,
                "reference": f"Attempted FamilyPass spending exceeding allowance",
                "wallet_balance_before": wallets[fp["owner_id"]]["balance"],
                "wallet_balance_after": wallets[fp["owner_id"]]["balance"],
                "fund_balance_before": "",
                "fund_balance_after": "",
                "family_pass_limit_remaining_before": rem,
                "family_pass_limit_remaining_after": rem,
                "metadata_json": json.dumps({"ground_truth_anomaly": False, "policy_violation": "FAMILYPASS_LIMIT_EXCEEDED"}),
                "is_itemized": False
            })

    # Sort all transactions chronologically
    all_transactions.sort(key=lambda x: x["timestamp"])

    print(f"Total simulated transactions: {len(all_transactions)}")
    print(f"Total ground-truth behavioral anomalies: {len(all_anomalies)}")

    # ==================== EXPORT TO CSV ====================
    print("Exporting datasets to CSV and JSON formats...")

    # 1. users.csv
    users_path = os.path.join(OUTPUT_DIR, "users.csv")
    with open(users_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["user_id", "username", "full_name", "phone", "role", "profile_type", "monthly_income_bdt", "budget_discipline", "created_at"])
        for u in USER_SPECS:
            writer.writerow([u["id"], u["username"], u["name"], u["phone"], "CUSTOMER", u["profile"], u["salary"], u["discipline"], START_DATE.strftime("%Y-%m-%d %H:%M:%S")])

    # 2. wallets.csv
    wallets_path = os.path.join(OUTPUT_DIR, "wallets.csv")
    with open(wallets_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["wallet_id", "owner_id", "initial_balance", "final_balance", "currency", "created_at"])
        for w in wallets.values():
            writer.writerow([w["wallet_id"], w["owner_id"], w["initial_balance"], w["balance"], "BDT", START_DATE.strftime("%Y-%m-%d %H:%M:%S")])

    # 3. merchants.csv
    merchants_path = os.path.join(OUTPUT_DIR, "merchants.csv")
    with open(merchants_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["merchant_id", "business_name", "category", "account_number", "contact_phone", "address", "final_balance", "is_active"])
        for m in merchants.values():
            writer.writerow([m["id"], m["name"], m["category"], m["acc"], m["phone"], m["address"], m["balance"], True])

    # 4. purpose_funds.csv
    funds_path = os.path.join(OUTPUT_DIR, "purpose_funds.csv")
    with open(funds_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["fund_id", "owner_id", "name", "category", "monthly_budget", "total_allocated", "total_spent", "current_balance", "status", "created_at"])
        for pf in purpose_funds.values():
            writer.writerow([pf["fund_id"], pf["owner_id"], pf["name"], pf["category"], pf["monthly_budget"], pf["total_allocated"], pf["total_spent"], pf["current_balance"], pf["status"], pf["created_at"]])

    # 5. family_passes.csv
    fp_path = os.path.join(OUTPUT_DIR, "family_passes.csv")
    with open(fp_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["family_pass_id", "owner_id", "member_id", "limit_amount", "used_amount", "remaining_limit", "start_date", "expiry_date", "allowed_action", "status", "purpose", "allowed_categories", "purpose_label", "created_at"])
        for fp in family_passes.values():
            rem = fp["limit_amount"] - fp["used_amount"]
            writer.writerow([fp["family_pass_id"], fp["owner_id"], fp["member_id"], fp["limit_amount"], fp["used_amount"], rem, fp["start_date"], fp["expiry_date"], fp["allowed_action"], fp["status"], fp["purpose"], json.dumps(fp["allowed_categories"]), fp["purpose_label"], fp["created_at"]])

    # 6. transactions.csv (Central Ledger)
    txn_path = os.path.join(OUTPUT_DIR, "transactions.csv")
    with open(txn_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        headers = [
            "transaction_id", "sender_id", "receiver_id", "merchant_id", "timestamp",
            "amount", "transaction_type", "payment_source", "purpose_fund_id", "family_pass_id",
            "category", "status", "rejection_reason", "reference", "wallet_balance_before",
            "wallet_balance_after", "fund_balance_before", "fund_balance_after",
            "family_pass_limit_remaining_before", "family_pass_limit_remaining_after",
            "metadata_json", "is_itemized"
        ]
        writer.writerow(headers)
        for t in all_transactions:
            writer.writerow([
                t["transaction_id"], t["sender_id"], t["receiver_id"], t["merchant_id"], t["timestamp"],
                t["amount"], t["transaction_type"], t["payment_source"], t["purpose_fund_id"], t["family_pass_id"],
                t["category"], t["status"], t["rejection_reason"], t["reference"], t["wallet_balance_before"],
                t["wallet_balance_after"], t["fund_balance_before"], t["fund_balance_after"],
                t["family_pass_limit_remaining_before"], t["family_pass_limit_remaining_after"],
                t["metadata_json"], t["is_itemized"]
            ])

    # 7. family_pass_transactions.csv
    fpt_path = os.path.join(OUTPUT_DIR, "family_pass_transactions.csv")
    with open(fpt_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["activity_id", "family_pass_id", "transaction_id", "member_id", "amount", "remaining_limit_after", "timestamp"])
        for act in all_fp_activities:
            writer.writerow([act["activity_id"], act["family_pass_id"], act["transaction_id"], act["member_id"], act["amount"], act["remaining_limit_after"], act["timestamp"]])

    # 8. transaction_items.csv
    items_path = os.path.join(OUTPUT_DIR, "transaction_items.csv")
    with open(items_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["item_id", "transaction_id", "name", "product_id", "quantity", "unit_price", "discount", "tax", "total"])
        for it in all_items:
            writer.writerow([it["item_id"], it["transaction_id"], it["name"], it["product_id"], it["quantity"], it["unit_price"], it["discount"], it["tax"], it["total"]])

    # 9. anomaly_ground_truth.csv
    anom_path = os.path.join(OUTPUT_DIR, "anomaly_ground_truth.csv")
    with open(anom_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["transaction_id", "is_anomaly", "anomaly_type", "reason", "amount", "category", "payment_source", "timestamp"])
        for an in all_anomalies:
            writer.writerow([an["transaction_id"], an["is_anomaly"], an["anomaly_type"], an["reason"], an["amount"], an["category"], an["payment_source"], an["timestamp"]])

    # ==================== VALIDATION CHECKS ====================
    print("\nRunning comprehensive integrity validation checks...")
    
    val_results = {}

    # Check 1: Referential Integrity
    user_ids = {u["id"] for u in USER_SPECS}
    merchant_ids = {m["id"] for m in MERCHANTS_DATA}
    fund_ids = set(purpose_funds.keys())
    fp_ids = set(family_passes.keys())

    ref_ok = True
    for t in all_transactions:
        if t["sender_id"] not in user_ids:
            ref_ok = False
        if t["merchant_id"] and int(t["merchant_id"]) not in merchant_ids:
            ref_ok = False
        if t["purpose_fund_id"] and int(t["purpose_fund_id"]) not in fund_ids:
            ref_ok = False
        if t["family_pass_id"] and int(t["family_pass_id"]) not in fp_ids:
            ref_ok = False
    val_results["referential_integrity"] = "PASSED" if ref_ok else "FAILED"

    # Check 2: Balance Integrity (No negative balances in final state)
    neg_wallets = [w["owner_id"] for w in wallets.values() if w["balance"] < 0]
    neg_funds = [f["fund_id"] for f in purpose_funds.values() if f["current_balance"] < 0]
    neg_passes = [fp["family_pass_id"] for fp in family_passes.values() if (fp["limit_amount"] - fp["used_amount"]) < 0]
    
    val_results["balance_integrity"] = "PASSED" if (len(neg_wallets) == 0 and len(neg_funds) == 0 and len(neg_passes) == 0) else "FAILED"

    # Check 3: Purpose Fund Category Rules
    pf_cat_mismatch = 0
    for t in all_transactions:
        if t["status"] == "COMPLETED" and t["payment_source"] == "PURPOSE_FUND":
            pf_id = int(t["purpose_fund_id"])
            m_id = int(t["merchant_id"])
            if purpose_funds[pf_id]["category"] != merchants[m_id]["category"]:
                pf_cat_mismatch += 1
    val_results["purpose_fund_category_consistency"] = "PASSED" if pf_cat_mismatch == 0 else "FAILED"

    # Check 4: FamilyPass Category Rules
    fp_cat_mismatch = 0
    for t in all_transactions:
        if t["status"] == "COMPLETED" and t["payment_source"] == "FAMILY_PASS":
            fp_id = int(t["family_pass_id"])
            m_id = int(t["merchant_id"])
            allowed = family_passes[fp_id]["allowed_categories"]
            if allowed and merchants[m_id]["category"] not in allowed:
                fp_cat_mismatch += 1
    val_results["family_pass_category_consistency"] = "PASSED" if fp_cat_mismatch == 0 else "FAILED"

    # Check 5: Chronological Ordering
    sorted_times = [datetime.datetime.strptime(t["timestamp"], "%Y-%m-%d %H:%M:%S") for t in all_transactions]
    temporal_ok = all(sorted_times[i] <= sorted_times[i+1] for i in range(len(sorted_times)-1))
    val_results["temporal_order_integrity"] = "PASSED" if temporal_ok else "FAILED"

    # Metrics Breakdown
    total_txns = len(all_transactions)
    completed_txns = sum(1 for t in all_transactions if t["status"] == "COMPLETED")
    rejected_txns = sum(1 for t in all_transactions if t["status"] == "REJECTED")
    
    pf_spend_count = sum(1 for t in all_transactions if t["payment_source"] == "PURPOSE_FUND" and t["transaction_type"] == "MERCHANT_PAYMENT" and t["status"] == "COMPLETED")
    fp_spend_count = sum(1 for t in all_transactions if t["payment_source"] == "FAMILY_PASS" and t["status"] == "COMPLETED")
    normal_spend_count = sum(1 for t in all_transactions if t["payment_source"] == "NORMAL_WALLET" and t["transaction_type"] in ("MERCHANT_PAYMENT", "MOBILE_RECHARGE", "CASH_OUT", "SEND_MONEY") and t["status"] == "COMPLETED")
    bills_count = sum(1 for t in all_transactions if t["transaction_type"] == "BILL_PAYMENT" or (t["category"] in ("Electricity", "Rent") and t["payment_source"] == "PURPOSE_FUND"))
    inflows_alloc_count = sum(1 for t in all_transactions if t["transaction_type"] in ("CASH_IN", "FUND_ALLOCATION", "FUND_TRANSFER"))

    behavioral_anom_count = len(all_anomalies)
    anom_pct = round((behavioral_anom_count / total_txns) * 100.0, 2)

    cat_counts = defaultdict(int)
    type_counts = defaultdict(int)
    source_counts = defaultdict(int)
    for t in all_transactions:
        cat_counts[t["category"]] += 1
        type_counts[t["transaction_type"]] += 1
        source_counts[t["payment_source"]] += 1

    summary_obj = {
        "dataset_name": "FUNDShare Synthetic Historical Financial Dataset",
        "notice": "SYNTHETIC DATA — NOT REAL UPAY CUSTOMER DATA",
        "random_seed": RANDOM_SEED,
        "date_range": {
            "start_date": START_DATE.strftime("%Y-%m-%d"),
            "end_date": END_DATE.strftime("%Y-%m-%d"),
            "total_days": TOTAL_DAYS
        },
        "volume_statistics": {
            "total_customer_users": len(USER_SPECS),
            "total_merchants": len(MERCHANTS_DATA),
            "total_purpose_funds": len(purpose_funds),
            "total_family_passes": len(family_passes),
            "total_transactions": total_txns,
            "average_transactions_per_user": round(total_txns / len(USER_SPECS), 1),
            "completed_transactions": completed_txns,
            "rejected_transactions": rejected_txns,
            "failed_transactions": 0,
            "itemized_transactions": len(all_items)
        },
        "distribution_percentages": {
            "purpose_fund_spending_pct": round((pf_spend_count / total_txns) * 100.0, 1),
            "family_pass_spending_pct": round((fp_spend_count / total_txns) * 100.0, 1),
            "normal_wallet_spending_pct": round((normal_spend_count / total_txns) * 100.0, 1),
            "utility_and_bill_payments_pct": round((bills_count / total_txns) * 100.0, 1),
            "inflows_and_allocations_pct": round((inflows_alloc_count / total_txns) * 100.0, 1)
        },
        "anomaly_statistics": {
            "behavioral_anomalies_ground_truth": behavioral_anom_count,
            "policy_violation_rejections": rejected_txns,
            "behavioral_anomaly_rate_pct": anom_pct
        },
        "breakdown_by_category": dict(sorted(cat_counts.items(), key=lambda x: x[1], reverse=True)),
        "breakdown_by_transaction_type": dict(sorted(type_counts.items(), key=lambda x: x[1], reverse=True)),
        "breakdown_by_payment_source": dict(sorted(source_counts.items(), key=lambda x: x[1], reverse=True)),
        "validation_results": val_results
    }

    # 10. dataset_summary.json
    summary_path = os.path.join(OUTPUT_DIR, "dataset_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary_obj, f, indent=2)

    # 11. README.md
    readme_path = os.path.join(OUTPUT_DIR, "README.md")
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(f"""# FUNDShare Synthetic Historical Financial Dataset

> **CRITICAL COMPLIANCE NOTICE**:
> **SYNTHETIC DATA — NOT REAL UPAY CUSTOMER DATA**
> This dataset was generated entirely synthetically for the FUNDShare Mobile Financial Services (MFS) hackathon prototype to train and evaluate Anomaly Detection, Budget Forecasting, and AI Financial Coaching. It does not represent or contain any real customer data.

---

## 1. Dataset Overview

* **Time Horizon**: {START_DATE.strftime('%B %d, %Y')} to {END_DATE.strftime('%B %d, %Y')} ({TOTAL_DAYS} chronological days)
* **Customer Users**: {len(USER_SPECS)} unique customer accounts
* **Merchants**: {len(MERCHANTS_DATA)} verified merchants across 10 business categories
* **Purpose Funds**: {len(purpose_funds)} active purpose fund budgeting buckets
* **FamilyPass Delegations**: {len(family_passes)} active spending authorization delegations
* **Total Transactions**: {total_txns:,} events
* **Average Volume per User**: {round(total_txns / len(USER_SPECS), 1)} transactions / customer
* **Reproducibility Random Seed**: `{RANDOM_SEED}`

---

## 2. Transaction Distribution

| Spending Category | Transactions | Percentage |
|:---|:---:|:---:|
| **Purpose Fund Spending** | {pf_spend_count} | {round((pf_spend_count / total_txns) * 100.0, 1)}% |
| **FamilyPass Spending** | {fp_spend_count} | {round((fp_spend_count / total_txns) * 100.0, 1)}% |
| **Normal Wallet Spending** | {normal_spend_count} | {round((normal_spend_count / total_txns) * 100.0, 1)}% |
| **Utility & Bill Payments** | {bills_count} | {round((bills_count / total_txns) * 100.0, 1)}% |
| **Inflows & Fund Allocations** | {inflows_alloc_count} | {round((inflows_alloc_count / total_txns) * 100.0, 1)}% |
| **Total** | **{total_txns}** | **100.0%** |

---

## 3. Anomaly & Policy Violation Design

* **Behavioral Outliers (Ground Truth)**: {behavioral_anom_count} transactions ({anom_pct}%)
  * `LARGE_AMOUNT`: 4.5× to 6.5× higher than user's category average
  * `UNUSUAL_TIME`: Transactions between 01:00 AM and 04:30 AM
  * `SPENDING_BURST`: Multiple high-velocity transactions within 1 hour
  * `UNUSUAL_CATEGORY`: Infrequent category expenditure with high value
* **Policy Violations (Deterministic Rejections)**: {rejected_txns} transactions
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
""")

    print(f"\nSynthetic dataset generated successfully in: {OUTPUT_DIR}")
    print(f"Validation Summary: {val_results}")
    return summary_obj

if __name__ == "__main__":
    generate_dataset()
