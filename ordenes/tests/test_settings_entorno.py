"""Selección de base por entorno (H16 · P01-02). Cada caso importa settings en
un proceso nuevo con variables explícitas y sin .env; nunca abre conexiones."""
import json
import os
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase

BASE = Path(__file__).resolve().parents[2]
SCRIPT = (
    "import json, lottusPedidos.settings as s;"
    "d = s.DATABASES['default'];"
    "print(json.dumps({'engine': d['ENGINE'], 'name': str(d['NAME']), 'user': d.get('USER'), 'host': d.get('HOST'), 'debug': s.DEBUG}))"
)


def cargar(**env):
    entorno = {k: v for k, v in os.environ.items() if not k.startswith(('DB_', 'DJANGO_'))}
    entorno.update({'DJANGO_ENV_FILE': '', 'DJANGO_SECRET_KEY': 'solo-prueba-clave-de-al-menos-32-bytes'})
    entorno.update(env)
    r = subprocess.run([sys.executable, '-c', SCRIPT], cwd=BASE, env=entorno, capture_output=True, text=True)
    return r.returncode, (json.loads(r.stdout) if r.returncode == 0 else r.stderr)


class SeleccionBaseTests(SimpleTestCase):
    def test_debug_no_cambia_destino(self):
        for debug in ('True', 'False'):
            code, cfg = cargar(DJANGO_DEBUG=debug, DB_HOST='staging.invalid', DB_NAME='lottus_staging',
                               DB_USER='staging_app', DB_PASSWORD='x')
            self.assertEqual(code, 0, cfg)
            self.assertEqual((cfg['name'], cfg['user'], cfg['host']), ('lottus_staging', 'staging_app', 'staging.invalid'))

    def test_faltan_variables_falla_sin_revelar_valores(self):
        code, err = cargar(DJANGO_DEBUG='False', DB_HOST='staging.invalid', DB_PASSWORD='valor-que-no-debe-aparecer')
        self.assertNotEqual(code, 0)
        self.assertIn('DB_NAME', err)
        self.assertNotIn('valor-que-no-debe-aparecer', err)

    def test_sin_db_host_usa_sqlite_local(self):
        code, cfg = cargar(DJANGO_DEBUG='True')
        self.assertEqual(code, 0, cfg)
        self.assertEqual(cfg['engine'], 'django.db.backends.sqlite3')

    def test_variables_del_proceso_prevalecen_sobre_archivo(self):
        import tempfile
        with tempfile.NamedTemporaryFile('w', suffix='.env', delete=False) as f:
            f.write('DB_HOST=archivo.invalid\nDB_NAME=desde_archivo\nDB_USER=u\nDB_PASSWORD=p\n')
        try:
            code, cfg = cargar(DJANGO_ENV_FILE=f.name, DB_NAME='desde_proceso')
        finally:
            os.unlink(f.name)
        self.assertEqual(code, 0, cfg)
        self.assertEqual(cfg['name'], 'desde_proceso')
        self.assertEqual(cfg['host'], 'archivo.invalid')
