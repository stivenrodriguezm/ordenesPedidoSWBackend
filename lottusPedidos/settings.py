from pathlib import Path
from datetime import timedelta
import os
import sys

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# DJANGO_ENV_FILE permite elegir otro archivo de entorno (staging, CI) o
# desactivarlo con DJANGO_ENV_FILE="" — por defecto se usa .env junto a manage.py.
# El servidor de desarrollo se mantiene aislado de cualquier `.env` que contenga
# credenciales de operación. La única excepción local explícita es el marcador
# no versionado `.local-test-db`, que selecciona la base MySQL de pruebas
# `u756180748_pruebasv3` usando las credenciales ya configuradas en `.env`.
_local_runserver = 'runserver' in sys.argv and os.environ.get('LOTTUS_ALLOW_REMOTE_RUNSERVER') != '1'
_local_test_db = ((_local_runserver and (_PROJECT_ROOT / '.local-test-db').exists())
                  or os.environ.get('LOTTUS_LOCAL_TEST_DB') == '1')
LOCAL_TEST_DB = _local_test_db
_env_file_setting = os.environ.get('DJANGO_ENV_FILE')
if _local_test_db:
    _env_file_setting = None
elif _local_runserver and _env_file_setting is None:
    _env_file_setting = ''
_env_file = (
    _PROJECT_ROOT / '.env'
    if _env_file_setting is None else (Path(_env_file_setting) if _env_file_setting else None)
)

try:
    # pyrefly: ignore [missing-import]
    from dotenv import load_dotenv
    # override=False: una variable ya definida en el proceso (systemd, CI,
    # `DB_NAME=... manage.py ...`) prevalece sobre .env. Con override=True el
    # .env pisaba en silencio la configuración explícita del proceso.
    if _env_file:
        load_dotenv(dotenv_path=_env_file, override=False)
except ImportError:
    # Fallback si python-dotenv no está instalado: parseo manual de .env
    if _env_file and _env_file.exists():
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
BASE_DIR = _PROJECT_ROOT
ASISTENTE_WEB_ROOT = Path(os.environ.get('ASISTENTE_WEB_ROOT', str(BASE_DIR.parent / 'webLottus')))
ASISTENTE_LANDING_ROOT = Path(os.environ.get('ASISTENTE_LANDING_ROOT', str(BASE_DIR.parent / 'landingLottus')))
ASISTENTE_GESTION_WEB_ROOT = Path(os.environ.get('ASISTENTE_GESTION_WEB_ROOT', str(BASE_DIR.parent / 'ordenesPedidoSW')))
ASISTENTE_BACKEND_WEB_ROOT = Path(os.environ.get('ASISTENTE_BACKEND_WEB_ROOT', str(BASE_DIR / 'paginaweb')))
ACADEMIA_CHROME_USUARIO_ID = int(os.environ.get('ACADEMIA_CHROME_USUARIO_ID', '0'))
ACADEMIA_ROOT = BASE_DIR / 'private_media' / 'academia'
ACADEMIA_PYTHON = os.environ.get('ACADEMIA_PYTHON', str(BASE_DIR / '.cache' / 'notebook-runtime' / 'bin' / 'python'))

# DEBUG: False por defecto; activar solo en desarrollo local con DJANGO_DEBUG=true
DEBUG = True if _local_test_db else os.environ.get('DJANGO_DEBUG', 'True' if _local_runserver else 'False').lower() in ('true', '1', 't')

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

