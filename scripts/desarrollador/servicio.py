"""Servicio del agente Desarrollador (2026-10-28). Corre en el VPS como usuario `desarrollador`.

    python -m desarrollador.servicio        (desde /opt/lottus-desarrollador, con su .env)

- Espera avisos de la plataforma en 127.0.0.1:8020/despertar (y revisa el trabajo cada 5 min).
- planificando → prepara el plan con Gemini (solo lectura) → plan_listo.
- aprobada → implementa en la rama desarrollador/t<id>, corre verificaciones (corrige hasta 3
  veces), sube la rama, despliega la versión de pruebas (backend con respaldo de pruebasv3 y
  frontend en GitHub Pages) → en_pruebas con vista previa. Si algo falla → fallida.
- descartada con restaurar_pruebas → la versión de pruebas vuelve a main.
Nunca toca producción.

En el Mac (DESARROLLADOR_APLICAR_BACKEND / _FRONTEND, ver aplicar_local.py) no hay vista previa:
el agente parte del código local, y lo verificado se aplica ahí mismo → aplicada; «Deshacer»
(deshaciendo) lo revierte → deshecha.
"""
import logging
import os
import re
import shutil
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import requests

from .espacio import Espacio, ErrorEspacio, ejecutar, encadenar_ordenes, riesgo_migraciones
from .gemini import Agente, ErrorGemini, texto_pedido
from .aplicar_local import AplicarLocal

log = logging.getLogger('desarrollador')
INTENTOS_CORRECCION = 3
LATIDO = 300


class Config:
    def __init__(self, env=os.environ):
        self.token = env['DESARROLLADOR_TOKEN']
        self.api = env.get('DESARROLLADOR_API', 'http://127.0.0.1:8000/api').rstrip('/')
        self.host = env.get('DESARROLLADOR_HOST', 'api.muebleslottus.com')
        # Proveedor: el de DESARROLLADOR_PROVEEDOR (gemini, gpt o claude) o, si no se fija, según la
        # clave que exista: Claude, luego GPT y por último Gemini.
        self.proveedor = env.get('DESARROLLADOR_PROVEEDOR', '').strip().lower()
        self.clave_anthropic = env.get('DESARROLLADOR_ANTHROPIC_API_KEY', '')
        self.modelo_claude = env.get('DESARROLLADOR_CLAUDE_MODELO', 'claude-opus-5-5')
        self.esfuerzo_plan = env.get('DESARROLLADOR_CLAUDE_ESFUERZO_PLAN', 'medium')
        self.esfuerzo = env.get('DESARROLLADOR_CLAUDE_ESFUERZO', 'high')
        self.clave_openai = env.get('DESARROLLADOR_OPENAI_API_KEY', '')
        self.modelo_gpt = env.get('DESARROLLADOR_GPT_MODELO', 'gpt-5.5')
        self.esfuerzo_gpt_plan = env.get('DESARROLLADOR_GPT_ESFUERZO_PLAN', 'low')
        self.esfuerzo_gpt = env.get('DESARROLLADOR_GPT_ESFUERZO', 'medium')
        self.clave = env.get('DESARROLLADOR_GEMINI_API_KEY', '')
        # Gemini: Flash para planear (barato y rápido, solo lee) y Pro para implementar (2026-10-29).
        lista = lambda clave, defecto: [m.strip() for m in env.get(clave, defecto).split(',') if m.strip()]  # noqa: E731
        self.modelos = lista('DESARROLLADOR_MODELOS', 'gemini-3.1-pro-preview-customtools,gemini-3.1-pro-preview,gemini-3.5-flash')
        self.modelos_plan = lista('DESARROLLADOR_MODELOS_PLAN', 'gemini-3.8-flash,gemini-3.7-flash,gemini-3.5-flash')
        self.intervalo = float(env.get('DESARROLLADOR_INTERVALO', '0'))
        self.raiz = env.get('DESARROLLADOR_RAIZ', '/home/desarrollador/trabajo')
        self.python = env.get('DESARROLLADOR_PYTHON', '/home/desarrollador/venv/bin/python')
        self.node_bin = env.get('DESARROLLADOR_NODE_BIN', '/home/desarrollador/node/bin')
        self.api_pruebas = env.get('DESARROLLADOR_API_PRUEBAS', 'https://api.muebleslottus.com:8443/api')
        self.vista_previa = env.get('DESARROLLADOR_VISTA_PREVIA', 'https://stivenrodriguezm.github.io/ordenesPedidoSW/')
        # En el Mac: repositorios donde se aplican los cambios, carpeta de sus parches y de los respaldos.
        self.aplicar = {n: env[f'DESARROLLADOR_APLICAR_{n.upper()}'] for n in ('backend', 'frontend') if env.get(f'DESARROLLADOR_APLICAR_{n.upper()}')}
        self.aplicados = env.get('DESARROLLADOR_APLICADOS', os.path.expanduser('~/.lottus-desarrollador/aplicados'))
        self.respaldos = env.get('DESARROLLADOR_RESPALDOS', os.path.expanduser('~/.lottus-desarrollador/respaldos'))
        self.desplegar = env.get('DESARROLLADOR_DESPLEGAR', 'sudo -n -u stiven /opt/lottus-desarrollador/desplegar_pruebas.sh').split()
        self.puerto = int(env.get('DESARROLLADOR_PUERTO', '8020'))


