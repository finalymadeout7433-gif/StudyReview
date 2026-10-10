"""Only protect the two new scheduling tables; legacy triggers are untouched."""
import os
from django.conf import settings
from django.db import migrations

NAMES = ('study_schedule_no_update', 'study_schedule_no_delete')


def _allowed_connection(schema_editor):
    connection = schema_editor.connection
    if connection.vendor != 'mysql':
        return None
    name = connection.settings_dict['NAME']
    authorized = getattr(settings, 'AUTHORIZED_MIGRATION_SCHEMAS',
                         ('study_review_dev', 'test_study_review_dev'))
    if name not in authorized:
        raise RuntimeError('Scheduling guards may only migrate isolated StudyReview schemas.')
    if os.environ.get('STUDY_ALLOW_SCHEMA_ADMIN') != '1':
        raise RuntimeError('Scheduling guard DDL requires explicit STUDY_ALLOW_SCHEMA_ADMIN=1.')
    # Use the already-authorized migration connection, never open credentials here.
    return connection


def install_guards(apps, schema_editor):
    connection = _allowed_connection(schema_editor)
    if connection is None:
        return
    with connection.cursor() as cursor:
        cursor.execute('SELECT TRIGGER_NAME FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA=%s',
                       [connection.settings_dict['NAME']])
        existing = {row[0] for row in cursor.fetchall()}
        for name, operation in zip(NAMES, ('UPDATE', 'DELETE')):
            if name not in existing:
                cursor.execute(f"CREATE TRIGGER {name} BEFORE {operation} ON scheduling_scheduleevent "
                               "FOR EACH ROW SIGNAL SQLSTATE '45000' "
                               "SET MESSAGE_TEXT = 'Scheduling history is immutable'")


def remove_guards(apps, schema_editor):
    connection = _allowed_connection(schema_editor)
    if connection is None:
        return
    with connection.cursor() as cursor:
        for name in NAMES:
            cursor.execute(f'DROP TRIGGER IF EXISTS {name}')


class Migration(migrations.Migration):
    dependencies = [('scheduling', '0001_initial')]
    operations = [migrations.RunPython(install_guards, remove_guards)]
