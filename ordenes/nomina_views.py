"""API de Nómina (D12a). VER_NOMINA consulta; GESTIONAR_NOMINA crea, edita y cierra."""
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response

from . import business_time, nomina
from .gestion_venta import texto_tela
from .models import AsesorCierre, AsesorNomina, CierreNomina, CustomUser, LineaNomina, OrdenPedido, PagoReciboCaja, PedidoTela
from .permissions import check_feature_permission
from .servicios import ErrorNegocio, auditar


class PermisoNomina(BasePermission):
    """GET con VER_NOMINA; cualquier cambio con GESTIONAR_NOMINA."""
    def has_permission(self, request, view):
        codigo = 'VER_NOMINA' if request.method == 'GET' else 'GESTIONAR_NOMINA'
        return check_feature_permission(codigo)().has_permission(request, view)


PERMISOS = [IsAuthenticated, PermisoNomina]


def _nombre(u):
    return (f'{u.first_name} {u.last_name}'.strip() or u.username) if u else None


def _num(v):
    return None if v is None else str(v)


def _linea(l):
    v = l.venta
    return {
        'id': l.id, 'tipo': l.tipo, 'venta': l.venta_id, 'cliente': l.descripcion,
        'fecha_venta': v.fecha_venta if v else None, 'estado_venta': l.estado_venta,
        'valor_venta': _num(l.valor_venta), 'participantes': l.participantes, 'base': _num(nomina.base_de(l)) if l.tipo != 'ajuste' else None,
        'origen_precio': l.origen_precio, 'revision_productos': l.revision_productos,
        'precio_lista': _num(l.precio_lista), 'descuento_pct': _num(l.descuento_pct), 'porcentaje': _num(l.porcentaje),
        'valor': _num(l.valor), 'abono_pct': _num(l.abono_pct), 'pagar': l.pagar, 'motivo_pendiente': l.motivo_pendiente,
        'editada': l.editada, 'nota': l.nota,
        'causada_en': {'id': l.causada_en_id, 'nombre': l.causada_en.nombre} if l.causada_en_id else None,
    }


def _cierre(cierre, detalle=True):
    cfg = nomina.config()
    datos = {
        'id': cierre.id, 'nombre': cierre.nombre, 'fecha_inicio': cierre.fecha_inicio, 'fecha_fin': cierre.fecha_fin,
        'estado': cierre.estado, 'observacion': cierre.observacion, 'creado_por': _nombre(cierre.creado_por),
        'cerrado_por': _nombre(cierre.cerrado_por), 'cerrado_en': cierre.cerrado_en,
        'tabla_comision': cierre.tabla_comision, 'abono_minimo_pct': _num(cierre.abono_minimo_pct),
        'bonificacion_pct': _num(cierre.bonificacion_pct),
        'dia_pago_basico': cfg.dia_pago_basico, 'pago_nomina': cfg.pago_nomina,
    }
    filas = list(cierre.asesores.all())
    totales = {f.id: nomina.totales(f) for f in filas}
    claves = ('salario_basico', 'comisiones', 'bonificaciones', 'ajustes', 'total_nomina',
              'comisiones_pendientes', 'bonificaciones_pendientes', 'ventas_con_lista', 'lista_total')
    suma = {k: sum((totales[f.id][k] for f in filas), Decimal('0')) for k in claves}
    datos['resumen'] = {k: str(v) for k, v in suma.items()}
    datos['resumen']['ventas_periodo'] = str(sum((f.ventas_periodo for f in filas), Decimal('0')))
    datos['resumen']['descuento_global_pct'] = _num(nomina.descuento_global(suma['ventas_con_lista'], suma['lista_total']))
    # Estado general dinámico: cerrado solo si todos los asesores están cerrados.
    datos['asesores_cerrados'] = sum(1 for f in filas if f.estado == 'cerrado')
    datos['asesores_total'] = len(filas)
    datos['asesores'] = [{
        'id': f.id, 'asesor': f.asesor_id, 'nombre': _nombre(f.asesor), 'salario_basico': _num(f.salario_basico),
        'meta': _num(f.meta), 'ventas_periodo': _num(f.ventas_periodo), 'cumple_meta': f.cumple_meta,
        'cumple_meta_manual': f.cumple_meta_manual, 'nota': f.nota,
        'estado': f.estado, 'cerrado_por': _nombre(f.cerrado_por), 'cerrado_en': f.cerrado_en,
        'totales': {k: (None if v is None else str(v)) for k, v in totales[f.id].items()},
        **({'lineas': [_linea(l) for l in f.lineas.all()]} if detalle else {}),
    } for f in filas]
    return datos


