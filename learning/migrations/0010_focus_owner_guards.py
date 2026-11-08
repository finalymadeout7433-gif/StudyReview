from importlib import import_module
from django.db import migrations

NAMES=['study_focus_owner_insert','study_focus_owner_update']

def install(apps,schema_editor):
    if schema_editor.connection.vendor!='mysql':return
    admin=import_module('learning.migrations.0002_database_guards').guard_connection(schema_editor)
    try:
        with admin.cursor() as cursor:
            for name,event in zip(NAMES,['INSERT','UPDATE']):
                cursor.execute('CREATE TRIGGER '+name+' BEFORE '+event+''' ON learning_focussession FOR EACH ROW BEGIN
                  IF NEW.course_id IS NOT NULL AND (SELECT owner_id FROM learning_course WHERE id=NEW.course_id) <> NEW.owner_id THEN
                    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Focus course must belong to its owner';
                  END IF;
                END''')
    finally:admin.close()

def uninstall(apps,schema_editor):
    if schema_editor.connection.vendor!='mysql':return
    admin=import_module('learning.migrations.0002_database_guards').guard_connection(schema_editor)
    try:
        with admin.cursor() as cursor:
            for name in NAMES:cursor.execute('DROP TRIGGER IF EXISTS '+name)
    finally:admin.close()

class Migration(migrations.Migration):
    dependencies=[('learning','0009_focus_active_guard')]
    operations=[migrations.RunPython(install,uninstall)]
