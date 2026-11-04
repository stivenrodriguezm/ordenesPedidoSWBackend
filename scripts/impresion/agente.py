#!/usr/bin/env python3
"""Agente de impresión de la oficina principal (2026-10-24; Windows desde 2026-10-30).

Corre en la computadora que tiene instalada la impresora. Cada pocos segundos le pregunta
a cada servidor configurado si hay documentos en cola; si hay, lo convierte a PDF con
Google Chrome o Edge (sin JavaScript) y lo manda a la impresora: en Mac a la cola CUPS con
`lp`; en Windows con SumatraPDF (va junto al agente, ver windows/empaquetar.sh). La oficina
no abre puertos: solo hace peticiones HTTPS de salida. Solo usa la biblioteca estándar.

Configuración (la crea `manage.py crear_impresora`, permisos 600):
    Mac: ~/Library/Application Support/LottusImpresion/config.json
    Windows: %LOCALAPPDATA%\\LottusImpresion\\config.json
    {"cola": "RICOH_…", "servidores": [{"nombre": "…", "api": "https://…/api", "token": "…"}]}
Opcionales: "intervalo" (segundos, 3), "chrome" (ruta), "simular" (true = guarda el PDF
en la carpeta «simulados» en vez de imprimir).

Uso:  python3 agente.py            (lo deja corriendo el LaunchAgent com.lottus.impresion
                                    o, en Windows, el acceso directo de Inicio)
      python3 agente.py --simular  (no imprime; deja los PDF en la carpeta «simulados»)
      python3 agente.py --probar   (imprime una página de prueba y termina)
"""
import json
import logging
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ES_WINDOWS = os.name == 'nt'
CARPETA = (Path(os.environ.get('LOCALAPPDATA') or Path.home()) / 'LottusImpresion' if ES_WINDOWS
           else Path.home() / 'Library' / 'Application Support' / 'LottusImpresion')
CONFIG = CARPETA / 'config.json'
CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
NAVEGADORES_WINDOWS = (r'Microsoft\Edge\Application\msedge.exe', r'Google\Chrome\Application\chrome.exe')
# En Windows, sin esto cada subproceso abriría una ventana de consola.
SIN_VENTANA = {'creationflags': 0x08000000} if ES_WINDOWS else {}
# El documento llega de la plataforma: sin scripts y sin pedir nada a la red local (solo
# las fuentes de Google y las imágenes https/data que pueda traer).
CSP = ('<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
       'style-src \'unsafe-inline\' https://fonts.googleapis.com; font-src https://fonts.gstatic.com data:; '
       'img-src https: data:">')
SEGUIMIENTO_MIN = 15
REVISAR_IMPRESORA_SEG = 30   # cada cuánto se busca la impresora en la red
CANCELAR_SEG = 90            # sin impresora, lo que lleva este tiempo en la cola se cancela y se avisa
NO_ENCONTRADA = ('La computadora de la oficina no encuentra la impresora: revisa que esté encendida '
                 'y en la misma red que esa computadora.')
# macOS responde en el idioma del sistema aunque se pida otro: nada depende del texto de lp/lpstat.

log = logging.getLogger('impresion')


def cargar_config():
    config = json.loads(CONFIG.read_text(encoding='utf-8-sig'))  # PowerShell lo guarda con BOM
    if not config.get('cola') or not config.get('servidores'):
        raise SystemExit(f'{CONFIG}: falta "cola" o "servidores".')
    return config


def pedir(servidor, ruta, datos=None):
    """POST a la API del servidor con el token de la impresora. Devuelve (estado, json)."""
    req = urllib.request.Request(
        servidor['api'].rstrip('/') + ruta, method='POST',
        data=json.dumps(datos or {}).encode(),
        headers={'Authorization': f'Impresora {servidor["token"]}', 'Content-Type': 'application/json',
                 'User-Agent': 'LottusImpresion/1'})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            cuerpo = r.read()
            return r.status, (json.loads(cuerpo) if cuerpo else None)
    except urllib.error.HTTPError as e:
        return e.code, None


def buscar_navegador():
    if not ES_WINDOWS:
        return CHROME
    for base in (os.environ.get('ProgramFiles(x86)'), os.environ.get('ProgramFiles'), os.environ.get('LOCALAPPDATA')):
        for relativa in NAVEGADORES_WINDOWS:
            if base and (Path(base) / relativa).exists():
                return str(Path(base) / relativa)
    raise RuntimeError('No se encontró Edge ni Chrome en esta computadora.')


