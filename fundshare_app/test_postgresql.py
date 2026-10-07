import datetime
import io
import json
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from django.apps import apps
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, IntegrityError, transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from fundshare_app.models import User, Wallet, PurposeFund, FamilyPass, Transaction, FamilyPassTransaction, FundTransfer
from fundshare_app.management.commands.import_legacy_sqlite import Command


class PostgreSQLAccountingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='postgres-owner', phone='01742000001')
        self.member = User.objects.create_user(username='postgres-recipient', phone='01742000002')
        self.wallet = Wallet.objects.create(owner=self.user, balance='100')
        self.fund = PurposeFund.objects.create(owner=self.user, name='Shared Grocery', category='Grocery', recipient=self.member)
        self.other_fund = PurposeFund.objects.create(owner=self.user, name='Medical', category='Medicine')
        self.family_pass = FamilyPass.objects.create(owner=self.user, member=self.member, limit_amount='100', expiry_date=timezone.localdate() + datetime.timedelta(days=7))

    def test_default_database_has_real_row_locks(self):
        self.assertEqual(connection.vendor, 'postgresql')
        self.assertTrue(connection.features.has_select_for_update)

    def test_ledger_and_transfer_amount_constraints_are_enforced(self):
        for amount in ['0', '-1']:
            with self.assertRaises(IntegrityError), transaction.atomic():
                Transaction.objects.create(sender=self.user, amount=amount, transaction_type='SEND_MONEY')
            with self.assertRaises(IntegrityError), transaction.atomic():
                FundTransfer.objects.create(owner=self.user, source_fund=self.fund, destination_fund=self.other_fund, amount=amount)

    def test_family_pass_activity_cannot_record_negative_remaining_limit(self):
        payment = Transaction.objects.create(sender=self.member, amount='1', transaction_type='MERCHANT_PAYMENT', family_pass=self.family_pass)
        with self.assertRaises(IntegrityError), transaction.atomic():
            FamilyPassTransaction.objects.create(family_pass=self.family_pass, transaction=payment, member=self.member, amount='1', remaining_limit_after='-1')

    def test_wallet_and_pass_database_constraints_remain_enforced(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Wallet.objects.filter(pk=self.wallet.pk).update(balance='-1')
        with self.assertRaises(IntegrityError), transaction.atomic():
            FamilyPass.objects.filter(pk=self.family_pass.pk).update(used_amount='101')
        self.wallet.refresh_from_db()
        self.family_pass.refresh_from_db()
        self.assertEqual(str(self.wallet.balance), '100.00')
        self.assertEqual(str(self.family_pass.used_amount), '0.00')

    def test_query_indexes_exist_on_postgresql(self):
        for model, names in [(PurposeFund, ['fund_owner_status_idx', 'fund_recipient_status_idx']), (FamilyPass, ['pass_owner_status_exp_idx', 'pass_member_status_exp_idx']), (Transaction, ['txn_receiver_time_idx', 'txn_pass_time_idx', 'txn_merchant_time_idx'])]:
            with connection.cursor() as cursor:
                constraints = connection.introspection.get_constraints(cursor, model._meta.db_table)
            for name in names:
                self.assertTrue(constraints[name]['index'])


class LegacyImportTests(TransactionTestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.source = Path(self.temporary.name) / 'source.sqlite3'
        self.backup_dir = Path(self.temporary.name) / 'backups'
        with closing(sqlite3.connect(self.source)) as source, source:
            source.execute('CREATE TABLE django_migrations (app TEXT, name TEXT)')
            source.execute("INSERT INTO django_migrations VALUES ('fundshare_app', '0009_canonical_phones_and_lockouts')")

    def fixture(self):
        owner = User.objects.create_user(pk=400, username='import-owner', phone='01743000001', password='Preserve-password-71!')
        member = User.objects.create_user(pk=401, username='import-member', phone='01743000002')
        owner.set_transaction_pin('482951')
        owner.save()
        Wallet.objects.create(owner=owner, balance='123.45')
        PurposeFund.objects.create(owner=owner, recipient=member, name='Shared Fund', category='Grocery', allocated_amount='50', current_balance='25')
        family_pass = FamilyPass.objects.create(owner=owner, member=member, limit_amount='100', used_amount='25', expiry_date=timezone.localdate() + datetime.timedelta(days=7))
        payment = Transaction.objects.create(sender=member, amount='25', transaction_type='MERCHANT_PAYMENT', payment_source='FAMILY_PASS', family_pass=family_pass)
        FamilyPassTransaction.objects.create(family_pass=family_pass, transaction=payment, member=member, amount='25', remaining_limit_after='75')
        models = list(apps.get_app_config('fundshare_app').get_models())
        serialized = Command.serialize(models, 'default')
        for model in reversed(models):
            model.objects.all().delete()
        return serialized

    def run_import(self, fixture, tamper=False):
        original_serializer = Command.serialize
        def serialize(models, alias):
            if alias == 'legacy_import':
                return fixture
            return '[]' if tamper else original_serializer(models, alias)
        with patch.object(type(self), 'databases', self.databases | {'legacy_import'}), patch.object(Command, 'serialize', side_effect=serialize):
            call_command('import_legacy_sqlite', source=self.source, backup_dir=self.backup_dir, stdout=io.StringIO())

    def test_import_preserves_money_credentials_relationships_and_resets_sequences(self):
        # Only source serialization is mocked; import, FK checks, row comparison and sequences use PostgreSQL.
        self.run_import(self.fixture())
        owner = User.objects.get(username='import-owner')
        member = User.objects.get(username='import-member')
        self.assertEqual(owner.pk, 400)
        self.assertTrue(owner.check_password('Preserve-password-71!'))
        self.assertTrue(owner.check_transaction_pin('482951'))
        self.assertEqual(str(owner.wallet.balance), '123.45')
        fund = PurposeFund.objects.get(owner=owner)
        self.assertEqual(fund.recipient_id, member.pk)
        self.assertEqual(str(fund.current_balance), '25.00')
        family_pass = FamilyPass.objects.get(owner=owner)
        self.assertEqual(str(family_pass.used_amount), '25.00')
        self.assertEqual(FamilyPassTransaction.objects.get().transaction_id, Transaction.objects.get().pk)
        new_user = User.objects.create_user(username='after-import', phone='01743000003')
        self.assertGreater(new_user.pk, 401)
        self.assertEqual(len(list(self.backup_dir.glob('*.sqlite3'))), 1)

    def test_nonempty_destination_is_never_overwritten(self):
        User.objects.create_user(username='existing-customer')
        with self.assertRaisesRegex(CommandError, 'not empty'):
            call_command('import_legacy_sqlite', source=self.source, backup_dir=self.backup_dir, stdout=io.StringIO())
        self.assertEqual(User.objects.count(), 1)

    def test_failed_verification_rolls_back_entire_import(self):
        with self.assertRaisesRegex(CommandError, 'rolled back'):
            self.run_import(self.fixture(), tamper=True)
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(Wallet.objects.count(), 0)
        self.assertEqual(Transaction.objects.count(), 0)
        self.assertTrue(self.source.exists())

    def test_invalid_source_lengths_abort_without_truncating_money_records(self):
        fixture = json.loads(self.fixture())
        for row in fixture:
            if row['model'] == 'fundshare_app.purposefund':
                row['fields']['name'] = 'x' * 101
        with self.assertRaisesRegex(CommandError, 'exceeds PostgreSQL'):
            self.run_import(json.dumps(fixture))
        self.assertEqual(User.objects.count(), 0)
