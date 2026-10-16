"""Movimientos de inventario trazables (P11-02).

Toda escritura de disponibilidad, zona, estado físico o venta de una unidad
pasa por aquí y deja un MovimientoInventario con antes/después, actor, motivo
y documento. Los estados que manejan los procesos (remisión, devolución al
proveedor) no se cambian a mano: así una unidad en tránsito no vuelve a estar
disponible por un simple cambio de etiqueta.
"""
from rest_framework import serializers

from .models import HistorialTraslado, Inventario, MovimientoInventario

CAMPOS = {'disponibilidad': 'disponibilidad', 'zona': 'zona_id', 'estado_fisico': 'estado_fisico', 'venta': 'venta_id'}
# Disponibilidades que solo asigna un proceso (remisión o devolución al proveedor).
SOLO_POR_PROCESO = {'por_despachar', 'despachado', 'devuelto_proveedor'}


def foto(item):
    return {c: getattr(item, attr) for c, attr in CAMPOS.items()}


def _usuario(u):
    return u if getattr(u, 'is_authenticated', False) else None


def _diferencias(antes, despues):
    a = {c: antes[c] for c in CAMPOS if antes.get(c) != despues.get(c)}
    return a, {c: despues[c] for c in a}


def registrar(item, antes, tipo, usuario=None, motivo='', documento='', siempre=False):
    """Movimiento con lo que cambió respecto de `antes` (foto previa)."""
    a, d = _diferencias(antes, foto(item))
    if not d and not siempre:
        return None
    return MovimientoInventario.objects.create(item=item, tipo=tipo, usuario=_usuario(usuario), antes=a, despues=d,
                                               motivo=motivo or '', documento=documento or '')


def ingreso(item, usuario=None, documento='', motivo=''):
    return MovimientoInventario.objects.create(item=item, tipo='ingreso', usuario=_usuario(usuario), antes={},
                                               despues=foto(item), motivo=motivo, documento=documento)


def aplicar(items, tipo, usuario=None, motivo='', documento='', **cambios):
    """Aplica los mismos `cambios` (disponibilidad=…, zona=Zona|None, …) a las
    unidades y registra un movimiento por cada una que realmente cambió. Un
    cambio de zona también queda en HistorialTraslado (lo usa la pantalla)."""
    valores = {CAMPOS[c]: (v.pk if hasattr(v, 'pk') else v) for c, v in cambios.items()}
    movidas, filas, traslados = [], [], []
    for item in items:
        antes = foto(item)
        for attr, v in valores.items():
            setattr(item, attr, v)
        a, d = _diferencias(antes, foto(item))
        if not d:
            continue
        movidas.append(item.pk)
        filas.append(MovimientoInventario(item=item, tipo=tipo, usuario=_usuario(usuario), antes=a, despues=d,
                                          motivo=motivo or '', documento=documento or ''))
        if 'zona' in d:
            traslados.append(HistorialTraslado(item_inventario=item, zona_origen_id=a['zona'], zona_destino_id=d['zona'],
                                               usuario=_usuario(usuario), observacion=motivo or tipo))
    if movidas:
        Inventario.objects.filter(pk__in=movidas).update(**valores)
        MovimientoInventario.objects.bulk_create(filas)
        HistorialTraslado.objects.bulk_create(traslados)
    return movidas


def validar_edicion_manual(item, nueva_disponibilidad, nueva_venta_id, en_remision_activa):
    """Reglas de la edición directa de una unidad (pantalla de inventario o factura)."""
    cambia_disp = nueva_disponibilidad is not None and nueva_disponibilidad != item.disponibilidad
    cambia_venta = nueva_venta_id is not False and nueva_venta_id != item.venta_id
    if en_remision_activa and (cambia_disp or cambia_venta):
        raise serializers.ValidationError({'disponibilidad': (
            f'El producto {item.pk} va en una remisión activa: su disponibilidad y su venta '
            'cambian con la remisión (despachar, entregar, devolver o anular).')})
    if cambia_disp and nueva_disponibilidad in SOLO_POR_PROCESO:
        raise serializers.ValidationError({'disponibilidad': (
            'Esa disponibilidad la asigna su proceso (remisión o devolución al proveedor); no se pone a mano.')})
    if cambia_disp and item.disponibilidad == 'devuelto_proveedor':
        raise serializers.ValidationError({'disponibilidad': (
            f'El producto {item.pk} fue devuelto al proveedor. Si llega la reposición, regístrala en su factura.')})
