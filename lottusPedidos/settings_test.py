"""Settings para `manage.py test`: SQLite en memoria, sin salidas externas.

Rápido y desechable; NO valida bloqueos de MySQL (para eso existe
settings_test_mysql). Hereda de settings, pero anula base de datos, correo,
CDNs y throttles para que ninguna prueba toque servicios reales aunque el
.env local tenga credenciales remotas.
"""
import os

# Clave solo para pruebas (CI no tiene .env). Nunca se usa fuera de este perfil.
os.environ.setdefault('DJANGO_SECRET_KEY', 'test-only-not-a-secret-key-with-at-least-32-bytes')

from .settings import *  # noqa: E402,F401,F403

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

# Ninguna salida externa durante pruebas.
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
EMAIL_HOST_USER = ''
EMAIL_HOST_PASSWORD = ''
SIRV_CLIENT_ID = ''
SIRV_CLIENT_SECRET = ''
CLOUDINARY_CLOUD_NAME = ''
CLOUDINARY_API_KEY = ''
CLOUDINARY_API_SECRET = ''

SECURE_SSL_REDIRECT = False
ALLOWED_HOSTS = ['testserver', 'localhost', '127.0.0.1']

# Caché local por proceso: los throttles de login no se comparten con nada real.
CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}

PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']  # solo velocidad en pruebas

from .test_guard import assert_test_database  # noqa: E402
assert_test_database(DATABASES['default'])

# Aislar también los archivos de pruebas de los adjuntos operativos.
import tempfile
_archivos_prueba = tempfile.TemporaryDirectory(prefix='lottus-test-media-')
MEDIA_ROOT = os.path.join(_archivos_prueba.name, 'media')

# Asistente: sin clave real y sin hilos en pruebas (Gemini se simula).
GEMINI_API_KEY = ''
ASISTENTE_EN_SEGUNDO_PLANO = False
ACADEMIA_ROOT = os.path.join(_archivos_prueba.name, 'academia')
ACADEMIA_CHROME_USUARIO_ID = 0