def _consulta_cierre():
    return CierreNomina.objects.select_related('creado_por', 'cerrado_por').prefetch_related(
        Prefetch('asesores', queryset=AsesorCierre.objects.select_related('asesor', 'cerrado_por').prefetch_related(
            Prefetch('lineas', queryset=LineaNomina.objects.select_related('venta', 'causada_en')))))


def _fecha(valor, campo):
    try:
        return date.fromisoformat(str(valor))
    except (TypeError, ValueError):
        raise ErrorNegocio('Fecha inválida.', 400, campo)


@api_view(['GET', 'PUT'])
@permission_classes(PERMISOS)
def config_nomina(request):
    cfg = nomina.config()
    if request.method == 'PUT':
        d = request.data
        if 'tabla_comision' in d:
            try:
                tabla = [[float(Decimal(str(fila[0]))), float(Decimal(str(fila[1])))] for fila in d['tabla_comision']]
            except (TypeError, ValueError, InvalidOperation, IndexError):
                raise ErrorNegocio('La tabla debe tener filas [descuento %, comisión %].', 400, 'tabla_comision')
            if not tabla or any(x < 0 or y < 0 for x, y in tabla):
                raise ErrorNegocio('La tabla no puede estar vacía ni tener valores negativos.', 400, 'tabla_comision')
            cfg.tabla_comision = sorted(tabla)
        for campo in ('abono_minimo_pct', 'bonificacion_pct'):
            if campo in d:
                setattr(cfg, campo, Decimal(str(d[campo])))
        if 'ventas_desde' in d:
            cfg.ventas_desde = _fecha(d['ventas_desde'], 'ventas_desde') if d['ventas_desde'] else None
        if 'dia_pago_basico' in d:
            cfg.dia_pago_basico = int(d['dia_pago_basico'])
        if 'pago_nomina' in d:
            cfg.pago_nomina = str(d['pago_nomina'])[:60]
        cfg.actualizado_por = request.user
        cfg.save()
        auditar(request.user, 'nomina.config', cfg, dict(d))
    return Response({
        'tabla_comision': cfg.tabla_comision, 'abono_minimo_pct': _num(cfg.abono_minimo_pct),
        'bonificacion_pct': _num(cfg.bonificacion_pct), 'ventas_desde': cfg.ventas_desde,
        'dia_pago_basico': cfg.dia_pago_basico, 'pago_nomina': cfg.pago_nomina,
    })


@api_view(['GET'])
@permission_classes(PERMISOS)
def asesores_nomina(request):
    fijos = {a.asesor_id: a for a in AsesorNomina.objects.all()}
    usuarios = CustomUser.objects.filter(is_active=True, role='vendedor').order_by('first_name', 'username')
    extra = CustomUser.objects.filter(id__in=fijos).exclude(role='vendedor')
    return Response([{
        'asesor': u.id, 'nombre': _nombre(u), 'rol': u.role,
        'salario_basico': _num(fijos[u.id].salario_basico) if u.id in fijos else '0',
        'meta': _num(fijos[u.id].meta) if u.id in fijos else '0',
        'activo': fijos[u.id].activo if u.id in fijos else True,
    } for u in list(usuarios) + list(extra)])


@api_view(['PATCH'])
@permission_classes(PERMISOS)
def editar_asesor_nomina(request, asesor_id):
    asesor = get_object_or_404(CustomUser, pk=asesor_id)
    fila, _ = AsesorNomina.objects.get_or_create(asesor=asesor)
    for campo in ('salario_basico', 'meta'):
        if campo in request.data:
            setattr(fila, campo, nomina.q(Decimal(str(request.data[campo] or 0))))
    if 'activo' in request.data:
        fila.activo = bool(request.data['activo'])
    fila.save()
    auditar(request.user, 'nomina.asesor_fijo', fila, dict(request.data))
    if 'salario_basico' in request.data or 'meta' in request.data:
        nomina.actualizar_fijos(asesor.id)
    return Response({'asesor': asesor.id, 'salario_basico': _num(fila.salario_basico), 'meta': _num(fila.meta), 'activo': fila.activo})


