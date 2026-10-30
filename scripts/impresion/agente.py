#!/usr/bin/env python3
"""Agente de impresión de la oficina principal (2026-10-24).

Corre en la computadora que tiene instalada la impresora. Cada pocos segundos le pregunta
a cada servidor configurado si hay documentos en cola; si hay, lo convierte a PDF con
Google Chrome (sin JavaScript) y lo manda a la cola CUPS con `lp`. La oficina no abre
puertos: solo hace peticiones HTTPS de salida. Solo usa la biblioteca estándar.

Configuración (la crea `manage.py crear_impresora`, permisos 600):
    ~/Library/Application Support/LottusImpresion/config.json
    {"cola": "RICOH_…", "servidores": [{"nombre": "…", "api": "https://…/api", "token": "…"}]}
Opcionales: "intervalo" (segundos, 3), "chrome" (ruta), "simular" (true = guarda el PDF
en la carpeta «simulados» en vez de imprimir).

Uso:  python3 agente.py            (lo deja corriendo el LaunchAgent com.lottus.impresion)
      python3 agente.py --simular  (no imprime; deja los PDF en la carpeta «simulados»)
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

CARPETA = Path.home() / 'Library' / 'Application Support' / 'LottusImpresion'
CONFIG = CARPETA / 'config.json'
CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
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
    config = json.loads(CONFIG.read_text())
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
        ], check=True, capture_output=True, timeout=90)
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


class Agente:
    def __init__(self, simular=False):
        self.config = cargar_config()
        self.simular = simular or bool(self.config.get('simular'))
        self.chrome = self.config.get('chrome') or CHROME
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


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s', stream=sys.stdout)
    Agente(simular='--simular' in sys.argv).correr()
