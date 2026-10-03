from typing import Optional, Tuple, Dict, Any
from django.contrib.auth import get_user_model
from fundshare_app.models import Contact
from fundshare_app.services.phone_utils import normalize_phone, find_user_by_phone_or_username

User = get_user_model()


class ContactService:
    """
    Centralized service for Contact Book management, account matching,
    and feature-level recipient eligibility checks.
    """

    @classmethod
    def get_contact_account_info(cls, contact: Contact) -> Dict[str, Any]:
        """
        Determines whether a contact's phone number or username belongs to an existing
        registered user, and returns their public status and feature permissions.
        NEVER exposes private financial data (wallet balance, transactions, PIN).
        """
        matched_user = contact.matched_user
        is_registered = matched_user is not None

        return {
            "id": contact.id,
            "name": contact.name,
            "phone": contact.phone,
            "username": matched_user.username if matched_user else (contact.username or None),
            "is_registered": is_registered,
            "account_status": "REGISTERED" if is_registered else "NOT_REGISTERED",
            "account_id": matched_user.id if matched_user else None,
            "avatar_url": getattr(matched_user, 'avatar_url', '') if matched_user else '',
            "role": getattr(matched_user, 'role', None) if matched_user else None,
            "created_at": contact.created_at.isoformat() if contact.created_at else None,
            "updated_at": contact.updated_at.isoformat() if contact.updated_at else None,
            "allowed_features": {
                "send_money": is_registered,
                "fund_share": is_registered,
                "family_pass": is_registered,
                "mobile_recharge": True,  # Non-registered numbers can always receive mobile recharge
                "bill_payment": True,
            }
        }

    @classmethod
    def check_recipient_eligibility(
        cls,
        identifier: Optional[str],
        feature: str = 'SEND_MONEY'
    ) -> Tuple[bool, Optional[str], Optional[Any]]:
        """
        Validates whether a recipient (phone number or username) is eligible for a specific feature.

        Returns:
            (is_eligible: bool, error_message: Optional[str], matched_user: Optional[User])
        """
        feature_upper = feature.upper()
        clean_ident = str(identifier).strip() if identifier else ''

        if not clean_ident:
            return False, "Recipient phone or username is required.", None

        matched_user = find_user_by_phone_or_username(clean_ident)

        # 1. MOBILE_RECHARGE: DOES NOT REQUIRE A REGISTERED ACCOUNT
        if feature_upper in ['MOBILE_RECHARGE', 'RECHARGE', 'BILL_PAYMENT', 'CASH_OUT']:
            return True, None, matched_user

        # 2. SEND_MONEY: STRICTLY REQUIRES A REGISTERED ACCOUNT
        if feature_upper in ['SEND_MONEY', 'SEND']:
            if not matched_user:
                return (
                    False,
                    "Recipient does not have a registered account. Send Money requires an active FundShare account.",
                    None
                )
            return True, None, matched_user

        # 3. FUND_SHARE: STRICTLY REQUIRES A REGISTERED ACCOUNT
        if feature_upper in ['FUND_SHARE', 'PURPOSE_FUND', 'FUNDS']:
            if not matched_user:
                return (
                    False,
                    "Recipient does not have a registered account. FundShare requires an active FundShare account.",
                    None
                )
            return True, None, matched_user

        # 4. FAMILY_PASS: STRICTLY REQUIRES A REGISTERED ACCOUNT
        if feature_upper in ['FAMILY_PASS', 'FAMILYPASS']:
            if not matched_user:
                return (
                    False,
                    "Recipient does not have a registered account. FamilyPass requires a registered user.",
                    None
                )
            return True, None, matched_user

        # Default fallback
        if not matched_user:
            return False, "Recipient does not have a registered account.", None

        return True, None, matched_user