@api_view(['GET', 'POST'])
@permission_classes(PERMISOS)
def cierres(request):
    if request.method == 'POST':
        inicio = _fecha(request.data.get('fecha_inicio'), 'fecha_inicio')
        fin = _fecha(request.data.get('fecha_fin'), 'fecha_fin')
        cierre = nomina.crear_cierre(request.user, inicio, fin, str(request.data.get('nombre') or '')[:120])
        return Response(_cierre(_consulta_cierre().get(pk=cierre.pk)), status=status.HTTP_201_CREATED)
    inicio, fin = business_time.periodo_comercial()
    return Response({
        'periodo_sugerido': {'fecha_inicio': inicio, 'fecha_fin': fin},
        'cierres': [_cierre(c, detalle=False) for c in _consulta_cierre()[:60]],
    })


@api_view(['GET', 'DELETE'])
@permission_classes(PERMISOS)
def cierre_detalle(request, pk):
    if request.method == 'DELETE':
        nomina.borrar_cierre(pk, request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)
    return Response(_cierre(get_object_or_404(_consulta_cierre(), pk=pk)))


@api_view(['POST'])
@permission_classes(PERMISOS)
def cierre_accion(request, pk, accion):
    if accion == 'regenerar':
        nomina.regenerar(pk, request.user)
    elif accion == 'cerrar':
        nomina.cerrar(pk, request.user)
    elif accion == 'reabrir':
        nomina.reabrir(pk, request.user, request.data.get('motivo'))
    else:
        return Response(status=status.HTTP_404_NOT_FOUND)
    return Response(_cierre(_consulta_cierre().get(pk=pk)))


@api_view(['PATCH'])
@permission_classes(PERMISOS)
def asesor_cierre(request, pk):
    fila = nomina.editar_asesor(pk, request.user, request.data)
    return Response(_cierre(_consulta_cierre().get(pk=fila.cierre_id)))


