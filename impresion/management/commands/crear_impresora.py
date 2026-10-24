"""Registra una impresora de la oficina (o renueva su token) y guarda el token en el
archivo de configuración del agente, sin mostrarlo en pantalla.

    manage.py crear_impresora --nombre "Ricoh SP 3710SF" --ubicacion "Oficina principal" \
        --config ~/Library/Application\\ Support/LottusImpresion/config.json \
        --servidor local --api http://127.0.0.1:8000/api --cola RICOH_SP_3710SF__50f7b8_
    manage.py crear_impresora --renovar 1 --config … --servidor … --api …
"""
import json
import os
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from impresion import servicios as s
from impresion.models import Impresora


class Command(BaseCommand):
    help = 'Crea una impresora remota (o renueva su token) y lo guarda en la configuración del agente.'

    def add_arguments(self, parser):
        parser.add_argument('--nombre')
        parser.add_argument('--ubicacion', default='')
        parser.add_argument('--renovar', type=int, help='Id de la impresora a la que se le cambia el token')
        parser.add_argument('--config', required=True, help='config.json del agente (se crea con permisos 600)')
        parser.add_argument('--servidor', required=True, help='Nombre del servidor en la configuración (local, pruebas, produccion…)')
        parser.add_argument('--api', required=True, help='URL base de la API, p. ej. https://api.muebleslottus.com/api')
        parser.add_argument('--cola', help='Nombre de la cola CUPS de la impresora (lpstat -p)')

    def handle(self, *args, **o):
        token, h = s.nuevo_token()
        if o['renovar']:
            imp = Impresora.objects.filter(pk=o['renovar']).first()
            if imp is None:
                raise CommandError('No existe esa impresora.')
            s.olvidar_token(imp.token_hash)
            imp.token_hash = h
            imp.save(update_fields=['token_hash'])
        else:
            if not o['nombre']:
                raise CommandError('Falta --nombre.')
            imp = Impresora.objects.create(nombre=o['nombre'], ubicacion=o['ubicacion'], token_hash=h)

        ruta = Path(o['config']).expanduser()
        ruta.parent.mkdir(parents=True, exist_ok=True)
        config = json.loads(ruta.read_text()) if ruta.exists() else {}
        if o['cola']:
            config['cola'] = o['cola']
        servidores = [x for x in config.get('servidores', []) if x.get('nombre') != o['servidor']]
        servidores.append({'nombre': o['servidor'], 'api': o['api'].rstrip('/'), 'token': token, 'impresora': imp.pk})
        config['servidores'] = servidores
        viejo = os.umask(0o077)
        try:
            tmp = ruta.with_suffix('.tmp')
            tmp.write_text(json.dumps(config, indent=2, ensure_ascii=False))
            os.chmod(tmp, 0o600)
            tmp.replace(ruta)
        finally:
            os.umask(viejo)
        self.stdout.write(f'Impresora {imp.pk} «{imp}» lista; token guardado en {ruta} (servidor «{o["servidor"]}»).')
