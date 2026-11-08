"""Course ownership is permanent: changing it would transfer all child history."""
from importlib import import_module
from django.db import migrations

NAME='study_course_owner_immutable'

def install(apps,schema_editor):
    if schema_editor.connection.vendor!='mysql':return
    admin=import_module('learning.migrations.0002_database_guards').guard_connection(schema_editor)
    try:
        with admin.cursor() as cursor:
            cursor.execute('SELECT COUNT(*) FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA=%s AND TRIGGER_NAME=%s',(schema_editor.connection.settings_dict['NAME'],NAME))
            if not cursor.fetchone()[0]:
                cursor.execute('CREATE TRIGGER '+NAME+''' BEFORE UPDATE ON learning_course FOR EACH ROW BEGIN
                    IF NEW.owner_id <> OLD.owner_id THEN
                        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Course ownership is immutable';
                    END IF;
                END''')
    finally:admin.close()

def uninstall(apps,schema_editor):
    if schema_editor.connection.vendor!='mysql':return
    admin=import_module('learning.migrations.0002_database_guards').guard_connection(schema_editor)
    try:
        with admin.cursor() as cursor:cursor.execute('DROP TRIGGER IF EXISTS '+NAME)
    finally:admin.close()

class Migration(migrations.Migration):
    dependencies=[('learning','0012_focus_task_guards')]
    operations=[migrations.RunPython(install,uninstall)]
