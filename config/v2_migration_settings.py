"""Explicit, temporary DDL profile; never accepted by the desktop launcher."""
import re
from .settings import *

if os.environ.get('STUDY_ALLOW_SCHEMA_ADMIN') != '1':
    raise ImproperlyConfigured('The migration-only profile requires explicit local schema authorization.')
plan_path = DATA_DIR / 'private' / 'schema-plan.json'
plan = json.loads(plan_path.read_text(encoding='utf-8-sig'))
database = plan.get('database', '')
if (plan.get('purpose') != 'study-review-v2-upgrade' or not isinstance(database, str)
        or not re.fullmatch(r'study_review_dev|study_review_restorecheck_[A-Za-z0-9_]+', database)):
    raise ImproperlyConfigured('The private migration plan must name one authorized local application or restore schema.')
DATABASES['default']['NAME'] = database
DATABASES['default']['USER'] = credential['administrator_user']
DATABASES['default']['PASSWORD'] = credential['administrator_password']
AUTHORIZED_MIGRATION_SCHEMAS = {database}
DEBUG = False
