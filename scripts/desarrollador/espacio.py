"""Espacio de trabajo del Desarrollador: copias de los dos repositorios en una rama propia por
tarea y las herramientas de archivos que usa el modelo, siempre dentro de ese espacio.

Nada aquí toca producción: el espacio es una copia aparte (otro usuario del sistema) y lo
único que sale de él es un commit en la rama `desarrollador/t<id>`.
"""
import os
import re
import subprocess
from pathlib import Path

REPOS = ('backend', 'frontend')
# Nunca se leen ni se envían al modelo.
CARPETAS_OCULTAS = {'.git', 'node_modules', 'dist', '.venv', 'venv', 'testenv', 'media', 'private_media', '__pycache__',
                    '.cache', 'staticfiles', 'static_collected', '.build-check', 'coverage'}
PATRON_SECRETO = re.compile(r'(^\.env)|(\.(pem|key|sqlite3|sql|gz|zip|log|p12|crt)$)|(^id_(rsa|ed25519))', re.I)
# Se leen pero no se escriben: configuración, dependencias, el propio agente, despliegue y migraciones existentes.
SOLO_LECTURA = [
    re.compile(r'^backend/lottusPedidos/settings[^/]*\.py$'), re.compile(r'^backend/requirements[^/]*\.txt$'),
    re.compile(r'^backend/scripts/'), re.compile(r'^backend/deploy/'), re.compile(r'^\w+/\.github/'),
    re.compile(r'^backend/[a-z_]+/migrations/(?!__init__)'), re.compile(r'^frontend/package(-lock)?\.json$'),
    re.compile(r'^frontend/(vite|vitest)\.config\.\w+$'), re.compile(r'^frontend/\.env'),
    re.compile(r'^backend/ordenes/desarrollador_views\.py$'),
]
MAX_LECTURA = 60000
MAX_ESCRITURA = 120000
MAX_RESULTADOS_BUSQUEDA = 60


class ErrorEspacio(Exception):
    pass


def ejecutar(cmd, cwd, timeout=600, env=None):
    """Corre un comando fijo (lista, sin shell) y devuelve (código, salida combinada)."""
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env={**os.environ, **(env or {})})
    except subprocess.TimeoutExpired:
        return 124, f'Tiempo agotado ({timeout} s): {" ".join(cmd)}'
    return r.returncode, (r.stdout or '') + (r.stderr or '')