# Asistente gerencial (Chat) con Gemini. La clave vive solo en el entorno del servidor
# (.env / systemd); nunca en el frontend ni en el repositorio. GEMINI_MODELOS: orden de
# preferencia; si uno está saturado (503/429) se usa el siguiente.
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')
GEMINI_MODELOS = [m.strip() for m in os.environ.get('GEMINI_MODELOS', 'gemini-3.7-flash,gemini-3.6-flash,gemini-3.5-flash-lite,gemini-3.8-flash,gemini-3.5-flash').split(',') if m.strip()]
# La respuesta se genera en un hilo aparte para no chocar con el timeout de gunicorn (30 s).
ASISTENTE_EN_SEGUNDO_PLANO = True

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
    "idempotency-key",  # reintentos seguros de altas financieras (P03-06)
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
    # El runserver local de ordenes inicia también el motor IA.
    'ordenes',
    'django.contrib.staticfiles',
    'rest_framework',
    'rest_framework_simplejwt.token_blacklist',
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
# Sin DB_HOST → SQLite local (no consume conexiones del hosting remoto).
# Con DB_HOST → MySQL con DB_NAME, DB_USER y DB_PASSWORD SIEMPRE explícitos.
# DEBUG controla la depuración, nunca qué base se usa: antes DEBUG=False
# forzaba el nombre/usuario de producción, así que un staging con depuración
# apagada apuntaba a la base real (auditoría 2026-10-02, H16).
_USE_REMOTE_DB = bool(os.environ.get('DB_HOST')) and (not _local_runserver or _local_test_db)

if _USE_REMOTE_DB:
    from django.core.exceptions import ImproperlyConfigured
    _faltantes = [k for k in ('DB_NAME', 'DB_USER', 'DB_PASSWORD') if not os.environ.get(k)]
    if _faltantes:
        # Solo se nombran las variables, nunca sus valores.
        raise ImproperlyConfigured(
            'DB_HOST está definido pero faltan variables de conexión: ' + ', '.join(_faltantes)
            + '. Defínelas explícitamente para el entorno (no hay valores por defecto).'
        )
    # En el modo local de pruebas el nombre es fijo para impedir que un `.env`
    # con valores de producción sea usado accidentalmente.
    active_db_name = 'u756180748_pruebasv3' if _local_test_db else os.environ['DB_NAME']
    active_db_user = os.environ['DB_USER']

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
        'lottusPedidos.throttling.ApiUserRateThrottle'
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '1000/day',
        'user': '10000/day',
        'session': '60/min',
        'office_live': '180/min',
        'office_presence': '10/min',
        'login': '10/min',
        'pqrs_create': '5/hour',
        'pqrs_track': '20/hour',
    }
}

# Contadores de throttling (login 10/min, PQRS…) compartidos entre los workers
# de gunicorn: con la caché en memoria por proceso cada worker contaba aparte
# (H28). Caché en disco local, sin servicio adicional que operar.
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.filebased.FileBasedCache',
        'LOCATION': os.environ.get('DJANGO_CACHE_DIR', str(BASE_DIR / '.cache' / 'django')),
    }
}

# IP real del cliente detrás de nginx: DRF toma la entrada de X-Forwarded-For que
# agrega el último proxy confiable. Poner DJANGO_NUM_PROXIES=1 SOLO tras verificar
# que nginx usa `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;`.
# Con 0 (por defecto) se usa REMOTE_ADDR: detrás del proxy todos comparten límite.
REST_FRAMEWORK['NUM_PROXIES'] = int(os.environ.get('DJANGO_NUM_PROXIES', '0')) or None

SIMPLE_JWT = {
    # Duraciones sin cambio hasta resolver D07 (acortarlas desconecta usuarios).
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=8),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=1),
    # Cada renovación entrega un refresh nuevo y revoca el anterior; el cierre
    # de sesión revoca el refresh en el servidor (P02-05, H28).
    'ROTATE_REFRESH_TOKENS': True,
    'BLACKLIST_AFTER_ROTATION': True,
    'AUTH_HEADER_TYPES': ('Bearer',),
}

def custom_exception_handler(exc, context):
    import logging
    from rest_framework.views import exception_handler
    from rest_framework.response import Response
    from rest_framework import status

    response = exception_handler(exc, context)

    from django.db.models.deletion import ProtectedError, RestrictedError
    if response is None and isinstance(exc, (ProtectedError, RestrictedError)):
        # Relación histórica protegida (H12): se informa en vez de un 500.
        return Response(
            {"error": "No se puede eliminar: el registro tiene documentos o movimientos asociados. Desactívalo o anúlalo."},
            status=status.HTTP_409_CONFLICT,
        )

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
