from typing import Optional, Tuple, Dict, Any
from django.contrib.auth import get_user_model
from fundshare_app.models import Contact, UserRole
from fundshare_app.services.recipient_service import RecipientService

User = get_user_model()


class ContactService:
    """
    Centralized service for Contact Book management, account matching,
    and feature-level recipient eligibility checks.
    """

    @classmethod
    def get_contact_account_info(cls, contact: Contact) -> Dict[str, Any]:
        """
        Determines whether a contact's phone number belongs to an existing
        registered user, and returns their public status and feature permissions.
        NEVER exposes private financial data (wallet balance, transactions, PIN).
        """
        matched_user = contact.matched_user
        is_registered = matched_user is not None
        can_receive_family_pass = bool(matched_user and matched_user.is_active and matched_user.effective_role == UserRole.CUSTOMER)
        can_receive_transfer = bool(matched_user and matched_user.is_active)

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
                "send_money": can_receive_transfer,
                "fund_share": can_receive_transfer,
                "family_pass": can_receive_family_pass,
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
        """Compatibility entry point; eligibility never requires an address-book entry."""
        return RecipientService.check_recipient_eligibility(identifier, feature)
