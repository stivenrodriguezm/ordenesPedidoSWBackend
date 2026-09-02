from pathlib import Path
from datetime import timedelta
import os

try:
    # pyrefly: ignore [missing-import]
    from dotenv import load_dotenv
    _env_file = Path(__file__).resolve().parent.parent / '.env'
    load_dotenv(dotenv_path=_env_file, override=True)
except ImportError:
    # Fallback si python-dotenv no está instalado: parseo manual de .env
    _env_file = Path(__file__).resolve().parent.parent / '.env'
    if _env_file.exists():
        with open(_env_file, 'r', encoding='utf-8') as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith('#') and '=' in _line:
                    _k, _v = _line.split('=', 1)
                    os.environ.setdefault(_k.strip(), _v.strip().strip("'\""))

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

# DEBUG: False por defecto; activar solo en desarrollo local con DJANGO_DEBUG=true
DEBUG = os.environ.get('DJANGO_DEBUG', 'False').lower() in ('true', '1', 't')

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY')
if not SECRET_KEY:
    if DEBUG:
        # Solo para desarrollo local; en producción DJANGO_SECRET_KEY es obligatoria
        SECRET_KEY = 'django-insecure-dev-only-local-key'
    else:
        from django.core.exceptions import ImproperlyConfigured
        raise ImproperlyConfigured(
            'La variable de entorno DJANGO_SECRET_KEY es obligatoria cuando DEBUG=False.'
        )

AUTH_USER_MODEL = 'ordenes.CustomUser'

# Allowed hosts: configurar vía ALLOWED_HOSTS="api.ejemplo.com,otro.ejemplo.com"
ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get(
        'ALLOWED_HOSTS', 'localhost,127.0.0.1,api.muebleslottus.com'
    ).split(',')
    if h.strip()
]

# CORS configuration
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOW_CREDENTIALS = True

CORS_ALLOWED_ORIGINS = [
    'https://muebleslottus.com',       # Sitio público (paginaweb) — dominio raíz
    'https://www.muebleslottus.com',   # Sitio público (paginaweb) — con www
    'https://app.muebleslottus.com',   # Producción Frontend HTTPS
    'https://api.muebleslottus.com',   # Producción Backend HTTPS
    'https://stivenrodriguezm.github.io',   # Sitio público (paginaweb) en GitHub Pages
]

CORS_ALLOWED_ORIGIN_REGEXES = [
    r"^https://.*\.muebleslottus\.com$",
]

if DEBUG:
    CORS_ALLOWED_ORIGINS += [
        'http://localhost:3000',           # Desarrollo local
        'http://127.0.0.1:3000',          # Desarrollo local (alt)
        'http://localhost:5173',           # Vite dev
        'http://127.0.0.1:5173',          # Vite dev (alt)
        'http://localhost:8000',           # Django admin local
        'http://127.0.0.1:8000',          # Django admin local (alt)
    ]
    CORS_ALLOWED_ORIGIN_REGEXES += [
        r"^http://localhost:[0-9]+$",
        r"^http://127\.0\.0\.1:[0-9]+$",
    ]

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
    'https://muebleslottus.com',       # Sitio público (paginaweb) — dominio raíz
    'https://www.muebleslottus.com',   # Sitio público (paginaweb) — con www
    'https://app.muebleslottus.com',   # Producción Frontend
    'https://api.muebleslottus.com',   # Producción Backend
]
if DEBUG:
    CSRF_TRUSTED_ORIGINS += [
        'http://localhost:3000',           # Desarrollo local
        'http://127.0.0.1:3000',          # Desarrollo local (alt)
        'http://localhost:5173',           # Vite dev
        'http://127.0.0.1:5173',          # Vite dev (alt)
        'http://localhost:8000',           # Django admin local
        'http://127.0.0.1:8000',          # Django admin local (alt)
    ]

# Configuración de Reverse Proxy Nginx & SSL en Producción
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True

# Cookies y cabeceras seguras en producción
if not DEBUG:
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    X_FRAME_OPTIONS = 'DENY'
    # Redirección forzada a HTTPS a nivel de Django, como respaldo por si el
    # proxy/nginx llegara a no redirigir HTTP->HTTPS por sí mismo.
    SECURE_SSL_REDIRECT = True
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
    'paginaweb',
    'listaprecios',
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
# In local dev (no DB_HOST env var set) → SQLite to avoid exhausting remote hosting connection limits
# In production → MySQL via environment variables
_USE_REMOTE_DB = bool(os.environ.get('DB_HOST'))

