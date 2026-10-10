"""Only new attachment tables are guarded; existing review tables are untouched."""
import os

from django.conf import settings
from django.db import migrations


TABLES = (
    ('image', 'attachments_attachment'),
    ('manifest', 'attachments_reviewimagemanifest'),
    ('snapshot', 'attachments_reviewimagesnapshot'),
)


def _check_authorized(schema_editor):
    name = str(schema_editor.connection.settings_dict['NAME'])
    declared = getattr(settings, 'AUTHORIZED_MIGRATION_SCHEMAS', ())
    if not isinstance(declared, (tuple, list, set, frozenset)) or any(not isinstance(item, str) for item in declared):
        raise RuntimeError('AUTHORIZED_MIGRATION_SCHEMAS must be an exact schema-name collection.')
    allowed = {'study_review_dev', 'test_study_review_dev', *declared}
    if name not in allowed or os.environ.get('STUDY_ALLOW_SCHEMA_ADMIN') != '1':
        raise RuntimeError('Image guard DDL requires an explicitly authorized isolated schema and STUDY_ALLOW_SCHEMA_ADMIN=1.')
    if schema_editor.connection.settings_dict.get('HOST') not in ('localhost', '127.0.0.1'):
        raise RuntimeError('Image guards may only be installed on the authorized local MySQL server.')


def install_guards(apps, schema_editor):
    if schema_editor.connection.vendor != 'mysql':
        return
    _check_authorized(schema_editor)
    with schema_editor.connection.cursor() as cursor:
        cursor.execute('SELECT TRIGGER_NAME FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA=%s',
            [schema_editor.connection.settings_dict['NAME']])
        existing = {row[0] for row in cursor.fetchall()}
        for label, table in TABLES:
            for event in ('UPDATE', 'DELETE'):
                trigger = f'att_{label}_no_{event.lower()}'
                if trigger not in existing:
                    cursor.execute(f"CREATE TRIGGER {trigger} BEFORE {event} ON {table} "
                        "FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Image history is immutable'")


def remove_guards(apps, schema_editor):
    if schema_editor.connection.vendor != 'mysql':
        return
    _check_authorized(schema_editor)
    with schema_editor.connection.cursor() as cursor:
        for label, table in TABLES:
            for event in ('UPDATE', 'DELETE'):
                cursor.execute(f'DROP TRIGGER IF EXISTS att_{label}_no_{event.lower()}')


class Migration(migrations.Migration):
    atomic = False
    dependencies = [('attachments', '0001_initial')]
    operations = [migrations.RunPython(install_guards, remove_guards)]
