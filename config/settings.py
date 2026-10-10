"""Local-first settings. Credentials never enter source or the delivery ZIP."""
import json
import os
import secrets
from pathlib import Path
from django.core.exceptions import ImproperlyConfigured
from .local_runtime import resolve_credentials_file

BASE_DIR = Path(os.environ.get('STUDY_RESOURCE_DIR', Path(__file__).resolve().parent.parent)).resolve()
DATA_DIR = Path(os.environ.get('STUDY_DATA_DIR', BASE_DIR)).resolve()
PRIVATE_DATA_ROOT = DATA_DIR / 'private'
DEBUG = os.environ.get('STUDY_DEBUG', '1') == '1'
SECRET_KEY = os.environ.get('STUDY_SECRET_KEY')
if not SECRET_KEY:
    secret_path = DATA_DIR / 'private' / 'django-secret.key'
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with secret_path.open('x', encoding='ascii') as secret_file:
            secret_file.write(secrets.token_urlsafe(64))
    except FileExistsError:
        pass
    SECRET_KEY = secret_path.read_text(encoding='ascii').strip()
ALLOWED_HOSTS = ['127.0.0.1', 'localhost', '[::1]', 'testserver']
INSTALLED_APPS = [
    'django.contrib.auth', 'django.contrib.contenttypes', 'django.contrib.sessions',
    'django.contrib.messages', 'django.contrib.staticfiles', 'learning',
    'attachments', 'assistant', 'scheduling', 'ai_gateway',
]
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware', 'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'attachments.upload_handlers.ImageUploadLimitMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware', 'django.middleware.clickjacking.XFrameOptionsMiddleware',
]
ROOT_URLCONF = 'config.urls'
TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [BASE_DIR / 'templates'], 'APP_DIRS': True,
    'OPTIONS': {'context_processors': [
        'django.template.context_processors.request', 'django.contrib.auth.context_processors.auth',
        'django.contrib.messages.context_processors.messages', 'learning.context_processors.navigation',
    ]},
}]
WSGI_APPLICATION = 'config.wsgi.application'

if os.environ.get('STUDY_DB_ENGINE') == 'sqlite':
    # Optional portable verification fallback; MySQL is the acceptance target.
    DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': BASE_DIR / 'local.sqlite3'}}
else:
    credential_path = resolve_credentials_file(DATA_DIR)
    if not credential_path.exists():
        raise ImproperlyConfigured('本地数据库安全配置不可读。请按 docs/01-Windows首次启动.md 配置；不得把密码写入源码或覆盖已有库。')
    credential = json.loads(credential_path.read_text(encoding='utf-8-sig'))
    # Migrations use this exact same resolved config only when explicitly enabled.
    os.environ.setdefault('STUDY_CREDENTIALS_FILE', str(credential_path))
    database_name = os.environ.get('STUDY_DATABASE', 'study_review_dev')
    if database_name != 'study_review_dev':
        raise ImproperlyConfigured('本机运行库须为 study_review_dev；该库可能已有真实学习数据，禁止覆盖。原库 study_review 另行保护。')
    if credential['host'] not in ('localhost', '127.0.0.1'):
        raise ImproperlyConfigured('本版只连接本机 MySQL。')
    DATABASES = {'default': {
        'ENGINE': 'django.db.backends.mysql', 'NAME': database_name,
        'USER': credential['application_user'], 'PASSWORD': credential['application_password'],
        'HOST': credential['host'], 'PORT': credential['port'],
        'OPTIONS': {'charset': 'utf8mb4', 'init_command': "SET sql_mode='STRICT_TRANS_TABLES,NO_ZERO_DATE,NO_ZERO_IN_DATE,ERROR_FOR_DIVISION_BY_ZERO'"},
        'TEST': {'NAME': 'test_study_review_dev', 'CHARSET': 'utf8mb4', 'COLLATION': 'utf8mb4_0900_ai_ci'},
    }}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]
LANGUAGE_CODE = 'zh-hans'
TIME_ZONE = 'Asia/Shanghai'
USE_I18N = True
USE_TZ = True
STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'dashboard'
LOGOUT_REDIRECT_URL = 'login'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'
X_FRAME_OPTIONS = 'DENY'
SECURE_CONTENT_TYPE_NOSNIFF = True
DATA_UPLOAD_MAX_MEMORY_SIZE = 512 * 1024
PRIVATE_MEDIA_ROOT = DATA_DIR / 'private' / 'media'
FILE_UPLOAD_MAX_MEMORY_SIZE = 1024 * 1024
FILE_UPLOAD_TEMP_DIR = DATA_DIR / 'private' / 'upload-temp'
FILE_UPLOAD_TEMP_DIR.mkdir(parents=True, exist_ok=True)
DATA_UPLOAD_MAX_NUMBER_FILES = 12
ATTACHMENT_MAX_INPUT_BYTES = 8 * 1024 * 1024
ATTACHMENT_MAX_PIXELS = 20_000_000
ATTACHMENT_MAX_DIMENSION = 10_000
ATTACHMENT_USER_QUOTA_BYTES = 500 * 1024 * 1024