def a_pdf(html, destino, chrome):
    """Convierte el documento a PDF con Chrome sin interfaz. Respeta su @page (carta, márgenes)."""
    html = re.sub(r'<head[^>]*>', lambda m: m.group(0) + CSP, html, count=1, flags=re.I) \
        if re.search(r'<head[^>]*>', html, re.I) else CSP + html
    with tempfile.TemporaryDirectory() as tmp:
        fuente = Path(tmp) / 'documento.html'
        fuente.write_text(html, encoding='utf-8')
        subprocess.run([
            chrome, '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
            '--disable-extensions', '--hide-scrollbars', f'--user-data-dir={Path(tmp) / "perfil"}',
            '--no-pdf-header-footer', '--print-to-pdf-no-header', '--virtual-time-budget=5000',
            f'--print-to-pdf={destino}', fuente.as_uri(),
        ], check=True, capture_output=True, timeout=90, **SIN_VENTANA)
    if not destino.exists() or destino.stat().st_size == 0:
        raise RuntimeError('Chrome no generó el PDF')


def imprimir(pdf, cola, copias, titulo):
    """Manda el PDF a CUPS. Devuelve el id del trabajo de CUPS (p. ej. RICOH_…-123)."""
    r = subprocess.run(['lp', '-d', cola, '-n', str(copias), '-t', titulo[:100], '-o', 'media=Letter', str(pdf)],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip() or 'lp falló')
    # «request id is COLA-12 …» o «la solicitud es COLA-12 …», según el idioma del sistema.
    m = re.search(re.escape(cola) + r'-\d+', r.stdout)
    return m.group(0) if m else None


def impresora_encontrada(cola):
    """True o False si la impresora de la cola responde en la red; None si no se puede saber
    (USB, cola desconocida). Solo mira códigos de salida y la URI, no textos traducidos."""
    try:
        salida = subprocess.run(['lpstat', '-v', cola], capture_output=True, text=True, timeout=10).stdout
        m = re.search(r'(\w+)://(\S+)', salida)
        if not m:
            return None
        if m.group(1) == 'dnssd':
            servicio = urllib.parse.unquote(m.group(2).split('/')[0])
            return subprocess.run(['ippfind', servicio, '-T', '3'], capture_output=True, timeout=15).returncode == 0
        if m.group(1) in ('ipp', 'ipps', 'http', 'https', 'socket', 'lpd'):
            url = urllib.parse.urlsplit(m.group(0))
            puerto = url.port or {'socket': 9100, 'lpd': 515, 'http': 80, 'https': 443}.get(m.group(1), 631)
            try:
                socket.create_connection((url.hostname, puerto), timeout=3).close()
                return True
            except OSError:
                return False
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def cancelar_en_cups(cups):
    subprocess.run(['cancel', cups], capture_output=True, timeout=20)


def cola_detenida(cola):
    r = subprocess.run(['lpoptions', '-p', cola], capture_output=True, text=True)
    return 'printer-state=5' in r.stdout.split()  # 3 libre, 4 imprimiendo, 5 en pausa


def pendientes_cups(cola):
    r = subprocess.run(['lpstat', '-W', 'not-completed', '-o', cola], capture_output=True, text=True)
    return {linea.split()[0] for linea in r.stdout.splitlines() if linea.strip()}


# ---------------------------------------------------------------------------
# Windows: la impresora se maneja con los comandos de impresión de PowerShell
# (Windows 8 en adelante) y el PDF se imprime con SumatraPDF, que va junto al agente.
# ---------------------------------------------------------------------------

def _powershell(script, timeout=30):
    r = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', script],
                       capture_output=True, text=True, timeout=timeout, **SIN_VENTANA)
    return r.returncode, r.stdout.strip()


def _ps_texto(valor):
    return "'" + str(valor).replace("'", "''") + "'"


def pendientes_windows(cola):
    _, salida = _powershell(f'Get-PrintJob -PrinterName {_ps_texto(cola)} | ForEach-Object {{ $_.Id }}')
    return {linea.strip() for linea in salida.splitlines() if linea.strip()}


def imprimir_windows(pdf, cola, copias, titulo):
    """Devuelve el id del trabajo en la cola de Windows, o None si ya salió de la cola."""
    antes = pendientes_windows(cola)
    sumatra = Path(__file__).resolve().parent / 'SumatraPDF.exe'
    r = subprocess.run([str(sumatra), '-print-to', cola, '-silent', '-print-settings', f'{copias}x,noscale,paper=letter', str(pdf)],
                       capture_output=True, text=True, timeout=120, **SIN_VENTANA)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip() or 'SumatraPDF no pudo imprimir')
    nuevos = pendientes_windows(cola) - antes
    return min(nuevos, key=int) if nuevos else None


