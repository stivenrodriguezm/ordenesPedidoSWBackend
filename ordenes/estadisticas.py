"""Reparto de ventas compartidas en métricas personales (P05-01, H13).

Regla de negocio: cada participante único (vendedor principal + compartidos,
sin repetir) recibe Total / N en sus estadísticas personales; listados,
detalle y totales de empresa conservan el 100 %. El reparto se redondea a 2
decimales (ROUND_HALF_UP) por persona; solo afecta métricas, nunca dinero.
"""
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

CENTAVO = Decimal('0.01')


def participantes(venta):
    """Ids únicos de quienes participan en la venta. Requiere (idealmente)
    prefetch de vendedores_compartidos; NO usar una relación ya filtrada."""
    ids = {venta.vendedor_id}
    ids.update(v.id for v in venta.vendedores_compartidos.all())
    ids.discard(None)
    return ids


def parte_de(venta, persona_id):
    ids = participantes(venta)
    if persona_id not in ids:
        return Decimal('0')
    return (Decimal(venta.valor_total) / len(ids)).quantize(CENTAVO, rounding=ROUND_HALF_UP)


def _con_participantes(ventas_qs):
    # Se recarga desde la tabla base para que el prefetch traiga TODOS los
    # compartidos aunque el queryset recibido filtre por la relación.
    from .models import Venta
    ids = list(ventas_qs.values_list('id', flat=True))
    return Venta.objects.filter(id__in=ids).prefetch_related('vendedores_compartidos')


def total_personal(ventas_qs, persona):
    persona_id = getattr(persona, 'id', persona)
    return sum((parte_de(v, persona_id) for v in _con_participantes(ventas_qs)), Decimal('0'))


def totales_personales_por_mes(ventas_qs, persona):
    persona_id = getattr(persona, 'id', persona)
    totales = defaultdict(lambda: Decimal('0'))
    for v in _con_participantes(ventas_qs):
        totales[(v.fecha_venta.year, v.fecha_venta.month)] += parte_de(v, persona_id)
    return dict(totales)
