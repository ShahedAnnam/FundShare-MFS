import datetime
import re

from django.db import migrations, models
from django.utils import timezone


def canonical_phone(raw):
    if not raw:
        return None
    phone = re.sub(r'[\s\-\(\)\.]', '', raw.strip())
    if phone.startswith('+880'):
        phone = phone[3:]
    elif phone.startswith('00880'):
        phone = phone[4:]
    elif phone.startswith('880') and len(phone) >= 13:
        phone = phone[2:]
    if len(phone) == 10 and phone.startswith('1'):
        phone = '0' + phone
    return phone or None


def normalize_accounts(apps, schema_editor):
    User = apps.get_model('fundshare_app', 'User')
    accounts = User.objects.using(schema_editor.connection.alias)
    seen = {}
    updates = []
    for account_id, raw in accounts.values_list('pk', 'phone').iterator():
        phone = canonical_phone(raw)
        if phone and not re.fullmatch(r'01[3-9][0-9]{8}', phone):
            raise RuntimeError(f'Account {account_id} has an invalid phone number. Correct it or clear it before migrating.')
        if phone and phone in seen:
            raise RuntimeError(f'Accounts {seen[phone]} and {account_id} share a normalized phone number. Resolve ownership before migrating; accounts will not be merged.')
        if phone:
            seen[phone] = account_id
        if raw != phone:
            updates.append((account_id, phone))
    for account_id, phone in updates:
        accounts.filter(pk=account_id).update(phone=phone)
    deadline = timezone.now() + datetime.timedelta(seconds=60)
    accounts.filter(pin_locked_until__gt=deadline).update(pin_locked_until=deadline)


class Migration(migrations.Migration):
    dependencies = [('fundshare_app', '0008_customer_roles')]

    operations = [
        migrations.RunPython(normalize_accounts, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='user',
            constraint=models.CheckConstraint(
                condition=models.Q(phone__isnull=True) | models.Q(phone__regex=r'\A01[3-9][0-9]{8}\Z'),
                name='user_canonical_phone',
            ),
        ),
    ]