def _estado_windows(cola):
    codigo, salida = _powershell(
        f'$p = Get-Printer -Name {_ps_texto(cola)} -ErrorAction Stop; '
        '$o = Get-PrinterPort -Name $p.PortName -ErrorAction SilentlyContinue; '
        '@{estado=[string]$p.PrinterStatus; host=[string]$o.PrinterHostAddress; puerto=[string]$o.PortNumber} | ConvertTo-Json -Compress')
    return json.loads(salida) if codigo == 0 and salida else None


def cola_detenida_windows(cola):
    estado = _estado_windows(cola)
    return bool(estado) and estado.get('estado') == 'Paused'


def impresora_encontrada_windows(cola):
    """False si Windows no la tiene o la ve desconectada, o si su dirección no responde;
    None si no se puede comprobar (USB o WSD, sin dirección fija)."""
    try:
        estado = _estado_windows(cola)
        if not estado or estado.get('estado') == 'Offline':
            return False
        if not estado.get('host'):
            return None
        try:
            socket.create_connection((estado['host'], int(estado.get('puerto') or 9100)), timeout=3).close()
            return True
        except OSError:
            return False
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def cancelar_windows(trabajo):
    cola = cargar_config()['cola']
    _powershell(f'Remove-PrintJob -PrinterName {_ps_texto(cola)} -ID {int(trabajo)}')


if ES_WINDOWS:
    imprimir, cola_detenida, pendientes_cups = imprimir_windows, cola_detenida_windows, pendientes_windows
    impresora_encontrada, cancelar_en_cups = impresora_encontrada_windows, cancelar_windows


