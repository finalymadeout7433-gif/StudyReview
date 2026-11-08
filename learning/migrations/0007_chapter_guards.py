"""MySQL protects curriculum boundaries even when ORM validation is bypassed."""
from importlib import import_module
from django.db import migrations

NAMES = ['study_chapter_insert', 'study_chapter_update',
         'study_point_chapter_insert', 'study_point_chapter_update']


def install(apps, schema_editor):
    if schema_editor.connection.vendor != 'mysql':
        return
    connect = import_module('learning.migrations.0002_database_guards').guard_connection
    chapter_check = """
        IF NEW.parent_id IS NOT NULL THEN
          IF NEW.parent_id = NEW.id OR
             (SELECT course_id FROM learning_chapter WHERE id=NEW.parent_id) <> NEW.course_id OR
             (SELECT parent_id FROM learning_chapter WHERE id=NEW.parent_id) IS NOT NULL THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Parent must be a root chapter in the same course';
          END IF;
        END IF;
    """
    point_check = """
        IF NEW.chapter_id IS NOT NULL AND
           (SELECT course_id FROM learning_chapter WHERE id=NEW.chapter_id) <> NEW.course_id THEN
          SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Chapter must belong to the same course';
        END IF;
    """
    statements = [
        'CREATE TRIGGER study_chapter_insert BEFORE INSERT ON learning_chapter FOR EACH ROW BEGIN '+chapter_check+' END',
        '''CREATE TRIGGER study_chapter_update BEFORE UPDATE ON learning_chapter FOR EACH ROW BEGIN
          IF NEW.course_id <> OLD.course_id THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Moving chapters between courses is not supported';
          END IF;
          IF NEW.parent_id IS NOT NULL AND EXISTS(SELECT 1 FROM learning_chapter WHERE parent_id=OLD.id) THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='A chapter with sections must remain a root';
          END IF;
        '''+chapter_check+' END',
        'CREATE TRIGGER study_point_chapter_insert BEFORE INSERT ON learning_knowledgepoint FOR EACH ROW BEGIN '+point_check+' END',
        'CREATE TRIGGER study_point_chapter_update BEFORE UPDATE ON learning_knowledgepoint FOR EACH ROW BEGIN '+point_check+' END',
    ]
    admin = connect(schema_editor)
    try:
        with admin.cursor() as cursor:
            cursor.execute('SELECT TRIGGER_NAME FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA=%s',
                           (schema_editor.connection.settings_dict['NAME'],))
            existing = {row[0] for row in cursor.fetchall()}
            for name, statement in zip(NAMES, statements):
                if name not in existing:
                    cursor.execute(statement)
    finally:
        admin.close()


def uninstall(apps, schema_editor):
    if schema_editor.connection.vendor != 'mysql':
        return
    admin = import_module('learning.migrations.0002_database_guards').guard_connection(schema_editor)
    try:
        with admin.cursor() as cursor:
            for name in NAMES:
                cursor.execute('DROP TRIGGER IF EXISTS '+name)
    finally:
        admin.close()


class Migration(migrations.Migration):
    dependencies = [('learning', '0006_course_chapters')]
    operations = [migrations.RunPython(install, uninstall)]
