"""Subprocess HTTP server used only by the synthetic focus browser test."""
from .v2_integrated_test_settings import *

requested = os.environ.get('STUDY_FOCUS_BROWSER_DB')
if requested != DATABASES['default']['TEST']['NAME'] or not requested.startswith('test_study_review_v2_'):
    raise ImproperlyConfigured('Focus browser server requires the exact synthetic test database.')
DATABASES['default']['NAME'] = requested
DEBUG = True