class Plataforma:
    """Canal interno con la plataforma (token compartido). Cada llamada es una petición corta."""
    def __init__(self, cfg):
        self.cfg = cfg
        self.sesion = requests.Session()
        self.sesion.headers.update({'X-Desarrollador-Token': cfg.token, 'Host': cfg.host, 'X-Forwarded-Proto': 'https'})

    def _url(self, ruta):
        return f'{self.cfg.api}/desarrollador/interno/{ruta}'

    def pendientes(self):
        r = self.sesion.get(self._url('pendientes/'), timeout=20)
        r.raise_for_status()
        return r.json()

    def tarea(self, pk):
        r = self.sesion.get(self._url(f'tareas/{pk}/'), timeout=20)
        r.raise_for_status()
        return r.json()

    def actualizar(self, pk, **datos):
        r = self.sesion.patch(self._url(f'tareas/{pk}/'), json=datos, timeout=30)
        if r.status_code == 409:
            log.warning('Tarea %s: %s', pk, r.text[:200])
            return None
        r.raise_for_status()
        return r.json()

    def latido(self):
        try:
            self.sesion.post(self._url('latido/'), timeout=10)
        except requests.RequestException:
            pass


class Eventos:
    """Junta los avances y los envía de a varios (menos peticiones a la plataforma). El primero
    sale de una vez para que la página muestre enseguida que el agente ya empezó."""
    def __init__(self, plataforma, pk):
        self.plataforma, self.pk, self.pendientes, self.ultimo = plataforma, pk, [], float('-inf')

    def __call__(self, texto):
        log.info('t%s: %s', self.pk, texto)
        self.pendientes.append(str(texto)[:300])
        if time.monotonic() - self.ultimo > 20 or len(self.pendientes) >= 10:
            self.enviar()

    def enviar(self, **extra):
        if self.pendientes or extra:
            self.plataforma.actualizar(self.pk, eventos=self.pendientes, **extra)
            self.pendientes, self.ultimo = [], time.monotonic()


