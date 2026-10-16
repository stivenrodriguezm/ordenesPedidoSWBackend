"""Servidor de desarrollo con el motor IA en la misma configuración de Django."""
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor

from django.contrib.staticfiles.management.commands.runserver import Command as Runserver
from django.core.management import call_command
from django.core.servers.basehttp import WSGIServer
from django.db import connections

log = logging.getLogger(__name__)


class ServidorConHilos(WSGIServer):
    """Atiende las peticiones con un grupo fijo de hilos.

    El servidor de Django crea un hilo por petición, y cada hilo abre su propia conexión
    a MySQL: el hosting limita a 500 conexiones por hora y se agotaban. Con hilos fijos,
    cada uno reutiliza su conexión según CONN_MAX_AGE. Al no ser ThreadingMixIn, Django
    responde «Connection: close» y ninguna conexión HTTP ociosa retiene un hilo.
    """
    hilos = 12

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._hilos = ThreadPoolExecutor(max_workers=self.hilos, thread_name_prefix='lottus-http')

    def process_request(self, request, client_address):
        self._hilos.submit(self._atender, request, client_address)

    def _atender(self, request, client_address):
        try:
            self.finish_request(request, client_address)
        except Exception:
            self.handle_error(request, client_address)
        finally:
            self.shutdown_request(request)

    def server_close(self):
        super().server_close()
        self._hilos.shutdown(wait=False)


class Command(Runserver):
    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument('--sin-motor-ia', action='store_true',
                            help='Usa un motor IA externo en vez de iniciarlo con el servidor local.')

    def run(self, **options):
        # El padre del autoreloader permanece vivo al recargar el servidor.
        # Solo él inicia el motor; --noreload también tiene un único propietario.
        if options.get('sin_motor_ia') or os.environ.get('RUN_MAIN') == 'true':
            return super().run(**options)
        detener = threading.Event()
        hilo = threading.Thread(target=self._motor, args=(detener,),
                                name='lottus-motor-local', daemon=True)
        hilo.start()
        self.stdout.write('Motor IA local supervisado junto al servidor; misma base de datos.')
        try:
            return super().run(**options)
        finally:
            detener.set()

    def inner_run(self, *args, **options):
        # El grupo de hilos reemplaza el hilo por petición (--nothreading lo desactiva).
        if options.get('use_threading'):
            options['use_threading'] = False
            self.server_cls = ServidorConHilos
        return super().inner_run(*args, **options)

    def _motor(self, detener):
        while not detener.is_set():
            try:
                call_command('ejecutar_automatizaciones_ia', continuo=True, intervalo=10,
                             trabajadores=2, detener=detener, stdout=self.stdout, stderr=self.stderr)
            except Exception:
                log.exception('El motor IA local se detuvo; se intentará iniciar nuevamente.')
            finally:
                connections.close_all()
            # Otro motor puede tener el bloqueo. Esperar permite tomarlo cuando
            # termine, sin duplicar procesos ni cerrar el servidor web.
            detener.wait(10)
