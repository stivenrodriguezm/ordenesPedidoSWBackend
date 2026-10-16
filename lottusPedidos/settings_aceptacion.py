"""P14 local exclusivamente: base/archivos ficticios bajo un temporal dedicado.

No usar para staging ni producción. No lee .env ni envía correo/CDN.
"""
import os
from pathlib import Path
from tempfile import gettempdir
from django.core.exceptions import ImproperlyConfigured

os.environ['DJANGO_ENV_FILE'] = ''
from .settings_test import *  # noqa: E402,F401,F403

ruta = os.environ.get('LOTTUS_ACEPTACION_DIR', '')
raiz = Path(ruta).resolve() if ruta else None
temporales = {Path(gettempdir()).resolve(), Path('/tmp').resolve(), Path('/private/tmp').resolve()}
if not raiz or raiz.parent not in temporales or not raiz.name.startswith('lottus-aceptacion-') or not raiz.is_dir():
    raise ImproperlyConfigured('LOTTUS_ACEPTACION_DIR debe ser una carpeta temporal nueva lottus-aceptacion-*.')
ACEPTACION_LOCAL = True
DEBUG = True
DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': str(raiz / 'test_aceptacion.sqlite3')}}
MEDIA_ROOT = str(raiz / 'media')
CORS_ALLOWED_ORIGINS = ['http://127.0.0.1:3107', 'http://localhost:3107']
CSRF_TRUSTED_ORIGINS = CORS_ALLOWED_ORIGINS
