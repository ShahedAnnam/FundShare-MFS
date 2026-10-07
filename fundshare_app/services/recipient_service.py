from fundshare_app.models import UserRole
from fundshare_app.services.phone_utils import find_user_by_phone, is_valid_bd_phone


class RecipientService:
    """Resolve registered recipients globally. Contacts are never consulted."""

    @staticmethod
    def check_recipient_eligibility(phone, feature='SEND_MONEY'):
        if not isinstance(phone, str) or not phone.strip():
            return False, 'Enter the recipient phone number.', None
        if not is_valid_bd_phone(phone):
            return False, 'Enter a valid Bangladesh mobile phone number.', None
        if not isinstance(feature, str):
            return False, 'Select a valid transaction feature.', None
        recipient = find_user_by_phone(phone)
        if feature.upper() in ['MOBILE_RECHARGE', 'RECHARGE', 'BILL_PAYMENT', 'CASH_OUT']:
            return True, None, recipient
        if recipient is None:
            return False, 'This account is not registered yet.', None
        if not recipient.is_active:
            return False, 'This account is inactive and cannot receive this transaction.', recipient
        if feature.upper() in ['FAMILY_PASS', 'FAMILYPASS'] and recipient.effective_role != UserRole.CUSTOMER:
            return False, 'FamilyPass recipients must be active customer accounts.', recipient
        return True, None, recipient

    @staticmethod
    def rejection_code(phone, recipient):
        if not isinstance(phone, str) or not is_valid_bd_phone(phone):
            return 'RECIPIENT_PHONE_INVALID'
        if recipient is None:
            return 'RECIPIENT_NOT_REGISTERED'
        if not recipient.is_active:
            return 'RECIPIENT_INACTIVE'
        return 'RECIPIENT_INELIGIBLE'
