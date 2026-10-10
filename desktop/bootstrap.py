"""Explicit new-machine initialization, only for a schema absent before this call."""
from __future__ import annotations
import json
import io
import os
from pathlib import Path
import sys
from .runtime import DesktopError, InstanceLock, RuntimePaths, inside, child_path


def validate_request(data_dir, credentials_file, create_confirmed, grant_confirmed):
    if not (create_confirmed and grant_confirmed):
        raise DesktopError('必须明确确认新建空库及向已有应用账户授予四项 DML 权限。')
    if not data_dir or not credentials_file:
        raise DesktopError('初始化必须明确指定程序之外的数据目录和本人准备的安全配置文件。')
    if not Path(data_dir).is_absolute() or not Path(credentials_file).is_absolute():
        raise DesktopError('数据目录和安全配置必须是绝对路径，不能依赖当前工作目录。')


def initialize_new_installation(resources, data_dir, credentials_file, *,
        create_confirmed=False, grant_confirmed=False, synthetic_demo=False):
    validate_request(data_dir, credentials_file, create_confirmed, grant_confirmed)
    paths = RuntimePaths.resolve(resources, data_dir, credentials_file)
    if inside(paths.credentials, paths.resources):
        raise DesktopError('安全配置必须私存于程序目录之外。')
    if getattr(sys, 'frozen', False) and inside(paths.credentials, Path(sys.executable).resolve().parent):
        raise DesktopError('安全配置必须私存于程序目录之外。')
    plan = child_path(paths.private, 'schema-plan.json')
    if plan.exists():
        raise DesktopError('已有维护计划，停止初始化；请保留现场并按恢复说明检查。')
    original_env = dict(os.environ)
    connection = None
    with InstanceLock(paths.lock):
        try:
            import MySQLdb
            config = json.loads(paths.credentials.read_text(encoding='utf-8-sig'))
            if config.get('host') not in ('localhost', '127.0.0.1'):
                raise DesktopError('只支持本人本机 MySQL。')
            if config.get('application_user') == config.get('administrator_user'):
                raise DesktopError('运行应用账户必须与初始化管理员分开。')
            from scripts.initialize_v2_mysql import create_new_database
            connection = MySQLdb.connect(host=config['host'], port=int(config['port']),
                user=config['administrator_user'], passwd=config['administrator_password'],
                charset='utf8mb4', connect_timeout=5)
            # Rejects ANY pre-existing schema, even empty; never creates/reset users.
            create_new_database(connection, config['application_user'])
            connection.close()
            connection = None
            with plan.open('x', encoding='utf-8') as stream:
                json.dump({'purpose': 'study-review-v2-upgrade',
                           'database': 'study_review_dev'}, stream)
            paths.apply_environment('config.settings')
            os.environ['DJANGO_SETTINGS_MODULE'] = 'config.v2_migration_settings'
            os.environ['STUDY_ALLOW_SCHEMA_ADMIN'] = '1'
            import django
            django.setup()
            from django.core.management import call_command
            call_command('migrate', interactive=False, verbosity=0,
                         stdout=io.StringIO(), stderr=io.StringIO())
            if synthetic_demo:
                # This branch is reachable only after this invocation created the schema.
                call_command('seed_demo', verbosity=0,
                             stdout=io.StringIO(), stderr=io.StringIO())
            from django.db import connections
            connections.close_all()
            plan.unlink()
            from .setup_wizard import persist_reference
            persist_reference(paths.resources, paths.data, paths.credentials, confirmed=True)
            return {'database': 'study_review_dev', 'new_schema_created': True,
                    'migrations_applied': True, 'synthetic_demo': bool(synthetic_demo),
                    'existing_account_grant': ['SELECT', 'INSERT', 'UPDATE', 'DELETE'],
                    'new_database_users_created': False, 'real_ai_called': False}
        except DesktopError:
            raise
        except Exception:
            # Do not stringify connector errors: they may contain private values.
            raise DesktopError('初始化未完成：库可能已存在、账户未准备或权限不足。'
                '没有自动删库或覆盖数据；保留现场，按首次启动／故障说明检查。') from None
        finally:
            if connection is not None:
                connection.close()
            os.environ.clear()
            os.environ.update(original_env)
