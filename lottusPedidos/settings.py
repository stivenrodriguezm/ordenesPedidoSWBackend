from pathlib import Path
from datetime import timedelta
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import pymysql
pymysql.version_info = (1, 4, 3, "final", 0)
pymysql.install_as_MySQLdb()

# Fix for PyMySQL returning strings for datetimes in Django
import django.utils.timezone
_original_make_aware = django.utils.timezone.make_aware
def _make_aware_safe(value, timezone=None, is_dst=None):
    if isinstance(value, str):
        if value.startswith("0000-00-00"):
            return None
        from django.utils.dateparse import parse_datetime
        try:
            parsed = parse_datetime(value)
            if parsed is not None:
                value = parsed
        except ValueError:
            return None
    if value is None:
        return None
    return _original_make_aware(value, timezone)
django.utils.timezone.make_aware = _make_aware_safe

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY', 'django-insecure-9k362@l)2sf4x1pstt7f=js1!y5u8*+ck*z77x=3x#k24j%r)-')

# DEBUG: False in production, True in local development
DEBUG = os.environ.get('DJANGO_DEBUG', 'True').lower() in ('true', '1', 't')

AUTH_USER_MODEL = 'ordenes.CustomUser'

# Allowed hosts configuration
raw_allowed_hosts = os.environ.get(
    'ALLOWED_HOSTS',
    'api.muebleslottus.com, app.muebleslottus.com, localhost, 127.0.0.1'
)
ALLOWED_HOSTS = [host.strip() for host in raw_allowed_hosts.split(',') if host.strip()]

# CORS configuration
CORS_ALLOW_ALL_ORIGINS = False

CORS_ALLOWED_ORIGINS = [
    'https://app.muebleslottus.com',   # Producción Frontend HTTPS
    'https://api.muebleslottus.com',   # Producción Backend HTTPS
    'http://app.muebleslottus.com',    # Producción Frontend HTTP
    'http://localhost:3000',           # Desarrollo local
    'http://127.0.0.1:3000',          # Desarrollo local (alt)
    'http://localhost:5173',           # Vite dev
]

CORS_ALLOW_CREDENTIALS = True

CORS_ALLOW_METHODS = [
    'GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS',
]

CORS_ALLOW_HEADERS = [
    "accept",
    "accept-encoding",
    "authorization",
    "content-type",
    "dnt",
    "origin",
    "user-agent",
    "x-csrftoken",
    "x-requested-with",
]

CSRF_TRUSTED_ORIGINS = [
    'https://app.muebleslottus.com',   # Producción Frontend
    'https://api.muebleslottus.com',   # Producción Backend
    'http://app.muebleslottus.com',
    'http://localhost:3000',           # Desarrollo local
    'http://127.0.0.1:3000',          # Desarrollo local (alt)
    'http://localhost:8000',           # Django admin local
]

# Configuración de Reverse Proxy Nginx & SSL en Producción
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True

# Cookies seguras en producción
if not DEBUG:
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_SECURE = True
else:
    CSRF_COOKIE_SECURE = False
    SESSION_COOKIE_SECURE = False

# Application definition
INSTALLED_APPS = [
    'corsheaders',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'ordenes',
    'suministros',
    'django_extensions',
    'django_filters',
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'lottusPedidos.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'lottusPedidos.wsgi.application'

# Database configuration
# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.sqlite3',
#         'NAME': BASE_DIR / 'db.sqlite3',
#     }
# }
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': os.environ.get('DB_NAME', 'u756180748_pruebasv3'),
        'USER': os.environ.get('DB_USER', 'u756180748_root'),
        'PASSWORD': os.environ.get('DB_PASSWORD', 'Lottus123'),
        'HOST': os.environ.get('DB_HOST', '195.35.61.108'),
        'PORT': os.environ.get('DB_PORT', '3306'),
        'OPTIONS': {
            'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
            'connect_timeout': 10,
            'autocommit': True,
        },
        'CONN_MAX_AGE': 0, # Close connection after each request to avoid timeout disconnects
    }
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
LANGUAGE_CODE = 'es-co'
TIME_ZONE = 'America/Bogota'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

# Media files (user uploads)
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# REST Framework configuration
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle'
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '100/day',
        'user': '1000/day'
    }
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=8),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=1),
    'AUTH_HEADER_TYPES': ('Bearer',),
}