@api_view(['POST'])
@permission_classes(PERMISOS)
def ajustes(request, pk):
    linea = nomina.agregar_ajuste(pk, request.user, request.data.get('descripcion'), request.data.get('valor'))
    return Response(_cierre(_consulta_cierre().get(pk=linea.asesor_cierre.cierre_id)), status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes(PERMISOS)
def asesor_accion(request, pk, accion):
    """Cerrar (dar por pagada) o reabrir la nómina de un asesor dentro del cierre."""
    if accion == 'cerrar':
        fila = nomina.cerrar_asesor(pk, request.user)
    elif accion == 'reabrir':
        fila = nomina.reabrir_asesor(pk, request.user)
    else:
        return Response(status=status.HTTP_404_NOT_FOUND)
    return Response(_cierre(_consulta_cierre().get(pk=fila.cierre_id)))


@api_view(['PATCH', 'DELETE'])
@permission_classes(PERMISOS)
def linea(request, pk):
    cierre_id = get_object_or_404(LineaNomina.objects.select_related('asesor_cierre'), pk=pk).asesor_cierre.cierre_id
    if request.method == 'DELETE':
        nomina.borrar_ajuste(pk, request.user)
    else:
        nomina.editar_linea(pk, request.user, request.data)
    return Response(_cierre(_consulta_cierre().get(pk=cierre_id)))


@api_view(['GET'])
@permission_classes(PERMISOS)
def venta_de_linea(request, pk):
    """Detalle para validar una comisión contra la venta física: datos de la venta,
    productos con su precio de lista y precio de venta, y pagos recibidos."""
    l = get_object_or_404(LineaNomina.objects.select_related('venta__cliente', 'venta__vendedor'), pk=pk)
    v = l.venta
    if not v:
        return Response({'error': 'Esta línea no tiene venta.'}, status=status.HTTP_404_NOT_FOUND)
    productos = []
    for p in v.lineas.select_related('referencia__proveedor', 'grupo_catalogo').order_by('id'):
        lista_u = p.precio_lista_unitario
        productos.append({
            'id': p.id, 'tipo': p.tipo, 'nombre': ' · '.join(x for x in (p.producto_nombre, p.variante_nombre) if x),
            'categoria': p.categoria_nombre, 'referencia': p.referencia.nombre if p.referencia else '',
            'proveedor': p.referencia.proveedor.nombre_empresa if p.referencia and p.referencia.proveedor else '',
            'cantidad': p.cantidad, 'grupo_tela': p.grupo_catalogo.nombre if p.grupo_catalogo else p.grupo_tela,
            'tela': texto_tela(p), 'precio_lista_unitario': _num(lista_u),
            'precio_lista_total': _num(lista_u * p.cantidad) if lista_u is not None else None,
            'precio_venta': _num(p.subtotal), 'descuento': _num(p.descuento), 'texto_cliente': p.texto_cliente,
        })
    con_lista = [p for p in productos if p['precio_lista_total'] is not None]
    suma_lista = sum((Decimal(p['precio_lista_total']) for p in con_lista), Decimal('0'))
    suma_venta = sum((Decimal(p['precio_venta']) for p in productos), Decimal('0'))
    pagos = [{
        'recibo': pg.recibo_id, 'fecha': pg.recibo.fecha, 'metodo': pg.metodo_pago, 'valor': _num(pg.valor), 'estado': pg.estado,
    } for pg in PagoReciboCaja.objects.filter(recibo__venta=v).select_related('recibo').order_by('recibo__fecha', 'id')]
    compartida = [_nombre(u) for u in v.vendedores_compartidos.all()]
    c = v.cliente if v.cliente_id else None
    return Response({
        'venta': {
            'id': v.id, 'fecha_venta': v.fecha_venta, 'cliente': c.nombre if c else '', 'sede': v.sede,
            'direccion': (c.direccion or '') if c else '', 'barrio': (c.barrio or '') if c else '', 'ciudad': (c.ciudad or '') if c else '',
            'vendedor': _nombre(v.vendedor), 'compartida_con': compartida, 'estado': v.estado,
            'valor_total': _num(v.valor_total), 'valor_lista': _num(v.valor_lista), 'abono': _num(v.abono), 'saldo': _num(v.saldo),
            'productos_confirmados': v.productos_confirmados, 'revision_productos': v.revision_productos,
        },
        'productos': productos,
        'totales': {
            'precio_lista': _num(suma_lista) if con_lista else None, 'precio_venta': _num(suma_venta),
            'productos_sin_precio_lista': len(productos) - len(con_lista),
            # ¿Lo de los productos cuadra con lo registrado en la venta?
            'lista_cuadra': bool(con_lista) and v.valor_lista is not None and suma_lista == Decimal(v.valor_lista),
            'venta_cuadra': bool(productos) and suma_venta == Decimal(v.valor_total),
        },
        'pagos': pagos,
        'pedidos': pedidos_de_venta(v),
        'pedidos_tela': pedidos_tela_de_venta(v),
    })


def pedidos_de_venta(v):
    """(2026-10-28) Todo lo pedido al proveedor para la venta, incluso lo anulado (con su estado),
    para validar la comisión de un vistazo."""
    ordenes = (OrdenPedido.objects.filter(Q(venta=v) | Q(venta__isnull=True, orden_venta=str(v.pk)))
               .select_related('proveedor').prefetch_related('detalles__referencia', 'detalles__subcategoria').order_by('id'))
    return [{
        'id': o.id, 'proveedor': o.proveedor.nombre_empresa, 'estado': o.estado, 'estado_nombre': o.get_estado_display(),
        'fecha_creacion': o.fecha_creacion, 'fecha_esperada': o.fecha_esperada, 'tela': o.tela or '',
        'detalles': [{'referencia': d.referencia.nombre if d.referencia else '', 'subcategoria': d.subcategoria.nombre if d.subcategoria else '',
                      'cantidad': d.cantidad, 'especificaciones': d.especificaciones or ''} for d in o.detalles.all()],
    } for o in ordenes]


def pedidos_tela_de_venta(v):
    """Pedidos de tela de la venta: los ligados a la venta, a uno de sus pedidos o a sus productos."""
    pedidos = (PedidoTela.objects.filter(Q(venta=v) | Q(orden_asociada__venta=v) | Q(detalles__linea_venta__venta=v)).distinct()
               .select_related('proveedor').prefetch_related('detalles__linea_venta').order_by('id'))
    return [{
        'id': p.id, 'proveedor': p.proveedor.nombre_empresa, 'estado': p.estado, 'fecha_creacion': p.fecha_creacion,
        'orden': p.orden_asociada_id, 'direccion': p.direccion_entrega,
        'detalles': [{'tela': d.tela, 'cantidad': _num(d.cantidad),
                      'unidad': 'dm' if d.linea_venta and d.linea_venta.tela_material == 'cuero' else 'm'} for d in p.detalles.all()],
    } for p in pedidos]