class Servicio:
    def __init__(self, cfg, plataforma=None, espacio=None):
        self.cfg = cfg
        self.plataforma = plataforma or Plataforma(cfg)
        self.espacio = espacio or Espacio(cfg.raiz)
        self.local = (AplicarLocal(self.espacio, cfg.aplicar, cfg.aplicados, cfg.python, cfg.respaldos)
                      if set(cfg.aplicar) == {'backend', 'frontend'} else None)
        self.despertar = threading.Event()

    # --- Bucle -------------------------------------------------------------------
    def una_vuelta(self):
        for tarea in self.plataforma.pendientes():
            try:
                self.procesar(tarea)
            except Exception as exc:  # noqa: BLE001 — una tarea rota no detiene el servicio
                log.exception('Tarea %s falló', tarea.get('id'))
                try:
                    if tarea.get('estado') in ('planificando', 'aprobada', 'implementando'):
                        self.plataforma.actualizar(tarea['id'], estado='fallida', error=f'Error interno del servicio: {exc.__class__.__name__}: {str(exc)[:500]}')
                except Exception:  # noqa: BLE001
                    log.exception('No se pudo reportar el fallo')

    def procesar(self, tarea):
        if tarea['estado'] == 'planificando':
            self.planear(tarea)
        elif tarea['estado'] in ('aprobada', 'implementando'):
            self.implementar(tarea)
        elif tarea['estado'] == 'deshaciendo':
            self.deshacer(tarea)
        elif tarea['estado'] == 'descartada' and (tarea.get('resultado') or {}).get('restaurar_pruebas'):
            self.restaurar_pruebas(tarea)

    def _agente(self, modo, tarea, **opciones):
        usuario = tarea.get('usuario', 'el usuario')
        proveedor = self.cfg.proveedor or ('claude' if self.cfg.clave_anthropic else 'gpt' if self.cfg.clave_openai else 'gemini')
        if proveedor == 'claude':
            from .claude import AgenteClaude  # el SDK de Anthropic solo hace falta si se usa Claude
            return AgenteClaude(self.cfg.clave_anthropic, self.cfg.modelo_claude, self.espacio, modo, usuario,
                                esfuerzo=self.cfg.esfuerzo_plan if modo == 'plan' else self.cfg.esfuerzo, **opciones)
        if proveedor == 'gpt':
            from .gpt import AgenteGPT
            return AgenteGPT(self.cfg.clave_openai, self.cfg.modelo_gpt, self.espacio, modo, usuario,
                             esfuerzo=self.cfg.esfuerzo_gpt_plan if modo == 'plan' else self.cfg.esfuerzo_gpt, **opciones)
        modelos = self.cfg.modelos_plan if modo == 'plan' else self.cfg.modelos
        return Agente(self.cfg.clave, modelos, self.espacio, modo, usuario, intervalo=self.cfg.intervalo, **opciones)

    # --- Plan ----------------------------------------------------------------------
    def planear(self, tarea):
        pk = tarea['id']
        ev = Eventos(self.plataforma, pk)
        ev('Leyendo el código para preparar el plan.')
        self.espacio.preparar(f'desarrollador/t{pk}', self.local and self.local.foto())
        agente = self._agente('plan', tarea, tiempo_max=1500)
        try:
            _, plan = agente.conversar(texto_pedido(tarea))
        except ErrorGemini as exc:
            ev.enviar(estado='fallida', error=str(exc), tokens_suma=agente.tokens, modelo=agente.modelo or '')
            return
        plan = {k: plan.get(k) for k in ('entendido', 'pasos', 'archivos', 'riesgo', 'riesgos', 'cambia_base_datos', 'cambios_pantalla', 'preguntas')}
        if plan.get('riesgo') not in ('bajo', 'medio', 'alto'):
            plan['riesgo'] = 'medio'
        ev('Plan listo para tu aprobación.')
        ev.enviar(estado='plan_listo', plan=plan, tokens_suma=agente.tokens, modelo=agente.modelo or '')

    # --- Implementación ----------------------------------------------------------
    def implementar(self, tarea):
        pk = tarea['id']
        rama = f'desarrollador/t{pk}'
        ev = Eventos(self.plataforma, pk)
        if tarea['estado'] == 'aprobada':
            if self.plataforma.actualizar(pk, estado='implementando', eventos=['Empezando la implementación.']) is None:
                return
        self.espacio.preparar(rama, self.local and self.local.foto())
        agente = self._agente('implementar', tarea, al_evento=ev, tiempo_max=3600)
        mensaje = texto_pedido({**tarea, 'estado': 'implementando'})
        final = None
        try:
            for intento in range(INTENTOS_CORRECCION + 1):
                _, final = agente.conversar(mensaje)
                ev('Implementación lista. Corriendo las verificaciones (puede tardar unos minutos).')
                ok, informe, migraciones = self.verificar(ev)
                if ok:
                    break
                if intento == INTENTOS_CORRECCION:
                    ev.enviar(estado='fallida', error='Las verificaciones siguen fallando después de varios intentos:\n' + informe[-6000:],
                              diff=self._diff(), tokens_suma=agente.tokens, modelo=agente.modelo or '')
                    return
                ev(f'Verificación con fallos; corrigiendo (intento {intento + 1} de {INTENTOS_CORRECCION}).')
                mensaje = 'Las verificaciones fallaron. Corrige y vuelve a llamar terminar:\n' + informe[-12000:]
        except (ErrorGemini, ErrorEspacio) as exc:
            ev.enviar(estado='fallida', error=str(exc), diff=self._diff(), tokens_suma=agente.tokens, modelo=agente.modelo or '')
            return
        diff = self._diff()
        if not diff.strip() or not any(self.espacio.cambios(n) for n in ('backend', 'frontend')):
            ev.enviar(estado='fallida', error='El agente no dejó cambios en el código.', tokens_suma=agente.tokens, modelo=agente.modelo or '')
            return
        mensaje_commit = f'Desarrollador IA · tarea #{pk}: {tarea["pedido"][:60]}\n\n{(final or {}).get("resumen", "")[:1500]}'
        commits = {n: self.espacio.commit(n, mensaje_commit, rama) for n in ('backend', 'frontend')}
        resultado = {'resumen': (final or {}).get('resumen', ''), 'cambios_pantalla': (final or {}).get('cambios_pantalla', ''),
                     'pruebas_agregadas': (final or {}).get('pruebas_agregadas') or [], 'rama': rama, 'commits': commits,
                     'migraciones': migraciones, 'verificaciones': 'Pruebas, lint y build sin errores.'}
        if self.local:
            ev('Verificado. Aplicando en tu plataforma.')
            try:
                resultado['aplicado'] = self.local.aplicar(pk, ev)
            except ErrorEspacio as exc:
                ev.enviar(estado='fallida', error=f'Se implementó y verificó, pero no se pudo aplicar: {exc}', diff=diff,
                          resultado={'rama': rama, 'commits': commits}, tokens_suma=agente.tokens, modelo=agente.modelo or '')
                return
            ev.enviar(estado='aplicada', resultado=resultado, diff=diff, tokens_suma=agente.tokens, modelo=agente.modelo or '')
            return
        ev('Cambios guardados en la rama ' + rama + '. Publicando en la versión de pruebas.')
        try:
            self.publicar_pruebas(rama if commits['backend'] else 'main', rama if commits['frontend'] else 'main', ev)
        except ErrorEspacio as exc:
            ev.enviar(estado='fallida', error=f'Se implementó y verificó, pero no se pudo publicar en pruebas: {exc}', diff=diff,
                      resultado={'rama': rama, 'commits': commits}, tokens_suma=agente.tokens, modelo=agente.modelo or '')
            return
        ev('Listo en la versión de pruebas.')
        ev.enviar(estado='en_pruebas', resultado=resultado, diff=diff, vista_previa=self.cfg.vista_previa,
                  tokens_suma=agente.tokens, modelo=agente.modelo or '')

    def deshacer(self, tarea):
        ev = Eventos(self.plataforma, tarea['id'])
        try:
            if not self.local:
                raise ErrorEspacio('deshacer solo está disponible donde se aplicó el cambio')
            self.local.deshacer(tarea['id'], (tarea.get('resultado') or {}).get('aplicado') or {}, ev)
        except ErrorEspacio as exc:
            ev.enviar(estado='aplicada', error=f'No se pudo deshacer: {exc}')
            return
        ev.enviar(estado='deshecha', error='')

    def _diff(self):
        return '\n'.join(self.espacio.diff(n) for n in ('backend', 'frontend') if self.espacio.cambios(n))

    # --- Verificaciones -----------------------------------------------------------
    def verificar(self, ev):
        """Migraciones, pruebas, lint y build de lo que cambió. Devuelve (ok, informe, migraciones)."""
        back, front = self.espacio.repo('backend'), self.espacio.repo('frontend')
        informe, ok, migraciones = [], True, {}
        cambios_back = self.espacio.cambios('backend')
        if cambios_back:
            antes = set(self._migraciones())
            codigo, salida = ejecutar([self.cfg.python, 'manage.py', 'makemigrations', '--settings=lottusPedidos.settings_test'], back, timeout=300)
            nuevas = sorted(set(self._migraciones()) - antes)
            if nuevas:
                encadenar_ordenes(self.espacio, nuevas)
                nuevas = sorted(set(self._migraciones()) - antes)
                migraciones = {'archivos': nuevas, 'operaciones_riesgosas': riesgo_migraciones(self.espacio, nuevas)}
                ev('Migración de base de datos generada: ' + ', '.join(Path(n).name for n in nuevas))
            for nombre, cmd, limite in (
                    ('check', [self.cfg.python, 'manage.py', 'check', '--settings=lottusPedidos.settings_test'], 300),
                    ('migraciones', [self.cfg.python, 'manage.py', 'makemigrations', '--check', '--dry-run', '--settings=lottusPedidos.settings_test'], 300),
                    ('pruebas backend', [self.cfg.python, 'manage.py', 'test', '--settings=lottusPedidos.settings_test', '--parallel', '1', '--noinput'], 1500)):
                codigo, salida = ejecutar(cmd, back, timeout=limite)
                informe.append(f'## {nombre}: {"OK" if codigo == 0 else "FALLÓ"}\n{salida[-5000:] if codigo else salida[-300:]}')
                ok = ok and codigo == 0
                if codigo:
                    break
        if self.espacio.cambios('frontend') and ok:
            env = {'PATH': f'{self.cfg.node_bin}:{os.environ.get("PATH", "")}', 'CI': '1'}
            for nombre, cmd, limite in (
                    ('lint', ['npx', 'eslint', 'src', '--quiet'], 600),
                    ('pruebas frontend', ['npx', 'vitest', 'run'], 1500),
                    ('build', ['npx', 'vite', 'build', '--outDir', str(Path(tempfile.gettempdir()) / 'desarrollador-build-check'), '--emptyOutDir'], 900)):
                codigo, salida = ejecutar(cmd, front, timeout=limite, env=env)
                informe.append(f'## {nombre}: {"OK" if codigo == 0 else "FALLÓ"}\n{salida[-5000:] if codigo else salida[-300:]}')
                ok = ok and codigo == 0
                if codigo:
                    break
        ev('Verificaciones: ' + ('todas pasaron.' if ok else 'hay fallos.'))
        return ok, '\n\n'.join(informe), migraciones

    def _migraciones(self):
        return [str(p.relative_to(self.espacio.raiz)) for p in self.espacio.repo('backend').glob('*/migrations/0*.py')]

    # --- Versión de pruebas ------------------------------------------------------
    def publicar_pruebas(self, ref_backend, ref_frontend, ev):
        codigo, salida = ejecutar([*self.cfg.desplegar, ref_backend], self.espacio.raiz, timeout=1800)
        if codigo:
            raise ErrorEspacio('backend de pruebas: ' + salida[-1500:])
        ev('Backend de pruebas actualizado.' + (' ' + salida.strip().splitlines()[-1] if salida.strip() else ''))
        self.publicar_frontend(ref_frontend, ev)

    def publicar_frontend(self, ref, ev):
        """Compila el frontend contra el API de pruebas y lo publica en GitHub Pages (rama gh-pages)."""
        front = self.espacio.repo('frontend')
        env = {'PATH': f'{self.cfg.node_bin}:{os.environ.get("PATH", "")}', 'VITE_API_BASE_URL': self.cfg.api_pruebas}
        tmp = Path(tempfile.mkdtemp(prefix='desarrollador-pages-'))
        try:
            if ref == 'main':  # sin cambios de frontend: se publica main en un árbol aparte
                fuente = tmp / 'fuente'
                for cmd in (['git', 'fetch', '-q', 'origin', 'main'], ['git', 'worktree', 'add', '-q', '--detach', str(fuente), 'origin/main']):
                    codigo, salida = ejecutar(cmd, front, timeout=180)
                    if codigo:
                        raise ErrorEspacio('frontend: ' + salida[-400:])
                (fuente / 'node_modules').symlink_to(front / 'node_modules')
            else:
                fuente = front
            codigo, salida = ejecutar(['npx', 'vite', 'build', '--base=./', '--outDir', str(tmp / 'build'), '--emptyOutDir'], fuente, timeout=900, env=env)
            if codigo:
                raise ErrorEspacio('compilación del frontend de pruebas: ' + salida[-800:])
            pages = tmp / 'pages'
            for cmd in (['git', 'fetch', '-q', 'origin', 'gh-pages'], ['git', 'worktree', 'add', '-q', '--detach', str(pages), 'origin/gh-pages']):
                codigo, salida = ejecutar(cmd, front, timeout=180)
                if codigo:
                    raise ErrorEspacio('gh-pages: ' + salida[-400:])
            pagina_404 = (pages / '404.html').read_bytes() if (pages / '404.html').exists() else None
            for hijo in pages.iterdir():
                if hijo.name != '.git':
                    shutil.rmtree(hijo) if hijo.is_dir() else hijo.unlink()
            shutil.copytree(tmp / 'build', pages, dirs_exist_ok=True)
            (pages / '_redirects').unlink(missing_ok=True)
            (pages / '.nojekyll').touch()
            if pagina_404:
                (pages / '404.html').write_bytes(pagina_404)
            index = pages / 'index.html'
            html = index.read_text(encoding='utf-8')
            html = html.replace('<head>', '<head>\n    <meta name="robots" content="noindex, nofollow">', 1)
            html = re.sub(r'\s*<script>\s*var path = window\.location\.pathname;.*?</script>', '', html, flags=re.S)
            index.write_text(html, encoding='utf-8')
            for cmd in (['git', 'add', '-A'],
                        ['git', '-c', 'user.name=Desarrollador IA Lottus', '-c', 'user.email=desarrollador@muebleslottus.com',
                         'commit', '-q', '--allow-empty', '-m', f'Versión de pruebas: {ref}'],
                        ['git', 'push', '-q', 'origin', 'HEAD:gh-pages']):
                codigo, salida = ejecutar(cmd, pages, timeout=300)
                if codigo:
                    raise ErrorEspacio('publicar gh-pages: ' + salida[-400:])
            ev('Frontend de pruebas publicado (GitHub tarda ~1 min en mostrarlo).')
        finally:
            for wt in (tmp / 'pages', tmp / 'fuente'):
                if wt.exists():
                    ejecutar(['git', 'worktree', 'remove', '--force', str(wt)], front, timeout=120)
            shutil.rmtree(tmp, ignore_errors=True)

    def restaurar_pruebas(self, tarea):
        ev = Eventos(self.plataforma, tarea['id'])
        try:
            self.publicar_pruebas('main', 'main', ev)
            ev('La versión de pruebas volvió a la de producción.')
        except ErrorEspacio as exc:
            ev(f'No se pudo restaurar la versión de pruebas: {exc}')
        ev.enviar(resultado={'restaurar_pruebas': False})


# --- Arranque -------------------------------------------------------------------------

def _servidor(servicio):
    token = servicio.cfg.token

    class Aviso(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            if self.path.rstrip('/') == '/despertar' and self.headers.get('X-Desarrollador-Token') == token:
                servicio.despertar.set()
                self.send_response(202)
            else:
                self.send_response(403)
            self.end_headers()

        def log_message(self, *args):
            pass

    httpd = ThreadingHTTPServer(('127.0.0.1', servicio.cfg.puerto), Aviso)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def _latir(plataforma):
    """Latido aparte (sesión propia): sigue mientras una tarea larga ocupa el bucle principal."""
    while True:
        plataforma.latido()
        time.sleep(LATIDO)


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    servicio = Servicio(Config())
    _servidor(servicio)
    threading.Thread(target=_latir, args=(Plataforma(servicio.cfg),), daemon=True).start()
    log.info('Desarrollador listo en 127.0.0.1:%s', servicio.cfg.puerto)
    while True:
        try:
            servicio.una_vuelta()
        except requests.RequestException as exc:
            log.warning('Sin conexión con la plataforma: %s', exc)
        servicio.despertar.wait(timeout=LATIDO)
        servicio.despertar.clear()


if __name__ == '__main__':
    main()
