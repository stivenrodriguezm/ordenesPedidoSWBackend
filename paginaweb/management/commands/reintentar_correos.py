"""Reintenta los correos pendientes o fallidos de la bandeja (P07-06).

Programar en cron, p. ej. cada 10 minutos:
    */10 * * * * cd /ruta/backend && ./venv/bin/python manage.py reintentar_correos
"""
from django.core.management.base import BaseCommand

from paginaweb.emails import enviar_correo
from paginaweb.models import CorreoSaliente


class Command(BaseCommand):
    help = 'Reintenta correos pendientes o fallidos (máximo CorreoSaliente.MAX_INTENTOS intentos).'

    def handle(self, *args, **options):
        ids = list(CorreoSaliente.objects.filter(
            estado__in=['pendiente', 'fallido'], intentos__lt=CorreoSaliente.MAX_INTENTOS,
        ).values_list('pk', flat=True)[:200])
        resultados = {'enviado': 0, 'fallido': 0}
        for pk in ids:
            correo = enviar_correo(pk)
            if correo:
                resultados[correo.estado] = resultados.get(correo.estado, 0) + 1
        self.stdout.write(f"Reintentados {len(ids)}: {resultados}")