if _USE_REMOTE_DB:
    # En producción (DEBUG=False), se fuerza estrictamente la base de datos oficial u756180748_lottus
    if not DEBUG:
        active_db_name = 'u756180748_lottus'
        active_db_user = 'u756180748_lottus'
    else:
        active_db_name = os.environ.get('DB_NAME', 'u756180748_pruebasv3')
        active_db_user = os.environ.get('DB_USER', 'u756180748_root')

    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': active_db_name,
            'USER': active_db_user,
            'PASSWORD': os.environ['DB_PASSWORD'],
            'HOST': os.environ['DB_HOST'],
            'PORT': os.environ.get('DB_PORT', '3306'),
            'OPTIONS': {
                'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
                'connect_timeout': 10,
                'autocommit': True,
            },
            'CONN_MAX_AGE': 60,  # Reutilizar conexiones hasta 60s para reducir conexiones/hora al hosting
            'CONN_HEALTH_CHECKS': True,
        }
    }
else:
    # Local development: use SQLite (no remote connections, no connection limits)
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db_local.sqlite3',
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

# URL pública del sitio (webLottus) — usada para construir enlaces
# absolutos (perfil de asesor, QR) fuera del dominio del API.
PUBLIC_SITE_URL = os.environ.get('PUBLIC_SITE_URL', 'http://localhost:4000').rstrip('/')

# Sirv (CDN de imágenes) — usado por paginaweb.sirv para subir imágenes de
# Gestión Web (productos, fotos de asesores) en vez de guardarlas en disco.
SIRV_CLIENT_ID = os.environ.get('SIRV_CLIENT_ID', '')
SIRV_CLIENT_SECRET = os.environ.get('SIRV_CLIENT_SECRET', '')
SIRV_PUBLIC_DOMAIN = os.environ.get('SIRV_PUBLIC_DOMAIN', 'lottus.sirv.com')

# Cloudinary (CDN de imágenes/video) — usado por paginaweb.cloudinary_client
# para subir imágenes y videos de Gestión Web. Cloudinary optimiza formato y
# calidad automáticamente en la entrega (f_auto,q_auto), a diferencia de Sirv
# que sirve el archivo tal cual se subió.
CLOUDINARY_CLOUD_NAME = os.environ.get('CLOUDINARY_CLOUD_NAME', '')
CLOUDINARY_API_KEY = os.environ.get('CLOUDINARY_API_KEY', '')
CLOUDINARY_API_SECRET = os.environ.get('CLOUDINARY_API_SECRET', '')

# Correo (PQRS y notificaciones transaccionales). Sin EMAIL_HOST_USER /
# EMAIL_HOST_PASSWORD configurados se usa el backend de consola (los correos
# se imprimen en el log del servidor) para no romper el flujo en desarrollo
# local sin credenciales SMTP reales.
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', '')
if EMAIL_HOST_USER and EMAIL_HOST_PASSWORD:
    EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
else:
    EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'
EMAIL_HOST = os.environ.get('EMAIL_HOST', 'smtp.gmail.com')
EMAIL_PORT = int(os.environ.get('EMAIL_PORT', '587'))
EMAIL_USE_TLS = os.environ.get('EMAIL_USE_TLS', 'True').lower() in ('true', '1', 't')
EMAIL_USE_SSL = os.environ.get('EMAIL_USE_SSL', 'False').lower() in ('true', '1', 't')
DEFAULT_FROM_EMAIL = os.environ.get('DEFAULT_FROM_EMAIL') or EMAIL_HOST_USER or 'no-reply@muebleslottus.com'

# Correo interno que recibe la notificación de cada PQRS nuevo (equipo LOTTUS)
PQRS_NOTIFY_EMAIL = os.environ.get('PQRS_NOTIFY_EMAIL', 'muebleslottus@gmail.com')

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
    'EXCEPTION_HANDLER': 'lottusPedidos.settings.custom_exception_handler',
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle'
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '1000/day',
        'user': '10000/day',
        'login': '10/min',
        'pqrs_create': '5/hour',
        'pqrs_track': '20/hour',
    }
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=8),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=1),
    'AUTH_HEADER_TYPES': ('Bearer',),
}

def custom_exception_handler(exc, context):
    import logging
    from rest_framework.views import exception_handler
    from rest_framework.response import Response
    from rest_framework import status

    response = exception_handler(exc, context)

    if response is None:
        logging.getLogger('django.request').exception(
            'Error interno no controlado en %s: %s',
            context.get('view').__class__.__name__ if context.get('view') else 'vista desconocida',
            exc,
        )
        return Response(
            {"detail": "Error interno del servidor."},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    return response