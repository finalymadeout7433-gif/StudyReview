"""Only the named private development copy may use these isolated schemas."""
from .settings import *

development_path = DATA_DIR / 'private' / 'development-environment.json'
development = json.loads(development_path.read_text(encoding='utf-8'))
if not development['database'].startswith('study_review_v2_dev_') or not development['test_database'].startswith('test_study_review_v2_'):
    raise ImproperlyConfigured('V2 development requires the explicitly created isolated database names.')
DATABASES['default']['NAME'] = development['database']
V2_DEVELOPMENT_DATABASE = development['database']
DATABASES['default']['USER'] = credential['administrator_user']
DATABASES['default']['PASSWORD'] = credential['administrator_password']
DATABASES['default']['TEST']['NAME'] = development['test_database']
AUTHORIZED_MIGRATION_SCHEMAS = {
    development['database'], development['test_database'],
    development['test_database'] + '_att',
    development['test_database'] + '_att_retry',
    development['test_database'] + '_chat',
    development['test_database'] + '_fsrs',
    development['test_database'] + '_att_v2',
    development['test_database'] + '_fsrs_v2',
    development['test_database'] + '_chat_v2',
}
# This signing key is created only in the private development copy by base settings.
# No source users, passwords, sessions or learning rows are imported.
