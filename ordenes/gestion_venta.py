"""Gestión de la venta (pedido del usuario, 2026-10-08).

El asesor finaliza la gestión cuando ya pidió todo lo que había que pedir: todos los
productos registrados con su precio de lista, pedidos al proveedor (o tomados de
bodega) y, si llevan tela comprada aparte, la tela pedida. Después solo queda esperar
que llegue y entregar. Se guarda en `Venta.estado_pedidos` (antes la columna
"Pedidos"), así las ventas que ya estaban marcadas como "Pedido" quedan finalizadas.

Estados que ve el usuario: pendiente, atrasada (sin finalizar después de
`GESTION_DIAS_LIMITE` días desde la venta) y finalizada.
"""
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import business_time
from .models import LineaVenta, Venta
from .servicios import ErrorNegocio, auditar

DIAS_LIMITE = int(getattr(settings, 'GESTION_DIAS_LIMITE', 3))


def estado_gestion(venta, hoy=None):
    if venta.estado == Venta.ESTADO_ANULADA:
        return None
    if venta.estado_pedidos or venta.estado == Venta.ESTADO_ENTREGADO:
        return 'finalizada'
    hoy = hoy or business_time.hoy()
    if venta.fecha_venta and hoy - venta.fecha_venta > timedelta(days=DIAS_LIMITE):
        return 'atrasada'
    return 'pendiente'


def tela_modo(linea):
    """El modo guardado o, si el producto del catálogo no usa tela, 'no aplica'."""
    if linea.tela_modo:
        return linea.tela_modo
    if linea.variante_id and not (linea.variante.metraje_tela or linea.variante.decimetraje_cuero):
        return LineaVenta.TELA_NO_APLICA
    return LineaVenta.TELA_SIN_DEFINIR


def pendientes(lineas):
    """Lo que falta para finalizar, a partir de las líneas ya representadas."""
    if not any(l.get('tipo', LineaVenta.TIPO_PRODUCTO) == LineaVenta.TIPO_PRODUCTO for l in lineas):
        return ['Agrega los productos de la venta.']
    faltan = []
    for n, l in enumerate(lineas, 1):
        if l.get('tipo', LineaVenta.TIPO_PRODUCTO) != LineaVenta.TIPO_PRODUCTO:
            continue  # servicios y ajustes: no se piden ni llevan tela
        nombre = f'Producto {n} ({l["producto_nombre"]})'
        if not l.get('precio_lista_unitario'):
            faltan.append(f'{nombre}: falta el precio de lista.')
        if l['por_pedir'] > 0:
            faltan.append(f'{nombre}: falta pedirlo al proveedor ({l["por_pedir"]} u.).')
        modo = l['tela_modo']
        material = 'el cuero' if l['tela_material'] == 'cuero' else 'la tela'
        if not modo:
            faltan.append(f'{nombre}: indica si lleva tela (no lleva, la incluye el proveedor o se compra aparte).')
        elif modo != LineaVenta.TELA_NO_APLICA and not l['tela_referencia'].strip():
            faltan.append(f'{nombre}: indica la referencia y el color de {material} con que se vendió.')
        if modo == LineaVenta.TELA_APARTE:
            if not l['tela_proveedor']:
                faltan.append(f'{nombre}: elige el proveedor de {material}.')
            elif not l['tela_pedidos']:
                faltan.append(f'{nombre}: falta pedir {material}.')
    return faltan


def resumen(venta, lineas):
    return {'estado': estado_gestion(venta), 'dias_limite': DIAS_LIMITE, 'pendientes': pendientes(lineas),
            'finalizada_en': venta.gestion_finalizada_en.isoformat() if venta.gestion_finalizada_en else None,
            'finalizada_por': (venta.gestion_finalizada_por.get_full_name() or venta.gestion_finalizada_por.username)
            if venta.gestion_finalizada_por_id else None}


def reabrir_si_falta(request, venta, datos):
    """Si después de finalizar cambian los productos y algo queda pendiente, la gestión
    vuelve a pendiente sola (nunca se queda "finalizada" con cosas por pedir)."""
    if venta.estado_pedidos and datos['gestion']['pendientes']:
        venta.estado_pedidos = False
        venta.gestion_finalizada_en = None
        venta.gestion_finalizada_por = None
        venta.save(update_fields=['estado_pedidos', 'gestion_finalizada_en', 'gestion_finalizada_por'])
        auditar(request.user, 'venta.gestion_reabierta', venta, {'motivo': 'cambio de productos', 'pendientes': datos['gestion']['pendientes']})
        datos['gestion'] = resumen(venta, datos['lineas'])
    return datos


class GestionEntrada(serializers.Serializer):
    revision = serializers.IntegerField(min_value=0)
    accion = serializers.ChoiceField(choices=['finalizar', 'reabrir'])


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def gestion(request, venta_id):
    from .productos_venta import exigir, visible
    visible(request, venta_id)
    exigir(request, 'VER_PRECIOS_VENTA')
    exigir(request, 'EDITAR_PRODUCTOS_VENTA', 'EDITAR_VENTA', 'EDITAR_ESTADO_PEDIDOS_VENTA')
    return cambiar_gestion(request, venta_id)


@transaction.atomic
def cambiar_gestion(request, venta_id):
    from .productos_venta import bloquear, representar
    s = GestionEntrada(data=request.data)
    s.is_valid(raise_exception=True)
    venta = bloquear(venta_id, s.validated_data['revision'])
    datos = representar(request, venta)
    if s.validated_data['accion'] == 'finalizar':
        faltan = datos['gestion']['pendientes']
        if faltan:
            raise ErrorNegocio('Aún no se puede finalizar: ' + ' '.join(faltan), 409)
        venta.estado_pedidos = True
        venta.gestion_finalizada_en = timezone.now()
        venta.gestion_finalizada_por = request.user
    else:
        venta.estado_pedidos = False
        venta.gestion_finalizada_en = None
        venta.gestion_finalizada_por = None
    venta.save(update_fields=['estado_pedidos', 'gestion_finalizada_en', 'gestion_finalizada_por'])
    auditar(request.user, f'venta.gestion_{s.validated_data["accion"]}', venta, {'revision': venta.revision_productos})
    datos['gestion'] = resumen(venta, datos['lineas'])
    return Response(datos)


def texto_remision(linea):
    """Lo que ve el cliente en la remisión. El texto para el cliente es opcional
    (2026-10-15): sin él va el nombre del producto (con su detalle)."""
    if not linea:
        return ''
    nombre = f'{linea.producto_nombre} · {linea.variante_nombre}' if linea.variante_nombre else linea.producto_nombre
    return linea.texto_cliente or linea.especificaciones or nombre


def texto_tela(linea):
    """Tapizado de un producto vendido para la remisión: material, referencia y color.
    Sin proveedor, precio ni metraje (para el cliente la tela ya está incluida)."""
    if not linea or linea.tela_modo not in ('incluida', 'aparte') or not (linea.tela_referencia or linea.tela_color):
        return ''
    material = linea.tela_material or ('cuero' if linea.grupo_catalogo_id and linea.grupo_catalogo.tipo == 'cuero' else 'tela')
    partes = [f'{material.capitalize()} {linea.tela_referencia}'.strip()]
    if linea.tela_color:
        partes.append(f'color {linea.tela_color}')
    return ' · '.join(partes)