class Espacio:
    def __init__(self, raiz):
        self.raiz = Path(raiz).resolve()
        self.base = 'origin/main'

    def repo(self, nombre):
        return self.raiz / nombre

    # --- Git ------------------------------------------------------------------------
    def preparar(self, rama, bases=None):
        """Deja cada repositorio en `rama`, nueva y sin cambios sueltos. Parte de origin/main o, con
        `bases` ({repo: ruta}), del punto de partida que aplicar_local guardó en ese repositorio."""
        self.base = 'refs/desarrollador/base' if bases else 'origin/main'
        for nombre in REPOS:
            r = self.repo(nombre)
            traer = (['git', 'fetch', '-q', '--no-tags', str(bases[nombre]), f'+{self.base}:{self.base}'] if bases
                     else ['git', 'fetch', '-q', 'origin', 'main'])
            for cmd in (traer, ['git', 'checkout', '-q', '-B', rama, self.base],
                        ['git', 'reset', '-q', '--hard', self.base],
                        ['git', 'clean', '-q', '-fd', '-e', 'node_modules', '-e', '.venv']):
                codigo, salida = ejecutar(cmd, r, timeout=180)
                if codigo:
                    raise ErrorEspacio(f'{nombre}: {" ".join(cmd[:3])} falló: {salida[-400:]}')

    def cambios(self, nombre):
        codigo, salida = ejecutar(['git', 'status', '--porcelain'], self.repo(nombre), timeout=60)
        return [l[3:] for l in salida.splitlines() if l.strip()] if not codigo else []

    def diff(self, nombre, maximo=150000):
        r = self.repo(nombre)
        ejecutar(['git', 'add', '-A', '-N'], r, timeout=60)  # que los archivos nuevos salgan en el diff
        _, resumen = ejecutar(['git', 'diff', '--stat', self.base], r, timeout=60)
        _, parche = ejecutar(['git', 'diff', self.base], r, timeout=60)
        texto = f'### {nombre}\n{resumen}\n{parche}'
        return texto if len(texto) <= maximo else texto[:maximo] + '\n… (diff recortado)'

    def commit(self, nombre, mensaje, rama):
        r = self.repo(nombre)
        if not self.cambios(nombre):
            return None
        for cmd in (['git', 'add', '-A'],
                    ['git', '-c', 'user.name=Desarrollador IA Lottus', '-c', 'user.email=desarrollador@muebleslottus.com',
                     'commit', '-q', '-m', mensaje],
                    ['git', 'push', '-q', '--force', 'origin', f'HEAD:refs/heads/{rama}']):
            codigo, salida = ejecutar(cmd, r, timeout=180)
            if codigo:
                raise ErrorEspacio(f'{nombre}: {" ".join(cmd[:2])} falló: {salida[-400:]}')
        _, sha = ejecutar(['git', 'rev-parse', '--short', 'HEAD'], r, timeout=30)
        return sha.strip()

    # --- Rutas seguras --------------------------------------------------------------
    def ruta(self, relativa, escribir=False):
        rel = str(relativa or '').strip().lstrip('/').replace('\\', '/')
        if not rel or rel.split('/')[0] not in REPOS:
            raise ErrorEspacio('La ruta debe empezar por backend/ o frontend/.')
        destino = (self.raiz / rel).resolve()
        if self.raiz not in destino.parents and destino != self.raiz:
            raise ErrorEspacio('Ruta fuera del espacio de trabajo.')
        partes = Path(rel).parts
        if any(p in CARPETAS_OCULTAS for p in partes) or any(PATRON_SECRETO.search(p) for p in partes):
            raise ErrorEspacio('Ese archivo o carpeta no está disponible (dependencias, compilados o datos sensibles).')
        if escribir and any(p.search(rel) for p in SOLO_LECTURA):
            raise ErrorEspacio('Ese archivo es de solo lectura para el agente (configuración, dependencias, migraciones o despliegue).')
        return destino, rel

    # --- Herramientas del modelo ------------------------------------------------------
    def listar(self, ruta):
        destino, rel = self.ruta(ruta)
        if not destino.is_dir():
            raise ErrorEspacio('No es una carpeta.')
        entradas = []
        for e in sorted(destino.iterdir(), key=lambda x: (not x.is_dir(), x.name)):
            if e.name in CARPETAS_OCULTAS or PATRON_SECRETO.search(e.name):
                continue
            entradas.append(e.name + ('/' if e.is_dir() else f'  ({e.stat().st_size} bytes)'))
        return '\n'.join(entradas[:400]) or '(vacía)'

    def leer(self, ruta, desde=1, hasta=None):
        destino, rel = self.ruta(ruta)
        if not destino.is_file():
            raise ErrorEspacio('No existe ese archivo.')
        lineas = destino.read_text(encoding='utf-8', errors='replace').splitlines()
        desde = max(1, int(desde or 1))
        hasta = min(len(lineas), int(hasta) if hasta else len(lineas))
        partes, total = [], 0
        for n in range(desde, hasta + 1):
            linea = f'{n}\t{lineas[n - 1]}'
            if total + len(linea) > MAX_LECTURA:
                partes.append(f'… (recortado en la línea {n - 1}; pide desde={n} para seguir)')
                break
            partes.append(linea)
            total += len(linea) + 1
        return f'{rel} ({len(lineas)} líneas)\n' + '\n'.join(partes)

    def buscar(self, texto, ruta='', es_regex=False):
        base, _ = self.ruta(ruta) if ruta else (self.raiz, '')
        try:
            patron = re.compile(texto if es_regex else re.escape(texto))
        except re.error as e:
            raise ErrorEspacio(f'Expresión inválida: {e}')
        resultados = []
        archivos = [base] if base.is_file() else sorted(base.rglob('*'))
        for f in archivos:
            if not f.is_file() or f.stat().st_size > 800000:
                continue
            rel = str(f.relative_to(self.raiz))
            partes = Path(rel).parts
            if any(p in CARPETAS_OCULTAS for p in partes) or any(PATRON_SECRETO.search(p) for p in partes):
                continue
            if f.suffix not in {'.py', '.js', '.jsx', '.ts', '.tsx', '.css', '.html', '.md', '.json', '.txt', '.sh'}:
                continue
            try:
                for n, linea in enumerate(f.read_text(encoding='utf-8', errors='replace').splitlines(), 1):
                    if patron.search(linea):
                        resultados.append(f'{rel}:{n}: {linea.strip()[:200]}')
                        if len(resultados) >= MAX_RESULTADOS_BUSQUEDA:
                            return '\n'.join(resultados) + '\n… (más resultados; acota la búsqueda)'
            except OSError:
                continue
        return '\n'.join(resultados) or 'Sin resultados.'

    def escribir(self, ruta, contenido):
        destino, rel = self.ruta(ruta, escribir=True)
        if len(contenido) > MAX_ESCRITURA:
            raise ErrorEspacio('Contenido demasiado grande; divide el cambio o reemplaza fragmentos.')
        destino.parent.mkdir(parents=True, exist_ok=True)
        nuevo = not destino.exists()
        destino.write_text(contenido, encoding='utf-8')
        return f'{"Creado" if nuevo else "Reescrito"} {rel} ({len(contenido.splitlines())} líneas).'

    def reemplazar(self, ruta, buscar, reemplazo):
        destino, rel = self.ruta(ruta, escribir=True)
        if not destino.is_file():
            raise ErrorEspacio('No existe ese archivo.')
        texto = destino.read_text(encoding='utf-8')
        veces = texto.count(buscar) if buscar else 0
        if veces != 1:
            raise ErrorEspacio(f'El texto a reemplazar aparece {veces} veces; debe aparecer exactamente una (cópialo exacto, con más contexto).')
        destino.write_text(texto.replace(buscar, reemplazo, 1), encoding='utf-8')
        return f'Reemplazado en {rel}.'

    def borrar(self, ruta):
        destino, rel = self.ruta(ruta, escribir=True)
        if not destino.is_file():
            raise ErrorEspacio('No existe ese archivo.')
        destino.unlink()
        return f'Borrado {rel}.'


