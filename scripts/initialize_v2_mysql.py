"""NEW machine manual initialization. No existing DB/account/password replacement."""
import argparse
import json
from pathlib import Path
import sys
DATABASE = 'study_review_dev'

def create_new_database(connection, application_user):
    if not isinstance(application_user, str) or not application_user.strip():
        raise ValueError('An existing local application account is required.')
    with connection.cursor() as cursor:
        cursor.execute('SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s', (DATABASE,))
        if cursor.fetchone()[0]:
            raise RuntimeError('目标库已存在，停止。即使空库也不覆盖、不重新授权。')
        cursor.execute('SELECT COUNT(*) FROM mysql.user WHERE User=%s AND Host=%s', (application_user, 'localhost'))
        if cursor.fetchone()[0] != 1:
            raise RuntimeError('需要本人先配置已有 localhost 应用账户；不会创建账户或密码。')
        cursor.execute('CREATE DATABASE `study_review_dev` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci')
        cursor.execute('GRANT SELECT, INSERT, UPDATE, DELETE ON `study_review_dev`.* TO %s@%s', (application_user, 'localhost'))

def main(argv=None):
    parser = argparse.ArgumentParser(description='V2 新机器空库初始化；不用于已有项目升级。')
    parser.add_argument('--create-new-empty-database', action='store_true')
    parser.add_argument('--confirm-existing-account-dml-grant', action='store_true')
    args = parser.parse_args(argv)
    if not (args.create_new_empty_database and args.confirm_existing_account_dml_grant):
        print('未连接数据库，未修改权限。先阅读 docs/01-Windows首次启动.md；本人确认空库及已有账户最小DML授权后才可执行。')
        return 2
    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root))
    from config.local_runtime import resolve_credentials_file
    import MySQLdb
    config = json.loads(resolve_credentials_file(root).read_text(encoding='utf-8-sig'))
    if config.get('host') not in ('localhost', '127.0.0.1'):
        raise RuntimeError('Only the local MySQL server is supported.')
    connection = MySQLdb.connect(host=config['host'], port=int(config['port']),
        user=config['administrator_user'], passwd=config['administrator_password'], charset='utf8mb4')
    try:create_new_database(connection, config['application_user'])
    finally:connection.close()
    print('仅新建空库 study_review_dev，向既有应用账户授予四项DML；尚未迁移、恢复或填充数据。')
    return 0

if __name__ == '__main__':
    try:raise SystemExit(main())
    except Exception:
        print('初始化未完成；请本人检查本机安全配置及空库条件。未自动删库或回收现有权限。')
        raise SystemExit(1)
