"""Confirmación de entrega con productos no entregados (P11-03, D04).

D04: la constancia de la entrega es la confirmación simple en el sistema, sin
firma ni foto. Confirma el transportador asignado o, si la llevó un
transportista externo, alguien con CAMBIAR_ESTADO_REMISION. Lo que no se
entregó se declara al confirmar, producto por producto: vuelve a bodega y
queda pendiente para otra remisión. Si nada se entregó, la remisión se
registra como devuelta (no como entregada con todo pendiente).
"""
from django.db.models import Sum
from django.db.models.functions import Coalesce
from rest_framework import serializers

from .models import NovedadEntrega, RemisionItemManual

MOTIVOS = {c[0] for c in NovedadEntrega.MOTIVO_CHOICES}


def _error(mensaje):
    return serializers.ValidationError({'no_entregados': mensaje})


def validar_no_entregados(remision, datos):
    """Lista recibida → lista de dicts listos para NovedadEntrega (sin guardar)."""
    if datos in (None, '', []):
        return []
    if not isinstance(datos, list):
        raise _error('Debe ser una lista de productos.')
    inventario = {i.pk: i for i in remision.inventario_items.all()}
    manuales = {m.pk: m for m in remision.items_manuales.all()}
    vistos, filas = set(), []
    for n, d in enumerate(datos, start=1):
        if not isinstance(d, dict):
            raise _error(f'Producto {n}: formato inválido.')
        motivo = d.get('motivo')
        if motivo not in MOTIVOS:
            raise _error(f'Producto {n}: elige por qué no se entregó.')
        detalle = str(d.get('detalle') or '').strip()[:1000]
        if motivo == 'otro' and not detalle:
            raise _error(f'Producto {n}: explica qué pasó.')
        if d.get('inventario'):
            pk = str(d['inventario'])
            if pk not in inventario:
                raise _error(f'El producto {pk} no está en esta remisión.')
            clave, fila = ('inventario', pk), {'inventario': inventario[pk], 'cantidad': 1}
        elif d.get('item_manual'):
            try:
                pk = int(d['item_manual'])
            except (TypeError, ValueError):
                raise _error(f'Producto {n}: identificador inválido.')
            if pk not in manuales:
                raise _error(f'El producto {pk} no está en esta remisión.')
            item = manuales[pk]
            try:
                cantidad = int(d.get('cantidad') or item.cantidad)
            except (TypeError, ValueError):
                raise _error(f'Producto {n}: cantidad inválida.')
            if not 1 <= cantidad <= item.cantidad:
                raise _error(f'Producto {n}: la cantidad no entregada debe estar entre 1 y {item.cantidad}.')
            clave, fila = ('item_manual', pk), {'item_manual': item, 'cantidad': cantidad}
        else:
            raise _error(f'Producto {n}: indica cuál producto no se entregó.')
        if clave in vistos:
            raise _error(f'Producto {n}: está repetido.')
        vistos.add(clave)
        filas.append({**fila, 'motivo': motivo, 'detalle': detalle})

    total = len(inventario) + sum(m.cantidad for m in manuales.values())
    if sum(f['cantidad'] for f in filas) >= total:
        raise _error('No se entregó ningún producto: registra la remisión como devuelta.')
    return filas


def guardar_no_entregados(remision, filas, usuario):
    NovedadEntrega.objects.bulk_create([
        NovedadEntrega(remision=remision, usuario=usuario if getattr(usuario, 'is_authenticated', False) else None, **f)
        for f in filas
    ])


def resumen(filas):
    etiquetas = dict(NovedadEntrega.MOTIVO_CHOICES)
    partes = []
    for f in filas:
        if 'inventario' in f:
            nombre = f['inventario'].pk
        else:
            m = f['item_manual']
            nombre = f"{f['cantidad']} × {m.referencia or m.descripcion[:40]}"
        partes.append(f"{nombre} ({etiquetas[f['motivo']].lower()}{': ' + f['detalle'] if f['detalle'] else ''})")
    return 'No entregado: ' + '; '.join(partes)


def comprometido_por_linea(detalle_ids, estados_vigentes):
    """{detalle_pedido_id: (cantidad comprometida o entregada, última remisión)}
    descontando lo que se declaró no entregado."""
    filas = (RemisionItemManual.objects
             .filter(detalle_pedido_id__in=list(detalle_ids), remision__estado__in=estados_vigentes)
             .annotate(no=Coalesce(Sum('novedades_entrega__cantidad'), 0))
             .values_list('detalle_pedido_id', 'remision_id', 'cantidad', 'no')
             .order_by('remision_id'))
    res = {}
    for det_id, rem_id, cantidad, no in filas:
        total, ultima = res.get(det_id, (0, None))
        neto = cantidad - no
        res[det_id] = (total + neto, rem_id if neto > 0 else ultima)
    return res
