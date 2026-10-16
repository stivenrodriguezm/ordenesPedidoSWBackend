"""Recepción de mercancía contra órdenes de pedido (P11-01, D04).

La mercancía casi siempre llega con su factura: registrar la factura ES la
recepción. Cada fila puede indicar la línea de la orden de pedido que atiende
(`detalle_pedido`); las unidades creadas quedan ligadas a esa línea y lo
pendiente se deriva (pedidas − unidades ligadas), sin contadores aparte que
puedan desincronizarse.

Concurrencia: las líneas tocadas se bloquean ANTES de crear o mover unidades y
el tope se verifica sobre el resultado final, dentro de la misma transacción.
Dos facturas que reciben la misma línea a la vez se serializan y la segunda
ve lo que dejó la primera.
"""
from django.db.models import Count, IntegerField, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.db import transaction
from rest_framework import serializers

from ordenes.models import DetallePedido, OrdenPedido

# Una orden en estos estados pasa sola a 'recibido' cuando llega todo.
ESTADOS_AUTORRECIBIBLES = ('pendiente', 'en_proceso', 'finalizado')


def contar_recibidas():
    """Unidades ligadas a la línea que siguen recibidas: una devuelta al proveedor
    deja la línea pendiente para la reposición (P11-02)."""
    return Count('unidades_recibidas', filter=Q(unidades_recibidas__isnull=False)
                 & ~Q(unidades_recibidas__disponibilidad='devuelto_proveedor'))


def sumar_rechazadas():
    """Unidades rechazadas al recibir (subconsulta: no multiplica el conteo de recibidas)."""
    from .models import RechazoRecepcion
    suma = (RechazoRecepcion.objects.filter(detalle_pedido=OuterRef('pk')).order_by()
            .values('detalle_pedido').annotate(s=Sum('cantidad')).values('s'))
    return Coalesce(Subquery(suma, output_field=IntegerField()), Value(0))


@transaction.atomic
def rechazar(linea_id, cantidad, motivo, usuario):
    """Registra mercancía no aceptada al recibir; la línea sigue pendiente (P11-01)."""
    from ordenes.servicios import ErrorNegocio, auditar
    from .models import RechazoRecepcion
    linea = bloquear_lineas([linea_id]).get(linea_id)
    if linea is None:
        raise ErrorNegocio('Línea de orden de pedido no encontrada.', 404)
    if linea.orden.estado == 'anulado':
        raise ErrorNegocio(f'La orden de pedido #{linea.orden_id} está anulada.', 409)
    motivo = str(motivo or '').strip()
    if not motivo:
        raise ErrorNegocio('Indica por qué se rechaza.', 400, 'motivo')
    try:
        cantidad = int(cantidad)
    except (TypeError, ValueError):
        raise ErrorNegocio('Cantidad inválida.', 400, 'cantidad')
    pendiente = linea.cantidad - recibidas_de(linea)
    if not 1 <= cantidad <= max(pendiente, 0):
        raise ErrorNegocio(f'La línea tiene {max(pendiente, 0)} pendientes de recibir: se pueden rechazar entre 1 y esa cantidad.', 400, 'cantidad')
    rechazo = RechazoRecepcion.objects.create(detalle_pedido=linea, cantidad=cantidad, motivo=motivo[:1000],
                                              usuario=usuario if getattr(usuario, 'is_authenticated', False) else None)
    auditar(usuario, 'recepcion.rechazo', linea, {'cantidad': cantidad, 'motivo': motivo[:200], 'orden': linea.orden_id})
    return rechazo


def recibidas_de(linea):
    return linea.unidades_recibidas.exclude(disponibilidad='devuelto_proveedor').count()


def bloquear_lineas(ids):
    """Bloquea las líneas (orden estable por PK) y devuelve {id: DetallePedido}."""
    ids = sorted({i for i in ids if i})
    if not ids:
        return {}
    return {d.pk: d for d in DetallePedido.objects.select_for_update().select_related('orden').filter(pk__in=ids).order_by('pk')}


def lineas_de_unidades(factura):
    """Líneas a las que hoy están ligadas las unidades de la factura."""
    if factura is None or factura.pk is None:
        return set()
    return set(factura.items_inventario.exclude(detalle_pedido=None).values_list('detalle_pedido_id', flat=True))


def verificar_topes(lineas):
    """Rechaza la operación si alguna línea quedó con más unidades que las pedidas."""
    if not lineas:
        return
    conteo = dict(DetallePedido.objects.filter(pk__in=list(lineas)).annotate(
        n=contar_recibidas()).values_list('pk', 'n'))
    for pk, linea in sorted(lineas.items()):
        recibidas = conteo.get(pk, 0)
        if recibidas > linea.cantidad:
            raise serializers.ValidationError({'productos': (
                f'La línea de la orden de pedido #{linea.orden_id} pide {linea.cantidad} '
                f'y quedarían {recibidas} unidades recibidas. Revisa la cantidad o la línea elegida.'
            )})


def actualizar_ordenes(lineas, usuario=None):
    """Pasa a 'recibido' las órdenes cuyas líneas quedaron completas. No baja
    una orden marcada 'recibido' a mano (puede haber llegado sin factura)."""
    from ordenes.servicios import auditar
    ordenes = {l.orden_id for l in lineas.values()}
    if not ordenes:
        return
    candidatas = OrdenPedido.objects.select_for_update().filter(pk__in=ordenes, estado__in=ESTADOS_AUTORRECIBIBLES)
    for orden in candidatas.order_by('pk'):
        pendientes = [d for d in orden.detalles.annotate(n=contar_recibidas()) if d.n < d.cantidad]
        if not pendientes:
            anterior = orden.estado
            orden.estado = 'recibido'
            orden.save(update_fields=['estado'])
            auditar(usuario, 'orden_pedido.recibida', orden,
                    {'antes': anterior, 'motivo': 'Todas sus líneas quedaron recibidas por factura'})


def pendientes_por_linea(qs):
    """Anota `recibidas` en un queryset de DetallePedido."""
    return qs.annotate(recibidas=contar_recibidas())
