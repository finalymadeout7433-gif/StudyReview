"""Secret-free, in-memory fast checks; actual MySQL acceptance uses root's isolated settings."""
SECRET_KEY = 'synthetic-test-signing-key-not-for-production'
DEBUG = False
ALLOWED_HOSTS = ['testserver', '127.0.0.1', 'localhost']
INSTALLED_APPS = [
    'django.contrib.auth', 'django.contrib.contenttypes', 'django.contrib.sessions',
    'django.contrib.messages', 'learning', 'attachments.apps.AttachmentsConfig',
]
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}}
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware', 'django.contrib.sessions.middleware.SessionMiddleware',
    'attachments.upload_handlers.ImageUploadLimitMiddleware', 'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware', 'django.contrib.messages.middleware.MessageMiddleware',
]
ROOT_URLCONF = 'attachments.tests.urls'
TIME_ZONE = 'Asia/Shanghai'
USE_TZ = True
LOGIN_URL = 'login'
DATA_UPLOAD_MAX_MEMORY_SIZE = 512 * 1024
