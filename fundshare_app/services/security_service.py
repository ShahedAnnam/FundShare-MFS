import datetime
import hashlib
import re

from django.core.cache import cache
from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from fundshare_app.models import User


class SecurityError(Exception):
    def __init__(self, message, code, status=400):
        self.message = message
        self.code = code
        self.status = status


def login_rate_keys(request, identifier):
    # Share this cache across workers in production. Never store raw identifiers.
    identities = [f"account:{identifier.lower()}", f"ip:{request.META.get('REMOTE_ADDR', '')}"]
    return ['login:' + hashlib.sha256(identity.encode()).hexdigest() for identity in identities]


def check_login_rate(request, identifier):
    now = timezone.now().timestamp()
    for key in login_rate_keys(request, identifier):
        locked_until = cache.get(key + ':locked')
        if locked_until and locked_until > now:
            raise SecurityError('Too many failed login attempts. Try again in one minute.', 'LOGIN_RATE_LIMITED', 429)
        if locked_until:
            cache.delete(key + ':locked')


def record_login_failure(request, identifier):
    for key in login_rate_keys(request, identifier):
        failure_key = key + ':failures'
        if cache.add(failure_key, 1, timeout=settings.LOGIN_FAILURE_WINDOW_SECONDS):
            count = 1
        else:
            try:
                count = cache.incr(failure_key)
            except ValueError:
                cache.set(failure_key, 1, timeout=settings.LOGIN_FAILURE_WINDOW_SECONDS)
                count = 1
        if count >= settings.LOGIN_MAX_FAILED_ATTEMPTS:
            cache.add(key + ':locked', timezone.now().timestamp() + settings.AUTH_LOCKOUT_SECONDS, timeout=settings.AUTH_LOCKOUT_SECONDS)
            cache.delete(failure_key)


def clear_login_failures(request, identifier):
    # A successful account login must not reset IP-wide credential-spraying protection.
    cache.delete(login_rate_keys(request, identifier)[0] + ':failures')


def check_registration_rate(request):
    identity = request.META.get('REMOTE_ADDR', '')
    key = 'registration:' + hashlib.sha256(identity.encode()).hexdigest()
    if cache.add(key, 1, timeout=300):
        count = 1
    else:
        try:
            count = cache.incr(key)
        except ValueError:
            cache.set(key, 1, timeout=300)
            count = 1
    if count > 5:
        raise SecurityError('Too many signup attempts. Try again in five minutes.', 'REGISTRATION_RATE_LIMITED', 429)


def verify_pin(user, pin):
    error = None
    with transaction.atomic():
        # The first write also serializes PIN attempts on SQLite.
        User.objects.filter(pk=user.pk).update(pin_failed_attempts=F('pin_failed_attempts'))
        account = User.objects.select_for_update().get(pk=user.pk)
        if not account.is_active:
            error = SecurityError('Your account is inactive.', 'ACCOUNT_INACTIVE', 403)
        elif not account.transaction_pin:
            error = SecurityError('Set your transaction PIN in Settings before continuing.', 'PIN_NOT_SET', 403)
        elif account.pin_locked_until and account.pin_locked_until > timezone.now():
            error = SecurityError('Transaction PIN is locked. Try again in one minute.', 'PIN_LOCKED', 429)
        elif not isinstance(pin, str) or not pin:
            error = SecurityError('Enter your transaction PIN to confirm this action.', 'PIN_REQUIRED', 400)
        elif not account.check_transaction_pin(pin):
            if account.pin_locked_until:
                account.pin_failed_attempts = 0
                account.pin_locked_until = None
            account.pin_failed_attempts += 1
            if account.pin_failed_attempts >= settings.TRANSACTION_PIN_MAX_FAILED_ATTEMPTS:
                account.pin_locked_until = timezone.now() + datetime.timedelta(seconds=settings.AUTH_LOCKOUT_SECONDS)
            account.save(update_fields=['pin_failed_attempts', 'pin_locked_until'])
            error = SecurityError('Incorrect transaction PIN. No money was moved.', 'PIN_INVALID', 403)
        else:
            account.pin_failed_attempts = 0
            account.pin_locked_until = None
            account.save(update_fields=['pin_failed_attempts', 'pin_locked_until'])
    if error:
        raise error


def validate_new_pin(pin):
    if not isinstance(pin, str) or not re.fullmatch(r'[0-9]{6}', pin):
        raise SecurityError('Your transaction PIN must contain exactly six digits.', 'INVALID_NEW_PIN')
    if len(set(pin)) == 1 or pin in ('012345', '123456', '234567', '345678', '456789', '987654', '876543', '765432', '654321'):
        raise SecurityError('Choose a PIN without repeated or sequential digits.', 'WEAK_PIN')
