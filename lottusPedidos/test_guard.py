"""Comprobación que aborta si un perfil de pruebas apunta a una base que no es
de pruebas. Se ejecuta al importar settings_test / settings_test_mysql, antes
de que Django abra ninguna conexión."""
from django.core.exceptions import ImproperlyConfigured

# Prefijos de las bases reales del hosting: nunca deben usarse en pruebas.
_PREFIJOS_PROHIBIDOS = ('u756180748_',)


def assert_test_database(db):
    engine = db.get('ENGINE', '')
    name = str(db.get('NAME', ''))
    if engine == 'django.db.backends.sqlite3':
        if name != ':memory:':
            raise ImproperlyConfigured('El perfil de pruebas SQLite debe usar una base en memoria.')
        return
    if engine != 'django.db.backends.mysql':
        raise ImproperlyConfigured(f'Motor no admitido para pruebas: {engine}')

    test_name = str((db.get('TEST') or {}).get('NAME') or '')
    user = str(db.get('USER', ''))
    for valor, etiqueta in ((name, 'NAME'), (test_name, 'TEST.NAME'), (user, 'USER')):
        if any(valor.startswith(p) for p in _PREFIJOS_PROHIBIDOS):
            raise ImproperlyConfigured(f'{etiqueta} de pruebas coincide con una cuenta/base del hosting real.')
    if not test_name.startswith('test_'):
        raise ImproperlyConfigured('La base MySQL de pruebas debe llamarse test_* (TEST.NAME).')
