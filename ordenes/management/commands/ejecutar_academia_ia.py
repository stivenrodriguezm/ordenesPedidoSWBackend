import time
import threading
import fcntl
from pathlib import Path
from django.conf import settings
from django.core.cache import cache
from django.core.management.base import BaseCommand
from django.db import close_old_connections, InterfaceError, OperationalError
from django.utils import timezone
from ordenes.asistente.academia import ejecutar_un_paso


class Command(BaseCommand):
    help = 'Procesa cursos de la academia por pasos. --continuo mantiene el motor activo.'

    def add_arguments(self, parser):
        parser.add_argument('--continuo', action='store_true')

    def handle(self, *args, **options):
        path = Path(settings.BASE_DIR) / '.cache' / 'academia-worker.lock'
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = path.open('a')
        try:
            fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.stderr.write('Ya hay un motor de cursos activo en este servidor.')
            return
        # El conector puede tardar hasta 180 s; el latido no depende de ese paso.
        def latido():
            while True:
                cache.set('academia-motor', timezone.now().timestamp(), 60)
                time.sleep(10)
        if options['continuo']:
            threading.Thread(target=latido, daemon=True).start()
        while True:
            cache.set('academia-motor', timezone.now().timestamp(), 240)
            close_old_connections()
            try:
                trabajo = ejecutar_un_paso()
            except (OperationalError, InterfaceError):
                self.stderr.write('La base de datos no está disponible; el motor volverá a intentar sin repetir operaciones de Google.')
                if not options['continuo']:
                    raise
                time.sleep(15)
                trabajo = False
            finally:
                close_old_connections()
            cache.set('academia-motor', timezone.now().timestamp(), 240)
            if not options['continuo']:
                break
            time.sleep(2 if trabajo else 5)
