"""One-time, verified import; SQLite is never an application runtime database."""
import hashlib
import itertools
import json
import sqlite3
from copy import deepcopy
from contextlib import closing
from collections import Counter
from pathlib import Path

from django.apps import apps
from django.core import serializers
from django.core.management.base import BaseCommand, CommandError
from django.core.management.color import no_style
from django.db import connections, transaction
from django.utils import timezone


class Command(BaseCommand):
    help = 'Import an up-to-date legacy SQLite snapshot into an empty, migrated PostgreSQL database.'

    def add_arguments(self, parser):
        parser.add_argument('--source', required=True, type=Path)
        parser.add_argument('--backup-dir', default='.local/backups', type=Path)

    def handle(self, *args, **options):
        destination = connections['default']
        if destination.vendor != 'postgresql':
            raise CommandError('The destination must be PostgreSQL.')
        source = options['source'].resolve()
        if not source.is_file():
            raise CommandError('The legacy SQLite file does not exist.')
        models = [apps.get_model('auth', 'Group'), *apps.get_app_config('fundshare_app').get_models(), apps.get_model('sessions', 'Session')]
        if any(model.objects.using('default').exists() for model in models):
            raise CommandError('Destination is not empty. Import refuses to merge or overwrite existing accounts and money.')

        backup_dir = options['backup_dir'].resolve()
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = backup_dir / ('legacy-' + timezone.now().strftime('%Y%m%d-%H%M%S-%f') + '.sqlite3')
        with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as reader, closing(sqlite3.connect(backup)) as snapshot:
            reader.backup(snapshot)
        alias = 'legacy_import'
        configuration = deepcopy(destination.settings_dict)
        configuration.update(ENGINE='django.db.backends.sqlite3', NAME=backup.as_uri() + '?mode=ro', USER='', PASSWORD='', HOST='', PORT='', CONN_MAX_AGE=0, OPTIONS={'uri': True})
        connections.databases[alias] = configuration
        legacy = connections[alias]
        try:
            with legacy.cursor() as cursor:
                cursor.execute("SELECT 1 FROM django_migrations WHERE app='fundshare_app' AND name='0009_canonical_phones_and_lockouts'")
                if cursor.fetchone() is None:
                    raise CommandError('Source must already have migration 0009 applied. Upgrade a copy using the legacy release first.')
            original = self.serialize(models, alias)
            serialized_counts = Counter(row['model'] for row in json.loads(original))
            counts = {model._meta.label: serialized_counts[model._meta.label_lower] for model in models}
            self.check_lengths(original)
            with transaction.atomic(using='default'):
                with destination.cursor() as cursor:
                    tables = [model._meta.db_table for model in models]
                    cursor.execute('LOCK TABLE ' + ', '.join(destination.ops.quote_name(table) for table in tables) + ' IN ACCESS EXCLUSIVE MODE')
                if any(model.objects.using('default').exists() for model in models):
                    raise CommandError('Destination changed during import. No data was imported.')
                deferred = []
                for obj in serializers.deserialize('json', original, using='default', handle_forward_references=True):
                    obj.save(using='default')
                    if obj.deferred_fields:
                        deferred.append(obj)
                for obj in deferred:
                    obj.save_deferred_fields(using='default')
                destination.check_constraints()
                imported = self.serialize(models, 'default')
                if self.digest(original) != self.digest(imported):
                    raise CommandError('Imported records do not exactly match the snapshot. Import rolled back.')
                with destination.cursor() as cursor:
                    for statement in destination.ops.sequence_reset_sql(no_style(), models):
                        cursor.execute(statement)
            self.stdout.write(self.style.SUCCESS('Verified PostgreSQL import: ' + str(sum(counts.values())) + ' records; all serialized fields, balances, credentials and relationships match.'))
            self.stdout.write('SQLite backup retained at ' + str(backup))
            for label, count in counts.items():
                self.stdout.write(f'{label}: {count}')
        except CommandError:
            raise
        except Exception as exc:
            raise CommandError(f'Import failed ({type(exc).__name__}). PostgreSQL changes rolled back; the source and snapshot are preserved.') from None
        finally:
            legacy.close()
            del connections[alias]
            connections.databases.pop(alias, None)

    @staticmethod
    def serialize(models, alias):
        rows = itertools.chain.from_iterable(model.objects.using(alias).order_by(model._meta.pk.name).iterator() for model in models)
        return serializers.serialize('json', rows, use_natural_foreign_keys=True)

    @staticmethod
    def digest(serialized):
        return hashlib.sha256(json.dumps(json.loads(serialized), sort_keys=True, separators=(',', ':')).encode()).hexdigest()

    @staticmethod
    def check_lengths(serialized):
        for row in json.loads(serialized):
            model = apps.get_model(row['model'])
            for field in model._meta.fields:
                value = row['fields'].get(field.name)
                if isinstance(value, str) and field.max_length and len(value) > field.max_length:
                    raise CommandError(f'{row["model"]} record {row["pk"]}: {field.name} exceeds PostgreSQL field length. Fix a source copy; no values were truncated.')
