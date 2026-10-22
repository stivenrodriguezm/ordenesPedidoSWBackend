"""Un ciclo por minuto, reutilizable desde el motor local o un worker externo."""
import logging
import time
from django.utils import timezone
from .models import ProgramacionNomina
from .servicios import preparar_programada

_ultimo = 0


def impulsar():
    global _ultimo
    ahora = time.monotonic()
    if ahora - _ultimo < 60:
        return
    _ultimo = ahora
    try:
        ProgramacionNomina.objects.filter(pk=1).update(latido_motor=timezone.now())
        preparar_programada()
    except Exception:
        logging.getLogger(__name__).exception('No se pudo preparar la nómina programada')
        try:
            ProgramacionNomina.objects.filter(pk=1).update(ultimo_error='No se pudo preparar la nómina. Revisa los empleados y la cuenta de origen.')
        except Exception:
            logging.getLogger(__name__).warning('No se pudo registrar el estado del programador de pagos')
