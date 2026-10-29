"""Aplicar directo en el Mac (DESARROLLADOR_APLICAR_BACKEND / _FRONTEND), sin vista previa: el
usuario prefiere ver el cambio en su plataforma y darle «Deshacer» si no le gusta (2026-10-29).

- foto(): el agente parte del código local tal como está, incluidos los cambios sin commit y los
  archivos nuevos (índice temporal; no toca el índice ni los archivos del usuario). Queda en
  refs/desarrollador/base de cada repositorio.
- aplicar(): el parche ya verificado se aplica al código local con `git apply`: todo o nada y en los
  dos repositorios o en ninguno. El backend (runserver) y el frontend (vite) lo recargan solos.
  Si trae migraciones: respaldo de pruebasv3 y luego migrar_pruebas.py (destinos explícitos).
- deshacer(): migraciones hacia atrás (con respaldo antes) y el parche al revés. Si alguna tarea
  posterior cambió las mismas líneas, no deshace nada y lo dice.
"""
import gzip
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

from .espacio import REPOS, ErrorEspacio, ejecutar

BASE = 'refs/desarrollador/base'
MIGRAR = Path(__file__).with_name('migrar_pruebas.py')
DB_PRUEBAS = 'u756180748_pruebasv3'


class AplicarLocal:
    def __init__(self, espacio, destinos, carpeta, python, respaldos):
        self.espacio, self.destinos = espacio, {n: Path(r) for n, r in destinos.items()}
        self.carpeta, self.python, self.respaldos = Path(carpeta), python, Path(respaldos)

    # --- Punto de partida -----------------------------------------------------------
    def foto(self):
        """Commit con el estado actual del código local de cada repositorio (sin tocarlo)."""
        for nombre, ruta in self.destinos.items():
            with tempfile.TemporaryDirectory() as tmp:
                env = {'GIT_INDEX_FILE': str(Path(tmp) / 'index')}
                pasos = [['git', 'read-tree', 'HEAD'], ['git', 'add', '-A'], ['git', 'write-tree']]
                for cmd in pasos:
                    codigo, salida = ejecutar(cmd, ruta, timeout=300, env=env)
                    if codigo:
                        raise ErrorEspacio(f'{nombre}: no se pudo leer tu código local ({salida[-300:]})')
            codigo, sha = ejecutar(['git', '-c', 'user.name=Desarrollador IA Lottus', '-c', 'user.email=desarrollador@muebleslottus.com',
                                    'commit-tree', salida.strip(), '-p', 'HEAD', '-m', 'Desarrollador: punto de partida'], ruta, timeout=60)
            if codigo or ejecutar(['git', 'update-ref', BASE, sha.strip()], ruta, timeout=60)[0]:
                raise ErrorEspacio(f'{nombre}: no se pudo guardar el punto de partida.')
        return dict(self.destinos)

    # --- Aplicar y deshacer ------------------------------------------------------------
    def aplicar(self, pk, ev):
        self.carpeta.mkdir(parents=True, exist_ok=True)
        parches = {}
        for nombre in REPOS:
            _, parche = ejecutar(['git', 'diff', '--binary', self.espacio.base, 'HEAD'], self.espacio.repo(nombre), timeout=120)
            if parche.strip():
                archivo = self.carpeta / f't{pk}-{nombre}.patch'
                archivo.write_text(parche, encoding='utf-8')
                parches[nombre] = archivo
        if not parches:
            raise ErrorEspacio('no hay cambios para aplicar')
        for nombre, archivo in parches.items():
            codigo, salida = ejecutar(['git', 'apply', '--check', str(archivo)], self.destinos[nombre], timeout=120)
            if codigo:
                raise ErrorEspacio(f'tu código local cambió en los mismos archivos mientras el agente trabajaba ({nombre}): {salida[-400:]}')
        previas = self._previas() if 'backend' in parches else {}
        respaldo = self._respaldar(ev) if previas else ''
        for nombre, archivo in parches.items():
            codigo, salida = ejecutar(['git', 'apply', str(archivo)], self.destinos[nombre], timeout=120)
            if codigo:  # no debería pasar tras --check; se devuelve lo ya aplicado
                self._revertir({n: a for n, a in parches.items() if n != nombre})
                raise ErrorEspacio(f'no se pudo aplicar en {nombre}: {salida[-400:]}')
        if previas:
            codigo, salida = self._manage(['shell'], entrada=MIGRAR.read_text(encoding='utf-8'))
            if codigo:
                self._revertir(parches)
                raise ErrorEspacio(f'la migración falló; se devolvió el código (respaldo {respaldo}): {salida[-800:]}')
            ev('Base de datos de pruebas migrada.')
        ev('Aplicado en tu plataforma: ' + ', '.join(sorted(parches)) + '.')
        return {'repositorios': sorted(parches), 'migraciones_previas': previas, 'respaldo': respaldo}

    def deshacer(self, pk, info, ev):
        parches = {n: self.carpeta / f't{pk}-{n}.patch' for n in info.get('repositorios') or []}
        if not parches or not all(a.exists() for a in parches.values()):
            raise ErrorEspacio('no se encontró el cambio aplicado de esta tarea')
        for nombre, archivo in parches.items():
            codigo, _ = ejecutar(['git', 'apply', '-R', '--check', str(archivo)], self.destinos[nombre], timeout=120)
            if codigo:
                raise ErrorEspacio(f'después se cambiaron las mismas líneas ({nombre}); deshaz primero las tareas más recientes')
        previas = info.get('migraciones_previas') or {}
        if previas:
            self._respaldar(ev)
            for app, nombre in sorted(previas.items()):
                codigo, salida = self._manage(['migrate', app, nombre, '--noinput'])
                if codigo:
                    raise ErrorEspacio(f'no se pudo devolver la base de datos ({app}): {salida[-600:]}')
            ev('Base de datos de pruebas devuelta.')
        self._revertir(parches)
        ev('Cambio deshecho en tu plataforma.')

    def _revertir(self, parches):
        for nombre, archivo in parches.items():
            codigo, salida = ejecutar(['git', 'apply', '-R', str(archivo)], self.destinos[nombre], timeout=120)
            if codigo:
                raise ErrorEspacio(f'no se pudo revertir {nombre}: {salida[-400:]}')

    # --- Base de datos ------------------------------------------------------------------
    def _previas(self):
        """Por app con migraciones nuevas: la migración de la que parte (destino para deshacer)."""
        _, nuevas = ejecutar(['git', 'diff', '--name-only', '--diff-filter=A', self.espacio.base, 'HEAD', '--', '*/migrations/0*.py'],
                             self.espacio.repo('backend'), timeout=60)
        rutas = sorted(nuevas.split())
        propias = {(r.split('/')[-3], Path(r).stem) for r in rutas}
        previas = {}
        for ruta in rutas:
            app = ruta.split('/')[-3]
            texto = (self.espacio.repo('backend') / ruta).read_text(encoding='utf-8')
            for dep in re.findall(rf"\(\s*['\"]{app}['\"]\s*,\s*['\"](\w+)['\"]\s*\)", texto):
                if (app, dep) not in propias:
                    previas.setdefault(app, dep)
            previas.setdefault(app, 'zero')  # primera migración de una app nueva
        return previas

    def _manage(self, args, entrada=None):
        try:
            r = subprocess.run([self.python, 'manage.py', *args], cwd=self.destinos['backend'], input=entrada, capture_output=True,
                               text=True, timeout=1800)
        except subprocess.TimeoutExpired:
            return 124, 'tiempo agotado'
        return r.returncode, (r.stdout or '') + (r.stderr or '')

    def _respaldar(self, ev):
        """Respaldo completo de pruebasv3 antes de migrar (credenciales del .env local, nunca en pantalla)."""
        from dotenv import dotenv_values
        e = dotenv_values(self.destinos['backend'] / '.env')
        if e.get('DB_NAME') != DB_PRUEBAS:
            raise ErrorEspacio('el backend local no apunta a la base de pruebas; no se migra')
        self.respaldos.mkdir(parents=True, exist_ok=True)
        destino = self.respaldos / f'pruebasv3_{time.strftime("%Y%m%d_%H%M%S")}.sql.gz'
        q = lambda v: '"' + v.replace('\\', '\\\\').replace('"', '\\"') + '"'  # noqa: E731
        fd, cnf = tempfile.mkstemp()
        try:
            with os.fdopen(fd, 'w') as f:
                f.write(f"[client]\nhost={e['DB_HOST']}\nport={e.get('DB_PORT') or 3306}\nuser={q(e['DB_USER'])}\npassword={q(e['DB_PASSWORD'])}\n")
            extra = ['--column-statistics=0'] if 'column-statistics' in ejecutar(['mysqldump', '--help'], self.respaldos, timeout=60)[1] else []
            with gzip.open(destino, 'wb') as salida:
                r = subprocess.run(['mysqldump', f'--defaults-extra-file={cnf}', '--single-transaction', '--quick', '--no-tablespaces', *extra,
                                    DB_PRUEBAS], stdout=salida, stderr=subprocess.PIPE, timeout=1800)
        finally:
            os.unlink(cnf)
        final = b''
        with gzip.open(destino, 'rb') as f:
            while bloque := f.read(1 << 20):
                final = (final + bloque)[-400:]
        completo = b'Dump completed' in final
        if r.returncode or not completo:
            raise ErrorEspacio('el respaldo de la base de pruebas quedó incompleto; no se migra')
        for viejo in sorted(self.respaldos.glob('pruebasv3_*.sql.gz'))[:-15]:
            viejo.unlink()
        ev(f'Respaldo de la base de pruebas: {destino.name}')
        return destino.name
