import os
from pathlib import Path
from dotenv import load_dotenv
import dj_database_url
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')
ON_VERCEL = os.getenv('VERCEL') == '1'
DEBUG = os.getenv('DEBUG', 'false' if ON_VERCEL else 'true').strip().lower() == 'true'
if ON_VERCEL and DEBUG:
    raise RuntimeError('DEBUG debe ser false en Vercel')
SECRET_KEY = os.getenv('SECRET_KEY', '')
if not SECRET_KEY:
    if not DEBUG:
        raise RuntimeError('Configure SECRET_KEY en producción')
    keyfile = BASE_DIR / '.dev-secret'
    if not keyfile.exists():
        import secrets
        keyfile.write_text(secrets.token_urlsafe(64))
        keyfile.chmod(0o600)
    SECRET_KEY = keyfile.read_text()
def env_list(name, default=''):
    return [value.strip() for value in os.getenv(name, default).split(',') if value.strip()]

ALLOWED_HOSTS = env_list('ALLOWED_HOSTS', 'localhost,127.0.0.1,testserver' if DEBUG else '')
if not DEBUG and (not ALLOWED_HOSTS or '*' in ALLOWED_HOSTS):
    raise RuntimeError('Configure ALLOWED_HOSTS con dominios explícitos en producción')
INSTALLED_APPS = ['django.contrib.admin','django.contrib.auth','django.contrib.contenttypes','django.contrib.sessions','django.contrib.messages','django.contrib.staticfiles','ledger']
MIDDLEWARE = ['django.middleware.security.SecurityMiddleware','whitenoise.middleware.WhiteNoiseMiddleware','django.contrib.sessions.middleware.SessionMiddleware','django.middleware.common.CommonMiddleware','django.middleware.csrf.CsrfViewMiddleware','django.contrib.auth.middleware.AuthenticationMiddleware','django.contrib.messages.middleware.MessageMiddleware','django.middleware.clickjacking.XFrameOptionsMiddleware','ledger.middleware.PrivatePagesMiddleware']
ROOT_URLCONF = 'config.urls'
TEMPLATES = [{'BACKEND':'django.template.backends.django.DjangoTemplates','DIRS':[],'APP_DIRS':True,'OPTIONS':{'context_processors':['django.template.context_processors.request','django.contrib.auth.context_processors.auth','django.contrib.messages.context_processors.messages']}}]
database_url = os.getenv('DATABASE_URL', '').strip()
if not DEBUG and not database_url:
    raise RuntimeError('Configure DATABASE_URL con PostgreSQL persistente en producción')
DATABASES = {'default': dj_database_url.parse(
    database_url or f'sqlite:///{BASE_DIR / "db.sqlite3"}',
    conn_max_age=0 if ON_VERCEL else 60, conn_health_checks=True,
)}
if not DEBUG and DATABASES['default']['ENGINE'] != 'django.db.backends.postgresql':
    raise RuntimeError('DATABASE_URL debe usar PostgreSQL en producción; SQLite solo es local')
if DATABASES['default']['ENGINE'].endswith('sqlite3'):
    DATABASES['default']['OPTIONS'] = {'timeout':30, 'transaction_mode':'IMMEDIATE'}
AUTH_PASSWORD_VALIDATORS = [{'NAME':'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},{'NAME':'django.contrib.auth.password_validation.MinimumLengthValidator'},{'NAME':'django.contrib.auth.password_validation.CommonPasswordValidator'},{'NAME':'django.contrib.auth.password_validation.NumericPasswordValidator'}]
AUTHENTICATION_BACKENDS = ['ledger.auth.EmailBackend']
LANGUAGE_CODE = 'es-co'
TIME_ZONE = 'America/Bogota'
USE_I18N = True
USE_TZ = True
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': (
        'django.contrib.staticfiles.storage.StaticFilesStorage' if DEBUG else
        'whitenoise.storage.CompressedManifestStaticFilesStorage'
    )},
}
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
LOGIN_URL = '/ingresar/'
LOGIN_REDIRECT_URL = '/'
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_AGE = 28800
CSRF_TRUSTED_ORIGINS = env_list('CSRF_TRUSTED_ORIGINS')
if not DEBUG and not CSRF_TRUSTED_ORIGINS:
    raise RuntimeError('Configure CSRF_TRUSTED_ORIGINS con orígenes HTTPS en producción')
if not DEBUG and any(not origin.startswith('https://') for origin in CSRF_TRUSTED_ORIGINS):
    raise RuntimeError('CSRF_TRUSTED_ORIGINS debe usar HTTPS en producción')
if not DEBUG:
    SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
WSGI_APPLICATION = 'config.wsgi.application'
# Active únicamente detrás de un proxy que reemplace este encabezado.
TRUST_PROXY = os.getenv('TRUST_PROXY', 'true' if ON_VERCEL else 'false').strip().lower() == 'true'
if ON_VERCEL and not TRUST_PROXY:
    raise RuntimeError('TRUST_PROXY debe ser true detrás del proxy HTTPS de Vercel')
if TRUST_PROXY:
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO','https')