class Agente:
    def __init__(self, simular=False):
        self.config = cargar_config()
        self.simular = simular or bool(self.config.get('simular'))
        self.chrome = self.config.get('chrome') or buscar_navegador()
        self.en_vuelo = {}   # id CUPS -> (servidor, id del trabajo, desde)
        self.fallos = {}     # nombre del servidor -> intentos fallidos seguidos (para espaciar los avisos)
        self.espera = {}     # nombre del servidor -> no consultar antes de este instante
        self.turno = threading.Lock()  # un documento a la vez (Chrome y lp), venga del servidor que venga
        self.impresora_ok = None       # última búsqueda de la impresora (None = no se sabe)
        self.revisada = 0
        self.avisados = set()          # trabajos de CUPS a los que ya se les avisó que no hay impresora

    def procesar(self, servidor, t):
        with self.turno:
            self._procesar(servidor, t)

    def _procesar(self, servidor, t):
        log.info('[%s] trabajo %s «%s» × %s', servidor['nombre'], t['id'], t['titulo'], t['copias'])
        ruta = f'/impresion/agente/trabajos/{t["id"]}/'
        try:
            with tempfile.TemporaryDirectory() as tmp:
                pdf = Path(tmp) / 'documento.pdf'
                a_pdf(t['html'], pdf, self.chrome)
                if self.simular:
                    salida = CARPETA / 'simulados' / f'{time.strftime("%Y%m%d-%H%M%S")}-{t["id"]}.pdf'
                    salida.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy(pdf, salida)
                    log.info('  simulado: %s', salida)
                    pedir(servidor, ruta, {'estado': 'impreso', 'detalle': 'Simulación: no se imprimió en papel.'})
                    return
                cups = imprimir(pdf, self.config['cola'], t['copias'], t['titulo'])
            detalle = 'La impresora está en pausa en la computadora de la oficina.' if cola_detenida(self.config['cola']) else ''
            if self.impresora_ok is False:
                detalle = NO_ENCONTRADA
                if cups:
                    self.avisados.add(cups)
            if not cups:  # CUPS lo aceptó pero no se pudo leer su número: no hay cómo seguirlo
                pedir(servidor, ruta, {'estado': 'impreso', 'detalle': detalle or 'Enviado a la impresora.'})
                log.info('  enviado a la impresora (sin número de CUPS)')
                return
            pedir(servidor, ruta, {'estado': 'enviado', 'detalle': detalle})
            self.en_vuelo[cups] = (servidor, t['id'], time.time())
            log.info('  enviado a la impresora (%s)', cups)
        except Exception as e:  # noqa: BLE001 — cualquier falla se informa a la plataforma
            log.exception('  no se pudo imprimir')
            mensaje = str(e) if not isinstance(e, subprocess.CalledProcessError) else 'Chrome no pudo convertir el documento.'
            pedir(servidor, ruta, {'estado': 'error', 'detalle': f'No se pudo imprimir: {mensaje}'[:255]})

    def revisar_impresora(self):
        if self.simular or time.time() - self.revisada < REVISAR_IMPRESORA_SEG:
            return
        self.revisada = time.time()
        ok = impresora_encontrada(self.config['cola'])
        if ok != self.impresora_ok:
            log.info('Impresora %s', {True: 'encontrada en la red', False: 'NO encontrada en la red', None: 'sin revisar'}[ok])
        self.impresora_ok = ok

    def revisar_en_vuelo(self):
        with self.turno:
            vuelo = list(self.en_vuelo.items())
        if not vuelo:
            return
        siguen = pendientes_cups(self.config['cola'])
        for cups, (servidor, pk, desde) in vuelo:
            ruta = f'/impresion/agente/trabajos/{pk}/'
            if cups not in siguen:
                pedir(servidor, ruta, {'estado': 'impreso'})
                log.info('  %s impreso', cups)
                self.en_vuelo.pop(cups, None)
            elif self.impresora_ok is False and time.time() - desde > CANCELAR_SEG and impresora_encontrada(self.config['cola']) is False:
                # Se cancela: que no salga una hoja sorpresa cuando la impresora vuelva.
                cancelar_en_cups(cups)
                pedir(servidor, ruta, {'estado': 'error', 'detalle': f'{NO_ENCONTRADA} No se imprimió: vuelve a enviarlo.'[:255]})
                log.warning('  %s cancelado: la impresora no aparece', cups)
                self.en_vuelo.pop(cups, None)
            elif self.impresora_ok is False and cups not in self.avisados:
                pedir(servidor, ruta, {'estado': 'enviado', 'detalle': NO_ENCONTRADA})
                self.avisados.add(cups)
            elif time.time() - desde > SEGUIMIENTO_MIN * 60:
                log.warning('  %s sigue en la cola de la impresora; se deja de seguir', cups)
                self.en_vuelo.pop(cups, None)

    def consultar(self, servidor):
        nombre = servidor['nombre']
        if time.time() < self.espera.get(nombre, 0):
            return
        try:
            estado, t = pedir(servidor, '/impresion/agente/siguiente/',
                              None if self.impresora_ok is None else {'impresora_ok': self.impresora_ok})
        except (urllib.error.URLError, OSError, ValueError) as e:
            estado, t = None, e
        if estado in (200, 204):
            if self.fallos.pop(nombre, 0):
                log.info('[%s] conexión restablecida', nombre)
            if estado == 200:
                self.procesar(servidor, t)
            return
        n = self.fallos[nombre] = self.fallos.get(nombre, 0) + 1
        self.espera[nombre] = time.time() + min(60, 3 * n)
        if n in (1, 10) or n % 100 == 0:
            motivo = 'token inválido o impresora desactivada' if estado == 401 else (f'HTTP {estado}' if estado else t)
            log.warning('[%s] sin conexión (%s), intento %s', nombre, motivo, n)

    def correr(self):
        log.info('Agente listo: cola %s, servidores %s%s', self.config['cola'],
                 ', '.join(s['nombre'] for s in self.config['servidores']), ' (SIMULACIÓN)' if self.simular else '')
        intervalo = float(self.config.get('intervalo', 3))

        # Cada servidor en su hilo: uno caído o lento no demora a los demás.
        def sondear(servidor):
            while True:
                try:
                    self.consultar(servidor)
                except Exception:  # noqa: BLE001
                    log.exception('[%s] error inesperado', servidor['nombre'])
                time.sleep(intervalo)

        for servidor in self.config['servidores']:
            threading.Thread(target=sondear, args=(servidor,), daemon=True, name=servidor['nombre']).start()
        while True:
            try:
                self.revisar_impresora()
                self.revisar_en_vuelo()
            except Exception:  # noqa: BLE001
                log.exception('No se pudo revisar la cola de CUPS')
            time.sleep(intervalo)


def pagina_de_prueba(agente):
    html = ('<!DOCTYPE html><html><head><meta charset="utf-8"><title>Prueba</title><style>@page { size: letter; margin: 12mm; }'
            'body { font-family: Arial, sans-serif; }</style></head><body><h1>Lottus · página de prueba</h1>'
            f'<p>Si ves esta hoja, el agente de impresión funciona. {time.strftime("%Y-%m-%d %H:%M")}</p></body></html>')
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / 'prueba.pdf'
        a_pdf(html, pdf, agente.chrome)
        imprimir(pdf, agente.config['cola'], 1, 'Prueba Lottus')
    print('Página de prueba enviada a', agente.config['cola'])


if __name__ == '__main__':
    salida = {'stream': sys.stdout}
    if ES_WINDOWS:  # sin consola (pythonw) ni launchd que guarde la salida; y que el equipo no se duerma
        from logging.handlers import RotatingFileHandler
        import ctypes
        CARPETA.mkdir(parents=True, exist_ok=True)
        salida = {'handlers': [RotatingFileHandler(CARPETA / 'agente.log', maxBytes=1_000_000, backupCount=2, encoding='utf-8')]}
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s', **salida)
    if '--probar' in sys.argv:
        pagina_de_prueba(Agente())
    else:
        Agente(simular='--simular' in sys.argv).correr()
