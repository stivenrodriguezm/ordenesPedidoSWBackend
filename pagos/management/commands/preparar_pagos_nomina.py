"""Ejecutar a diario por scheduler o desde el motor persistente del ERP."""
import logging
import time
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.utils import timezone
from pagos.models import ProgramacionNomina
from pagos.servicios import preparar_programada


class Command(BaseCommand):
    help = 'Prepara, una sola vez por mes, el borrador de pagos de nómina programado.'

    def add_arguments(self, parser):
        parser.add_argument('--continuo', action='store_true')

    def handle(self, *args, **options):
        while True:
            try:
                close_old_connections()
                ProgramacionNomina.objects.filter(pk=1).update(latido_motor=timezone.now())
                lote = preparar_programada()
                if not options['continuo']:
                    self.stdout.write(f'Lote de nómina: {lote.id}' if lote else 'No hay nómina programada pendiente.')
            except Exception:
                logging.getLogger(__name__).exception('Falló la preparación mensual de nómina')
                try:
                    ProgramacionNomina.objects.filter(pk=1).update(ultimo_error='No se pudo preparar la nómina. Revisa empleados, origen y permisos.')
                except Exception:
                    logging.getLogger(__name__).warning('El programador reintentará la conexión en el siguiente ciclo.')
                if not options['continuo']:
                    raise
            finally:
                close_old_connections()
            if not options['continuo']:
                break
            time.sleep(60)
