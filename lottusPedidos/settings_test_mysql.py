"""Perfil de integración/concurrencia sobre un MySQL DESECHABLE.

Uso (servidor MySQL local o contenedor, usuario exclusivo de pruebas):

    LOTTUS_TEST_MYSQL_HOST=127.0.0.1 LOTTUS_TEST_MYSQL_USER=lottus_test \
    LOTTUS_TEST_MYSQL_PASSWORD=... \
    testenv/bin/python manage.py test --settings=lottusPedidos.settings_test_mysql --noinput \
        ordenes.tests.test_concurrencia

Nunca lee DB_* del .env: usa solo LOTTUS_TEST_MYSQL_* y aborta si el destino
se parece a una base real. Django crea y destruye `test_lottus` en cada corrida.
"""
import os

from django.core.exceptions import ImproperlyConfigured

from .settings_test import *  # noqa: F401,F403

if not os.environ.get('LOTTUS_TEST_MYSQL_HOST'):
    raise ImproperlyConfigured('Define LOTTUS_TEST_MYSQL_HOST/USER/PASSWORD para el perfil MySQL de pruebas.')

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': 'test_lottus',
        'USER': os.environ.get('LOTTUS_TEST_MYSQL_USER', 'lottus_test'),
        'PASSWORD': os.environ.get('LOTTUS_TEST_MYSQL_PASSWORD', ''),
        'HOST': os.environ['LOTTUS_TEST_MYSQL_HOST'],
        'PORT': os.environ.get('LOTTUS_TEST_MYSQL_PORT', '3306'),
        'OPTIONS': {'init_command': "SET sql_mode='STRICT_TRANS_TABLES'"},
        'TEST': {'NAME': 'test_lottus', 'CHARSET': 'utf8mb4'},
    }
}

from .test_guard import assert_test_database  # noqa: E402
assert_test_database(DATABASES['default'])
