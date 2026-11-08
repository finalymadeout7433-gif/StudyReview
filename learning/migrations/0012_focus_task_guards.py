from importlib import import_module
from django.db import migrations
NAMES=['study_focus_task_insert','study_focus_task_update']
def install(apps,schema_editor):
    if schema_editor.connection.vendor!='mysql':return
    admin=import_module('learning.migrations.0002_database_guards').guard_connection(schema_editor)
    try:
        with admin.cursor() as c:
            for name,event in zip(NAMES,['INSERT','UPDATE']):
                c.execute('CREATE TRIGGER '+name+' BEFORE '+event+''' ON learning_focussession FOR EACH ROW BEGIN
                IF NEW.task_id IS NOT NULL AND NOT ((SELECT course_id FROM learning_task WHERE id=NEW.task_id) <=> NEW.course_id) THEN
                  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Focus task must belong to the focus course';
                END IF;
                END''')
    finally:admin.close()
def uninstall(apps,schema_editor):
    if schema_editor.connection.vendor!='mysql':return
    admin=import_module('learning.migrations.0002_database_guards').guard_connection(schema_editor)
    try:
        with admin.cursor() as c:
            for name in NAMES:c.execute('DROP TRIGGER IF EXISTS '+name)
    finally:admin.close()
class Migration(migrations.Migration):
    dependencies=[('learning','0011_focus_task_context')]
    operations=[migrations.RunPython(install,uninstall)]
