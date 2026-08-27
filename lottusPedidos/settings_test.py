"""Settings para correr `manage.py test` localmente: el usuario MySQL remoto
de .env no tiene privilegio CREATE DATABASE, así que las pruebas usan SQLite
en memoria en vez de intentar crear una base de datos de prueba remota."""
from .settings import *  # noqa: F401,F403

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}