# --- Migraciones: la cadena de ordenes va antes del merge de Bancos ---------------------

MERGE = 'backend/ordenes/migrations/0061_merge_bancos_y_nomina.py'


def encadenar_ordenes(espacio, nuevas):
    """makemigrations numera las nuevas de ordenes después de 0061_merge_bancos_y_nomina;
    en este proyecto cada una se encadena antes del merge (0057 de Bancos no se aplica):
    se renombra con el número siguiente a la última, depende de ella y el merge depende de la nueva."""
    merge = espacio.raiz / MERGE
    for rel in sorted(nuevas):
        if not re.match(r'^backend/ordenes/migrations/\d{4}_\w+\.py$', rel):
            continue
        archivo = espacio.raiz / rel
        texto = archivo.read_text(encoding='utf-8')
        if "('ordenes', '0061_merge_bancos_y_nomina')" not in texto:
            continue
        m = merge.read_text(encoding='utf-8')
        anterior = re.search(r"\('ordenes', '(0(?!057)\d{3}_\w+)'\)", m).group(1)
        nombre = f'{int(anterior[:4]) + 1:04d}{Path(rel).stem[4:]}'
        texto = texto.replace("('ordenes', '0061_merge_bancos_y_nomina')", f"('ordenes', '{anterior}')")
        destino = archivo.with_name(f'{nombre}.py')
        destino.write_text(texto, encoding='utf-8')
        archivo.unlink()
        merge.write_text(m.replace(f"'{anterior}'", f"'{nombre}'"), encoding='utf-8')


OPERACIONES_RIESGOSAS = re.compile(r'migrations\.(DeleteModel|RemoveField|RunSQL|RenameField|RenameModel|AlterField)\(')


def riesgo_migraciones(espacio, archivos):
    """Operaciones de las migraciones nuevas que pueden perder o transformar datos."""
    hallazgos = []
    for rel in archivos:
        f = espacio.raiz / rel
        if f.is_file():
            for op in OPERACIONES_RIESGOSAS.findall(f.read_text(encoding='utf-8')):
                hallazgos.append(f'{Path(rel).name}: {op}')
    return hallazgos
