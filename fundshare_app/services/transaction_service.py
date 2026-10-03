import uuid
from decimal import Decimal
from django.db import transaction as db_transaction
from django.utils import timezone
from fundshare_app.models import (
    User, Wallet, Merchant, PurposeFund, FundTransfer,
    FamilyPass, FamilyPassTransaction, Transaction, TransactionItem,
    TransactionType, PaymentSource, TransactionStatus,
    FamilyPassStatus, Notification, NotificationType, AnomalyResult,
    BusinessCategory
)


class TransactionValidationError(Exception):
    def __init__(self, message, code="INVALID_TRANSACTION"):
        super().__init__(message)
        self.message = message
        self.code = code


class TransactionService:

    @classmethod
    def _save_transaction_items(cls, txn: Transaction, validated_items: list):
        if validated_items:
            items_to_create = [
                TransactionItem(
                    transaction=txn,
                    name=itm['name'],
                    product_id=itm['product_id'],
                    quantity=itm['quantity'],
                    unit_price=itm['unit_price'],
                    discount=itm['discount'],
                    tax=itm['tax'],
                    total=itm['total']
                )
                for itm in validated_items
            ]
            TransactionItem.objects.bulk_create(items_to_create)

    @classmethod
    def execute_transaction(
        cls,
        sender: User,
        transaction_type: str,
        amount: Decimal = None,
        receiver: User = None,
        merchant: Merchant = None,
        payment_source: str = PaymentSource.NORMAL_WALLET,
        purpose_fund: PurposeFund = None,
        family_pass: FamilyPass = None,
        reference: str = '',
        metadata: dict = None,
        items: list = None
    ) -> Transaction:
        """
        Executes financial transactions adhering strictly to deterministic business rules:
        - Category verification for purpose funds
        - 7-point validation for FamilyPass
        - Atomic wallet updates
        - Non-frontend authorization checks
        - Item-level purchase validation and persistence
        """
        validated_items = []
        if items is not None:
            if not isinstance(items, (list, tuple)):
                raise TransactionValidationError("Items must be a list.", code="INVALID_ITEMS_FORMAT")
            if len(items) > 0:
                for idx, itm in enumerate(items):
                    if not isinstance(itm, dict):
                        raise TransactionValidationError(f"Item #{idx+1} must be an object.", code="INVALID_ITEM_FORMAT")
                    name = str(itm.get('item_name') or itm.get('name') or '').strip()
                    if not name:
                        raise TransactionValidationError("Item name is required for all purchased items.", code="INVALID_ITEM_NAME")
                    prod_id = str(itm.get('product_id') or itm.get('sku') or '').strip()
                    try:
                        qty = Decimal(str(itm.get('quantity', '1')))
                    except Exception:
                        raise TransactionValidationError(f"Invalid quantity for item '{name}'.", code="INVALID_ITEM_QUANTITY")
                    if qty <= Decimal('0.00'):
                        raise TransactionValidationError(f"Quantity for item '{name}' must be greater than zero.", code="INVALID_ITEM_QUANTITY")

                    try:
                        price = Decimal(str(itm.get('unit_price', '0')))
                    except Exception:
                        raise TransactionValidationError(f"Invalid unit price for item '{name}'.", code="INVALID_ITEM_PRICE")
                    if price < Decimal('0.00'):
                        raise TransactionValidationError(f"Unit price for item '{name}' cannot be negative.", code="INVALID_ITEM_PRICE")

                    try:
                        discount = Decimal(str(itm.get('discount', '0') or '0'))
                    except Exception:
                        raise TransactionValidationError(f"Invalid discount for item '{name}'.", code="INVALID_ITEM_DISCOUNT")
                    if discount < Decimal('0.00'):
                        raise TransactionValidationError(f"Discount for item '{name}' cannot be negative.", code="INVALID_ITEM_DISCOUNT")

                    try:
                        tax = Decimal(str(itm.get('tax', '0') or '0'))
                    except Exception:
                        raise TransactionValidationError(f"Invalid tax for item '{name}'.", code="INVALID_ITEM_TAX")
                    if tax < Decimal('0.00'):
                        raise TransactionValidationError(f"Tax for item '{name}' cannot be negative.", code="INVALID_ITEM_TAX")

                    line_total = (qty * price) - discount + tax
                    if line_total < Decimal('0.00'):
                        raise TransactionValidationError(f"Line total for item '{name}' cannot be negative.", code="INVALID_LINE_TOTAL")

                    validated_items.append({
                        'name': name,
                        'product_id': prod_id,
                        'quantity': qty,
                        'unit_price': price,
                        'discount': discount,
                        'tax': tax,
                        'total': line_total
                    })

                items_sum = sum([it['total'] for it in validated_items])
                if items_sum <= Decimal('0.00'):
                    raise TransactionValidationError("Total purchase amount must be greater than zero.", code="INVALID_AMOUNT")

                if amount is not None:
                    try:
                        supplied_amount = Decimal(str(amount))
                        if supplied_amount != items_sum:
                            raise TransactionValidationError(
                                f"Payment amount mismatch: supplied ৳{supplied_amount}, calculated item total ৳{items_sum}.",
                                code="AMOUNT_MISMATCH"
                            )
                    except Exception as e:
                        if isinstance(e, TransactionValidationError):
                            raise
                        raise TransactionValidationError("Invalid payment amount format.", code="INVALID_AMOUNT")
                amount = items_sum

        if amount is None or amount <= Decimal('0.00'):
            raise TransactionValidationError("Transaction amount must be greater than zero.", code="INVALID_AMOUNT")

        if transaction_type == TransactionType.MERCHANT_PAYMENT:
            if not merchant:
                raise TransactionValidationError("Merchant is required for payment.", code="MERCHANT_REQUIRED")
            if not merchant.is_active:
                raise TransactionValidationError(f"Merchant '{merchant.business_name}' is inactive and cannot accept payments.", code="MERCHANT_INACTIVE")

        if metadata is None:
            metadata = {}

        # Ensure sender has a wallet
        wallet, _ = Wallet.objects.get_or_create(owner=sender)

        # PRE-FLIGHT CATEGORY VALIDATION & AUDIT LOGGING
        if transaction_type == TransactionType.MERCHANT_PAYMENT and payment_source == PaymentSource.PURPOSE_FUND:
            if not purpose_fund:
                raise TransactionValidationError("Purpose fund must be selected for purpose-based payment.")
            if purpose_fund.owner != sender:
                raise TransactionValidationError("Unauthorized: You do not own this purpose fund.")
            if merchant and purpose_fund.category != merchant.category:
                reason = (
                    f"Category Restriction Mismatch: Merchant '{merchant.business_name}' is registered as "
                    f"'{merchant.category}', but '{purpose_fund.name}' can ONLY be used for "
                    f"'{purpose_fund.category}' payments. Transaction denied by FundShare rule engine."
                )
                Transaction.objects.create(
                    transaction_id=f"TXN-{timezone.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6].upper()}",
                    sender=sender,
                    merchant=merchant,
                    amount=amount,
                    transaction_type=TransactionType.MERCHANT_PAYMENT,
                    payment_source=PaymentSource.PURPOSE_FUND,
                    purpose_fund=purpose_fund,
                    category=merchant.category,
                    status=TransactionStatus.REJECTED,
                    rejection_reason=reason,
                    reference=reference,
                    metadata=metadata
                )
                raise TransactionValidationError(reason, code="CATEGORY_RESTRICTION_ERROR")

        with db_transaction.atomic():
            txn_id = f"TXN-{timezone.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6].upper()}"

            if transaction_type == TransactionType.CASH_IN:
                # Add money to normal wallet
                wallet.balance += amount
                wallet.save(update_fields=['balance', 'updated_at'])

                txn = Transaction.objects.create(
                    transaction_id=txn_id,
                    sender=sender,
                    receiver=sender,
                    amount=amount,
                    transaction_type=TransactionType.CASH_IN,
                    payment_source=PaymentSource.NORMAL_WALLET,
                    category='Deposit',
                    status=TransactionStatus.COMPLETED,
                    reference=reference or 'Simulated Cash In / Bank Add Money',
                    metadata=metadata
                )
                Notification.objects.create(
                    user=sender,
                    title="Money Added Successfully",
                    message=f"৳{amount:,.2f} added to your normal wallet. New balance: ৳{wallet.balance:,.2f}",
                    notification_type=NotificationType.TRANSACTION
                )
                return txn

            elif transaction_type == TransactionType.SEND_MONEY:
                if not receiver:
                    raise TransactionValidationError("Receiver is required for Send Money.")
                if receiver == sender:
                    raise TransactionValidationError("Cannot send money to yourself.")
                if wallet.balance < amount:
                    raise TransactionValidationError(f"Insufficient balance. Available: ৳{wallet.balance:,.2f}, required: ৳{amount:,.2f}")

                wallet.balance -= amount
                wallet.save(update_fields=['balance', 'updated_at'])

                receiver_wallet, _ = Wallet.objects.get_or_create(owner=receiver)
                receiver_wallet.balance += amount
                receiver_wallet.save(update_fields=['balance', 'updated_at'])

                txn = Transaction.objects.create(
                    transaction_id=txn_id,
                    sender=sender,
                    receiver=receiver,
                    amount=amount,
                    transaction_type=TransactionType.SEND_MONEY,
                    payment_source=PaymentSource.NORMAL_WALLET,
                    category='Transfer',
                    status=TransactionStatus.COMPLETED,
                    reference=reference or f"Sent to {receiver.full_name or receiver.username}",
                    metadata=metadata
                )
                Notification.objects.create(
                    user=sender,
                    title="Money Sent",
                    message=f"৳{amount:,.2f} sent to {receiver.full_name or receiver.username}. Remaining balance: ৳{wallet.balance:,.2f}",
                    notification_type=NotificationType.TRANSACTION
                )
                Notification.objects.create(
                    user=receiver,
                    title="Money Received",
                    message=f"Received ৳{amount:,.2f} from {sender.full_name or sender.username}. New balance: ৳{receiver_wallet.balance:,.2f}",
                    notification_type=NotificationType.TRANSACTION
                )
                return txn

            elif transaction_type == TransactionType.MERCHANT_PAYMENT:
                if not merchant:
                    raise TransactionValidationError("Merchant is required for payment.")

                if payment_source == PaymentSource.PURPOSE_FUND:
                    if not purpose_fund:
                        raise TransactionValidationError("Purpose fund must be selected for purpose-based payment.")
                    if purpose_fund.owner != sender:
                        raise TransactionValidationError("Unauthorized: You do not own this purpose fund.")

                    # CRITICAL BUSINESS RULE: STRICT PURPOSE FUND CATEGORY RESTRICTION
                    if purpose_fund.category != merchant.category:
                        reason = (
                            f"Category Restriction Mismatch: Merchant '{merchant.business_name}' is registered as "
                            f"'{merchant.category}', but '{purpose_fund.name}' can ONLY be used for "
                            f"'{purpose_fund.category}' payments. Transaction denied by FundShare rule engine."
                        )
                        # Record rejected transaction for security audit
                        txn = Transaction.objects.create(
                            transaction_id=txn_id,
                            sender=sender,
                            merchant=merchant,
                            amount=amount,
                            transaction_type=TransactionType.MERCHANT_PAYMENT,
                            payment_source=PaymentSource.PURPOSE_FUND,
                            purpose_fund=purpose_fund,
                            category=merchant.category,
                            status=TransactionStatus.REJECTED,
                            rejection_reason=reason,
                            reference=reference,
                            metadata=metadata
                        )
                        raise TransactionValidationError(reason, code="CATEGORY_RESTRICTION_ERROR")

                    if purpose_fund.current_balance < amount:
                        reason = f"Insufficient Purpose Fund balance. '{purpose_fund.name}' has ৳{purpose_fund.current_balance:,.2f}, required ৳{amount:,.2f}."
                        Transaction.objects.create(
                            transaction_id=txn_id,
                            sender=sender,
                            merchant=merchant,
                            amount=amount,
                            transaction_type=TransactionType.MERCHANT_PAYMENT,
                            payment_source=PaymentSource.PURPOSE_FUND,
                            purpose_fund=purpose_fund,
                            category=merchant.category,
                            status=TransactionStatus.REJECTED,
                            rejection_reason=reason,
                            reference=reference,
                            metadata=metadata
                        )
                        raise TransactionValidationError(reason, code="INSUFFICIENT_FUND_BALANCE")

                    # Deduct from Purpose Fund
                    purpose_fund.current_balance -= amount
                    purpose_fund.save(update_fields=['current_balance', 'updated_at'])

                    # Credit merchant
                    merchant.balance += amount
                    merchant.save(update_fields=['balance'])

                    txn = Transaction.objects.create(
                        transaction_id=txn_id,
                        sender=sender,
                        merchant=merchant,
                        amount=amount,
                        transaction_type=TransactionType.MERCHANT_PAYMENT,
                        payment_source=PaymentSource.PURPOSE_FUND,
                        purpose_fund=purpose_fund,
                        category=merchant.category,
                        status=TransactionStatus.COMPLETED,
                        reference=reference or f"Payment to {merchant.business_name} via {purpose_fund.name} Fund",
                        metadata=metadata
                    )
                    cls._save_transaction_items(txn, validated_items)

                    Notification.objects.create(
                        user=sender,
                        title=f"Paid {merchant.business_name}",
                        message=f"৳{amount:,.2f} deducted from {purpose_fund.name} Fund. Remaining fund balance: ৳{purpose_fund.current_balance:,.2f}",
                        notification_type=NotificationType.TRANSACTION
                    )
                    cls._check_anomaly_and_record(txn)
                    return txn

                elif payment_source == PaymentSource.FAMILY_PASS:
                    # CRITICAL SECURITY MODEL: 8-POINT BACKEND VERIFICATION FOR FAMILYPASS
                    if not family_pass:
                        raise TransactionValidationError("FamilyPass instance is required.", code="FAMILYPASS_REQUIRED")

                    # Lock FamilyPass and Owner Wallet to prevent concurrent overspending
                    family_pass = FamilyPass.objects.select_for_update().get(id=family_pass.id)
                    owner_wallet, _ = Wallet.objects.select_for_update().get_or_create(owner=family_pass.owner)

                    # 1. Active status check
                    if family_pass.status != FamilyPassStatus.ACTIVE:
                        raise TransactionValidationError("FamilyPass is not active or has been revoked.", code="FAMILYPASS_INACTIVE")

                    # 2. Expiry check
                    today = timezone.localdate() if timezone.is_aware(timezone.now()) else timezone.now().date()
                    if family_pass.expiry_date < today:
                        family_pass.status = FamilyPassStatus.EXPIRED
                        family_pass.save(update_fields=['status', 'updated_at'])
                        family_pass.member.sync_role()
                        raise TransactionValidationError(f"FamilyPass expired on {family_pass.expiry_date}.", code="FAMILYPASS_EXPIRED")

                    # 3. Member authentication match (must NOT share credentials)
                    if family_pass.member != sender:
                        raise TransactionValidationError("Unauthorized user for this FamilyPass delegation.", code="FAMILYPASS_UNAUTHORIZED")

                    # 4. Action permission check
                    if family_pass.allowed_action not in ['MERCHANT_PAYMENT', 'ALL']:
                        raise TransactionValidationError("Action not permitted under current FamilyPass policy.", code="FAMILYPASS_ACTION_DENIED")

                    # 5. Remaining spending limit check
                    if family_pass.remaining_limit < amount:
                        raise TransactionValidationError(
                            f"FamilyPass spending limit exceeded. Remaining allowance: ৳{family_pass.remaining_limit:,.2f}, requested: ৳{amount:,.2f}",
                            code="FAMILYPASS_LIMIT_EXCEEDED"
                        )

                    # 6. Owner normal wallet balance sufficiency check
                    if owner_wallet.balance < amount:
                        raise TransactionValidationError("Owner's wallet balance is insufficient to cover this transaction.", code="OWNER_BALANCE_INSUFFICIENT")

                    # 7. Execute FamilyPass transaction atomically
                    owner_wallet.balance -= amount
                    owner_wallet.save(update_fields=['balance', 'updated_at'])

                    family_pass.used_amount += amount
                    family_pass.save(update_fields=['used_amount', 'updated_at'])

                    merchant.balance += amount
                    merchant.save(update_fields=['balance'])

                    txn = Transaction.objects.create(
                        transaction_id=txn_id,
                        sender=sender,
                        merchant=merchant,
                        amount=amount,
                        transaction_type=TransactionType.MERCHANT_PAYMENT,
                        payment_source=PaymentSource.FAMILY_PASS,
                        family_pass=family_pass,
                        category=merchant.category,
                        status=TransactionStatus.COMPLETED,
                        reference=reference or f"FamilyPass spending by {sender.full_name or sender.username} at {merchant.business_name}",
                        metadata={**metadata, 'owner_username': family_pass.owner.username, 'member_username': sender.username}
                    )
                    cls._save_transaction_items(txn, validated_items)

                    # Create FamilyPass activity log
                    FamilyPassTransaction.objects.create(
                        family_pass=family_pass,
                        transaction=txn,
                        member=sender,
                        amount=amount,
                        remaining_limit_after=family_pass.remaining_limit
                    )

                    # Trigger simulated instant notification to Owner
                    member_display = sender.full_name or sender.username
                    Notification.objects.create(
                        user=family_pass.owner,
                        title="🔔 FamilyPass Transaction Alert",
                        message=f"{member_display} spent ৳{amount:,.2f} at {merchant.business_name} ({merchant.category}). FamilyPass remaining limit: ৳{family_pass.remaining_limit:,.2f}.",
                        notification_type=NotificationType.FAMILY_PASS,
                        metadata={
                            'member': member_display,
                            'merchant': merchant.business_name,
                            'amount': float(amount),
                            'remaining_limit': float(family_pass.remaining_limit),
                            'timestamp': timezone.now().isoformat()
                        }
                    )

                    # Notification to Member
                    Notification.objects.create(
                        user=sender,
                        title="FamilyPass Payment Successful",
                        message=f"Paid ৳{amount:,.2f} to {merchant.business_name} via {family_pass.owner.full_name or family_pass.owner.username}'s FamilyPass. Remaining limit: ৳{family_pass.remaining_limit:,.2f}.",
                        notification_type=NotificationType.TRANSACTION
                    )

                    cls._check_anomaly_and_record(txn)
                    return txn

                else:
                    # Normal Wallet payment
                    if wallet.balance < amount:
                        raise TransactionValidationError(f"Insufficient balance. Available: ৳{wallet.balance:,.2f}, required: ৳{amount:,.2f}")

                    wallet.balance -= amount
                    wallet.save(update_fields=['balance', 'updated_at'])

                    merchant.balance += amount
                    merchant.save(update_fields=['balance'])

                    txn = Transaction.objects.create(
                        transaction_id=txn_id,
                        sender=sender,
                        merchant=merchant,
                        amount=amount,
                        transaction_type=TransactionType.MERCHANT_PAYMENT,
                        payment_source=PaymentSource.NORMAL_WALLET,
                        category=merchant.category,
                        status=TransactionStatus.COMPLETED,
                        reference=reference or f"Payment to {merchant.business_name}",
                        metadata=metadata
                    )
                    cls._save_transaction_items(txn, validated_items)

                    Notification.objects.create(
                        user=sender,
                        title=f"Paid {merchant.business_name}",
                        message=f"৳{amount:,.2f} paid from normal wallet. Remaining balance: ৳{wallet.balance:,.2f}",
                        notification_type=NotificationType.TRANSACTION
                    )
                    cls._check_anomaly_and_record(txn)
                    return txn

            elif transaction_type in [TransactionType.MOBILE_RECHARGE, TransactionType.BILL_PAYMENT, TransactionType.CASH_OUT]:
                if wallet.balance < amount:
                    raise TransactionValidationError(f"Insufficient wallet balance. Available: ৳{wallet.balance:,.2f}, required: ৳{amount:,.2f}")

                wallet.balance -= amount
                wallet.save(update_fields=['balance', 'updated_at'])

                category_map = {
                    TransactionType.MOBILE_RECHARGE: 'Recharge',
                    TransactionType.BILL_PAYMENT: 'Utility Bill',
                    TransactionType.CASH_OUT: 'Cash Out'
                }

                txn = Transaction.objects.create(
                    transaction_id=txn_id,
                    sender=sender,
                    amount=amount,
                    transaction_type=transaction_type,
                    payment_source=PaymentSource.NORMAL_WALLET,
                    category=category_map.get(transaction_type, 'General'),
                    status=TransactionStatus.COMPLETED,
                    reference=reference or f"Simulated {transaction_type.replace('_', ' ').title()}",
                    metadata=metadata
                )

                Notification.objects.create(
                    user=sender,
                    title=f"{transaction_type.replace('_', ' ').title()} Successful",
                    message=f"৳{amount:,.2f} processed. Remaining balance: ৳{wallet.balance:,.2f}",
                    notification_type=NotificationType.TRANSACTION
                )
                cls._check_anomaly_and_record(txn)
                return txn

            else:
                raise TransactionValidationError(f"Unsupported transaction type: {transaction_type}")

    @classmethod
    def allocate_to_fund(cls, user: User, purpose_fund: PurposeFund, amount: Decimal) -> PurposeFund:
        """
        Allocates funds from the owner's normal wallet into a specific PurposeFund.
        """
        if amount <= Decimal('0.00'):
            raise TransactionValidationError("Allocation amount must be greater than zero.")
        if purpose_fund.owner != user:
            raise TransactionValidationError("Unauthorized fund access.")

        wallet, _ = Wallet.objects.get_or_create(owner=user)
        if wallet.balance < amount:
            raise TransactionValidationError(f"Insufficient wallet balance to allocate. Available: ৳{wallet.balance:,.2f}")

        with db_transaction.atomic():
            wallet.balance -= amount
            wallet.save(update_fields=['balance', 'updated_at'])

            purpose_fund.allocated_amount += amount
            purpose_fund.current_balance += amount
            purpose_fund.save(update_fields=['allocated_amount', 'current_balance', 'updated_at'])

            Transaction.objects.create(
                sender=user,
                amount=amount,
                transaction_type=TransactionType.FUND_ALLOCATION,
                payment_source=PaymentSource.NORMAL_WALLET,
                purpose_fund=purpose_fund,
                category=purpose_fund.category,
                status=TransactionStatus.COMPLETED,
                reference=f"Allocated ৳{amount} to {purpose_fund.name} Fund"
            )

            Notification.objects.create(
                user=user,
                title="Fund Allocated",
                message=f"৳{amount:,.2f} transferred from wallet to {purpose_fund.name} Fund. Current fund balance: ৳{purpose_fund.current_balance:,.2f}",
                notification_type=NotificationType.TRANSACTION
            )

        return purpose_fund

    @classmethod
    def transfer_between_funds(
        cls,
        user: User,
        source_fund: PurposeFund,
        destination_fund: PurposeFund,
        amount: Decimal,
        reason: str = ''
    ) -> FundTransfer:
        """
        Transfers money between two purpose funds owned by the same user.
        Strictly an explicit user action (AI recommends, user confirms).
        """
        if amount <= Decimal('0.00'):
            raise TransactionValidationError("Transfer amount must be greater than zero.")
        if source_fund == destination_fund:
            raise TransactionValidationError("Source and destination funds cannot be identical.")
        if source_fund.owner != user or destination_fund.owner != user:
            raise TransactionValidationError("Unauthorized: Funds must belong to the user.")
        if source_fund.current_balance < amount:
            raise TransactionValidationError(f"Insufficient balance in '{source_fund.name}'. Available: ৳{source_fund.current_balance:,.2f}")

        with db_transaction.atomic():
            source_fund.current_balance -= amount
            source_fund.save(update_fields=['current_balance', 'updated_at'])

            destination_fund.current_balance += amount
            destination_fund.save(update_fields=['current_balance', 'updated_at'])

            transfer = FundTransfer.objects.create(
                owner=user,
                source_fund=source_fund,
                destination_fund=destination_fund,
                amount=amount,
                reason=reason or f"Transfer from {source_fund.name} to {destination_fund.name}"
            )

            Transaction.objects.create(
                sender=user,
                amount=amount,
                transaction_type=TransactionType.FUND_TRANSFER,
                payment_source=PaymentSource.PURPOSE_FUND,
                purpose_fund=destination_fund,
                category=destination_fund.category,
                status=TransactionStatus.COMPLETED,
                reference=f"Transferred ৳{amount:,.2f} from {source_fund.name} to {destination_fund.name}"
            )

            Notification.objects.create(
                user=user,
                title="Inter-Fund Transfer Completed",
                message=f"Moved ৳{amount:,.2f} from {source_fund.name} to {destination_fund.name}. Reason: {reason or 'Manual transfer'}",
                notification_type=NotificationType.TRANSACTION
            )

        return transfer

    @classmethod
    def _check_anomaly_and_record(cls, txn: Transaction):
        """
        Runs real-time spending anomaly detection on completed transactions.
        """
        try:
            from fundshare_app.ml.anomaly_detector import AnomalyDetector
            detector = AnomalyDetector.get_instance()
            analysis = detector.analyze_transaction(txn)
            if analysis:
                AnomalyResult.objects.update_or_create(
                    transaction=txn,
                    defaults={
                        'user': txn.sender,
                        'is_anomaly': analysis['is_anomaly'],
                        'anomaly_score': analysis['anomaly_score'],
                        'reason': analysis['reason'],
                        'features_summary': analysis['features_summary'],
                        'model_version': analysis['model_version']
                    }
                )
                if analysis['is_anomaly'] and txn.sender:
                    Notification.objects.create(
                        user=txn.sender,
                        title="⚠️ Unusual Spending Flagged",
                        message=f"Transaction of ৳{txn.amount:,.2f} in {txn.category or 'General'} was flagged as unusual: {analysis['reason'][:120]}...",
                        notification_type=NotificationType.ANOMALY_ALERT,
                        metadata={'transaction_id': txn.transaction_id, 'score': analysis['anomaly_score']}
                    )
        except Exception as e:
            # Anomaly check failure must not rollback the transaction
            pass
