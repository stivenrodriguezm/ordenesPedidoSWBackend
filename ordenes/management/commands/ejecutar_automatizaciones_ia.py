"""Motor persistente. En local: LOTTUS_LOCAL_TEST_DB=1 ... --continuo."""
import logging
import time
import fcntl
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from django.core.management.base import BaseCommand
from django.conf import settings
from django.db import close_old_connections, connections

from ordenes.asistente import automatizaciones as tareas
from ordenes.asistente import agente
from ordenes import coordinacion, vida_oficina
from ordenes.models import EjecucionAutomatizacionIA, InformeAreas, TrabajoAgenteIA

log = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Ejecuta automatizaciones de IA pendientes. --continuo mantiene el motor activo.'
    stealth_options = ('detener',)

    def add_arguments(self, parser):
        parser.add_argument('--continuo', action='store_true')
        parser.add_argument('--intervalo', type=int, default=10)
        parser.add_argument('--trabajadores', type=int, default=2)
        parser.add_argument('--limite', type=int, default=20)

    def handle(self, *args, **opciones):
        path=Path(settings.BASE_DIR)/'.cache'/'oficina-worker.lock'
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('a') as lock:
            try:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:
                self.stderr.write('Ya hay un motor de automatizaciones activo en este servidor.')
                return
            try:
                self._atender(opciones)
            finally:
                connections.close_all()

    def _atender(self, opciones):
        detener = opciones.get('detener')
        intervalo = max(2, min(60, opciones['intervalo']))
        trabajadores = max(1, min(4, opciones['trabajadores']))
        limite = max(1, min(50, opciones['limite']))
        if not opciones['continuo']:
            from pagos.motor import impulsar as impulsar_pagos
            impulsar_pagos()
            tareas.latido()
            tareas.recuperar_interrumpidas()
            tareas.encolar_vencidas(limite)
            coordinacion.recuperar_interrumpidos()
            coordinacion.encolar_programado()
            vida_oficina.impulsar()
            agente.recuperar_interrumpidos()
            for pk in TrabajoAgenteIA.objects.filter(estado='pendiente',continuacion_de__isnull=True).values_list('pk',flat=True):
                agente.procesar(pk)
            for pk in InformeAreas.objects.filter(estado='pendiente').values_list('pk',flat=True):
                coordinacion.ejecutar(pk)
            ids = list(EjecucionAutomatizacionIA.objects.filter(estado='pendiente').order_by('creada','id').values_list('pk',flat=True)[:limite])
            for pk in ids:
                tareas.latido()
                tareas.ejecutar(pk)
            self.stdout.write(f'Ejecuciones atendidas: {len(ids)}')
            return
        self.stdout.write('Motor IA iniciado; resultados privados y horarios de Bogotá.')
        futuros = {}
        with ThreadPoolExecutor(max_workers=trabajadores, thread_name_prefix='lottus-ia') as ejecutor:
            try:
                while detener is None or not detener.is_set():
                    try:
                        close_old_connections()
                        tareas.latido()
                        from pagos.motor import impulsar as impulsar_pagos
                        impulsar_pagos()
                        tareas.recuperar_interrumpidas()
                        tareas.encolar_vencidas(limite)
                        coordinacion.recuperar_interrumpidos()
                        coordinacion.encolar_programado()
                        vida_oficina.impulsar()
                        agente.recuperar_interrumpidos()
                        futuros = {pk:f for pk,f in futuros.items() if not f.done()}
                        capacidad = trabajadores-len(futuros)
                        if capacidad:
                            trabajos=list(TrabajoAgenteIA.objects.filter(estado='pendiente',continuacion_de__isnull=True).order_by('creado','id').values_list('pk',flat=True)[:capacidad])
                            for pk in trabajos:
                                key=('agente',pk)
                                if key not in futuros and capacidad:
                                    futuros[key]=ejecutor.submit(agente.procesar,pk);capacidad-=1
                            informes=list(InformeAreas.objects.filter(estado='pendiente').values_list('pk',flat=True)[:1])
                            for pk in informes:
                                key=('informe',pk)
                                if key not in futuros and capacidad:
                                    futuros[key]=ejecutor.submit(coordinacion.ejecutar,pk);capacidad-=1
                            ids = list(EjecucionAutomatizacionIA.objects.filter(estado='pendiente').exclude(pk__in=[pk for tipo,pk in futuros if tipo=='privada']).order_by('creada','id').values_list('pk',flat=True)[:capacidad])
                            for pk in ids:
                                futuros[('privada',pk)] = ejecutor.submit(tareas.ejecutar, pk)
                    except Exception:
                        log.exception('No se pudo completar un ciclo del motor IA')
                    finally:
                        # El motor no atraviesa el cierre de conexiones HTTP de Django.
                        # Cerrar siempre abría una conexión nueva cada ciclo (~360/hora) y
                        # agotaba el límite del hosting (500/hora). Se cierra solo la que
                        # falló o superó CONN_MAX_AGE; CONN_HEALTH_CHECKS descarta la que
                        # el hosting haya cerrado mientras el equipo esperaba.
                        close_old_connections()
                    if detener is not None:
                        detener.wait(intervalo)
                    else:
                        time.sleep(intervalo)
            except KeyboardInterrupt:
                self.stdout.write('Motor IA detenido. Las ejecuciones en curso terminan antes de salir.')
