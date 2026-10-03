import re
from typing import Optional, List
from django.contrib.auth import get_user_model
from django.db.models import Q

User = get_user_model()


def normalize_phone(raw_phone: Optional[str]) -> str:
    """
    Normalizes a Bangladesh mobile phone number to canonical 11-digit format: 01XXXXXXXXX.
    Handles:
      - +8801XXXXXXXXX -> 01XXXXXXXXX
      - 8801XXXXXXXXX  -> 01XXXXXXXXX
      - 008801XXXXXXXXX -> 01XXXXXXXXX
      - 1XXXXXXXXX (10 digits) -> 01XXXXXXXXX
      - Embedded spaces, dashes, parentheses: "+880 1711-000001" -> "01711000001"
    """
    if not raw_phone:
        return ""

    # Remove all whitespace, dashes, parens, dots
    cleaned = re.sub(r'[\s\-\(\)\.]', '', str(raw_phone).strip())

    # If it starts with +880, strip +88
    if cleaned.startswith('+880'):
        cleaned = cleaned[3:]
    elif cleaned.startswith('00880'):
        cleaned = cleaned[4:]
    elif cleaned.startswith('880') and len(cleaned) >= 13:
        cleaned = cleaned[2:]
    elif cleaned.startswith('+'):
        cleaned = cleaned[1:]

    # If 10 digits starting with 1, prepend 0
    if len(cleaned) == 10 and cleaned.startswith('1'):
        cleaned = '0' + cleaned

    return cleaned


def is_valid_bd_phone(phone: Optional[str]) -> bool:
    """
    Validates whether the phone number is a valid 11-digit Bangladesh mobile number.
    Standard operators start with 013, 014, 015, 016, 017, 018, 019.
    """
    norm = normalize_phone(phone)
    return bool(re.match(r'^01[3-9]\d{8}$', norm))


def get_phone_variations(phone: Optional[str]) -> List[str]:
    """
    Returns common variations for phone matching against database records:
    [canonical '01XXXXXXXXX', '+8801XXXXXXXXX', '8801XXXXXXXXX', raw]
    """
    if not phone:
        return []
    norm = normalize_phone(phone)
    raw = str(phone).strip()
    variations = set()
    if norm:
        variations.add(norm)
        variations.add(f"+88{norm}")
        variations.add(f"88{norm}")
        if len(norm) == 11 and norm.startswith('0'):
            variations.add(norm[1:])  # 10 digits
    if raw:
        variations.add(raw)
    return list(variations)


def find_user_by_phone_or_username(identifier: Optional[str]):
    """
    Finds a User by either username or phone number (with normalization).
    """
    if not identifier:
        return None

    ident_str = str(identifier).strip()

    # 1. Try exact username match (case-insensitive)
    user = User.objects.filter(username__iexact=ident_str).first()
    if user:
        return user

    # 2. Try phone variations
    variations = get_phone_variations(ident_str)
    user = User.objects.filter(phone__in=variations).first()
    if user:
        return user

    # 3. Try exact phone match if any
    return User.objects.filter(phone=ident_str).first()
