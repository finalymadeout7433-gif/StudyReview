import json
import os
from pathlib import Path
from django.conf import settings
from django.db import migrations


def guard_connection(schema_editor):
    """One-time DDL only; never elevate the application connection."""
    import MySQLdb
    database = schema_editor.connection.settings_dict['NAME']
    permitted = {'study_review_dev', 'test_study_review_dev'} | set(getattr(settings, 'AUTHORIZED_MIGRATION_SCHEMAS', ()))
    if database not in permitted:
        raise RuntimeError('Database guards can only be installed in isolated StudyReview schemas.')
    if os.environ.get('STUDY_ALLOW_SCHEMA_ADMIN') != '1':
        raise RuntimeError('初次迁移需以 STUDY_ALLOW_SCHEMA_ADMIN=1 安装隔离库触发器；详见运行说明。')
    default_path = Path(__file__).resolve().parents[2] / 'private' / 'database-credentials.json'
    config = json.loads(Path(os.environ.get('STUDY_CREDENTIALS_FILE', str(default_path))).read_text(encoding='utf-8-sig'))
    if config['host'] not in ('127.0.0.1', 'localhost'):
        raise RuntimeError('Only the authorized local MySQL server is supported.')
    return MySQLdb.connect(host=config['host'], port=int(config['port']), db=database,
        user=config['administrator_user'], passwd=config['administrator_password'], charset='utf8mb4')


def install_guards(apps, schema_editor):
    if schema_editor.connection.vendor != 'mysql':
        return
    statements = [
        """CREATE TRIGGER study_review_no_update BEFORE UPDATE ON learning_reviewrecord
        FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Review history is immutable'""",
        """CREATE TRIGGER study_review_no_delete BEFORE DELETE ON learning_reviewrecord
        FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Review history is immutable'""",
        """CREATE TRIGGER study_point_same_course_insert BEFORE INSERT ON learning_questionknowledgepoint
        FOR EACH ROW BEGIN
          IF (SELECT course_id FROM learning_wrongquestion WHERE id=NEW.question_id) <>
             (SELECT course_id FROM learning_knowledgepoint WHERE id=NEW.knowledge_point_id) THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Knowledge point must belong to the same course';
          END IF;
        END""",
        """CREATE TRIGGER study_point_same_course_update BEFORE UPDATE ON learning_questionknowledgepoint
        FOR EACH ROW BEGIN
          IF (SELECT course_id FROM learning_wrongquestion WHERE id=NEW.question_id) <>
             (SELECT course_id FROM learning_knowledgepoint WHERE id=NEW.knowledge_point_id) THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Knowledge point must belong to the same course';
          END IF;
        END""",
    ]
    for table in ('task', 'wrongquestion', 'knowledgepoint'):
        statements.append(f"""CREATE TRIGGER study_{table}_no_move BEFORE UPDATE ON learning_{table}
        FOR EACH ROW BEGIN
          IF OLD.course_id <> NEW.course_id THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Moving content between courses is not supported';
          END IF;
        END""")
    admin = guard_connection(schema_editor)
    try:
        with admin.cursor() as cursor:
            cursor.execute('SELECT TRIGGER_NAME FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA=%s',
                (schema_editor.connection.settings_dict['NAME'],))
            existing = {row[0] for row in cursor.fetchall()}
            for sql in statements:
                name = sql.split()[2]
                if name not in existing:
                    cursor.execute(sql)
    finally:
        admin.close()


def remove_guards(apps, schema_editor):
    if schema_editor.connection.vendor != 'mysql':
        return
    names = ['study_review_no_update', 'study_review_no_delete', 'study_point_same_course_insert',
        'study_point_same_course_update', 'study_task_no_move', 'study_wrongquestion_no_move', 'study_knowledgepoint_no_move']
    admin = guard_connection(schema_editor)
    try:
        with admin.cursor() as cursor:
            for name in names:
                cursor.execute(f'DROP TRIGGER IF EXISTS {name}')
    finally:
        admin.close()


class Migration(migrations.Migration):
    dependencies = [('learning', '0001_initial')]
    operations = [migrations.RunPython(install_guards, remove_guards)]
