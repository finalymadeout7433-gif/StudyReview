"""Create fresh named synthetic schemas; never alters a pre-existing schema or user."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import uuid

def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', required=True)
    parser.add_argument('--credentials-file', required=True)
    parser.add_argument('--confirm-create-isolated-schemas', action='store_true')
    args = parser.parse_args(argv)
    if not args.confirm_create_isolated_schemas:
        raise ValueError('No database access: explicitly confirm creation of isolated synthetic schemas.')
    data = Path(args.data_dir).resolve()
    root = Path(__file__).resolve().parent.parent
    if data.is_relative_to(root):
        raise ValueError('Development data and credentials must stay outside the checkout.')
    config_path = Path(args.credentials_file).resolve()
    if config_path.is_relative_to(root):
        raise ValueError('Do not store private configuration in the repository.')
    private = data / 'private'
    if (private / 'development-environment.json').exists() or (private / 'runtime.json').exists():
        raise ValueError('A development environment already exists; reuse it, never reinitialize.')
    config = json.loads(config_path.read_text(encoding='utf-8-sig'))
    if config.get('host') not in ('127.0.0.1', 'localhost'):
        raise ValueError('Only local MySQL is supported.')
    suffix = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:8]
    names = ('study_review_v2_dev_' + suffix, 'test_study_review_v2_' + suffix)
    import MySQLdb
    connection = MySQLdb.connect(host=config['host'], port=int(config['port']),
        user=config['administrator_user'], passwd=config['administrator_password'],
        charset='utf8mb4', connect_timeout=5)
    try:
        with connection.cursor() as cursor:
            for name in names:
                assert re.fullmatch(r'(study_review_v2_dev_|test_study_review_v2_)[A-Za-z0-9_]+', name)
                cursor.execute('SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s', (name,))
                if cursor.fetchone()[0]:
                    raise ValueError('Generated schema exists; stop without any overwrite.')
            for name in names:
                cursor.execute('CREATE DATABASE ' + chr(96) + name + chr(96) +
                               ' CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci')
    finally:
        connection.close()
    private.mkdir(parents=True, exist_ok=True)
    for name, value in (
        ('runtime.json', {'credentials_file': str(config_path)}),
        ('development-environment.json', {'database': names[0], 'test_database': names[1]}),
    ):
        with (private / name).open('x', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
    print('Created two fresh synthetic schemas. No user or grants created. '
          'Set STUDY_DATA_DIR to your chosen directory, then migrate with the development profile.')

if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('Development setup stopped. Preserve the current state and check the local configuration; '
              'no schema is automatically dropped and no private value is printed.', file=sys.stderr)
        raise SystemExit(1)
