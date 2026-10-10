from .v2_development_settings import *
DATABASES['default']['TEST']['NAME'] = development['test_database'] + '_fsrs_v2'
