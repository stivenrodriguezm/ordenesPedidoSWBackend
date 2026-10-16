"""Identificador visible de ítems de inventario (P04-05, H33).

Antes: prefijo + número aleatorio 1000–9999 (9000 valores, colisiones
crecientes y bucle infinito al agotarse). Ahora: prefijo + consecutivo
bloqueado por prefijo, que continúa después del mayor número existente. Los
códigos ya impresos (QR) no cambian y pueden pasar de 4 a 5+ dígitos.
"""
import re

from ordenes.models import ConsecutivoDocumento

from .models import Inventario

INICIO = 1000
_MAX_INTENTOS = 1000


def _mayor_existente(prefijo):
    patron = re.compile(rf'^{re.escape(prefijo)}(\d+)$')
    mayor = 0
    for pk in Inventario.objects.filter(id_referencia__startswith=prefijo).values_list('id_referencia', flat=True).iterator():
        m = patron.match(pk)
        if m:
            mayor = max(mayor, int(m.group(1)))
    return mayor


def siguiente_id_inventario(prefijo):
    """Debe llamarse dentro de una transacción (bloquea el contador del prefijo)."""
    serie = f'inventario:{prefijo}'
    contador = ConsecutivoDocumento.objects.select_for_update().filter(serie=serie).first()
    if contador is None:
        ConsecutivoDocumento.objects.get_or_create(serie=serie, defaults={'ultimo': max(_mayor_existente(prefijo), INICIO - 1)})
        contador = ConsecutivoDocumento.objects.select_for_update().get(serie=serie)
    numero = max(contador.ultimo + 1, INICIO)
    for _ in range(_MAX_INTENTOS):
        candidato = f'{prefijo}{numero}'
        if not Inventario.objects.filter(pk=candidato).exists():
            contador.ultimo = numero
            contador.save(update_fields=['ultimo'])
            return candidato
        numero += 1  # código heredado aleatorio ya ocupado: se salta
    raise RuntimeError(f'No se encontró un código libre para el prefijo {prefijo}')
