"""Panel del administrador (2026-10-09): una sola consulta con lo que sirve para decidir
el día — ritmo de ventas del período comercial frente al anterior, asesores, recaudo,
caja, cartera, lo que requiere atención en cada módulo y los últimos informes de la IA.

Solo lectura. Exige VER_DASHBOARD_GENERAL (el administrador lo tiene siempre). Cada
pendiente de «Requiere atención» solo se incluye si el usuario puede abrir su módulo.
"""
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Q, Sum
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from . import business_time
from .estadisticas import parte_de, participantes
from .gestion_venta import DIAS_LIMITE
from .models import (
    AsesorCierre, ComprobanteEgreso, EjecucionAutomatizacionIA, OrdenPedido, PagoReciboCaja, PedidoTela,
    PerfilAsistente, Venta,
)
from .permissions import check_feature_permission, tiene_permiso_codigo
from .servicios import saldo_caja

CERO = Decimal('0')
REMISION_ACTIVA = ('creada', 'despachada')
# Las cifras basadas en el estado de la venta (gestión, entregas, cartera) miran solo las
# ventas recientes: muchas ventas antiguas nunca se marcaron como entregadas.
VENTANA_DIAS = 90

ATENCION = [  # clave, título, detalle, tono, ruta, grupo (el orden es el de pantalla)
    ('gestion_atrasada', 'Gestión de ventas atrasada', f'Ventas de los últimos {VENTANA_DIAS} días sin finalizar su gestión', 'danger', '/ventas', 'ventas'),
    ('entregas_vencidas', 'Entregas pactadas vencidas', f'Ventas de los últimos {VENTANA_DIAS} días sin entregar y con la fecha pasada', 'warning', '/ventas', 'ventas'),
    ('op_atrasadas', 'Pedidos a fábrica atrasados', 'OP sin recibir con la fecha de llegada vencida', 'danger', '/ordenes', 'pedidos'),
    ('telas_pendientes', 'Telas por pedir', 'Pedidos de tela en estado Pendiente', 'warning', '/telas', 'telas'),
    ('remisiones_atrasadas', 'Remisiones atrasadas', 'Entregas programadas que no se han cerrado', 'danger', '/suministros/remisiones', 'entregas'),
    ('remisiones_hoy', 'Entregas para hoy', 'Remisiones programadas para hoy', 'info', '/suministros/remisiones', 'entregas'),
    ('sin_transportador', 'Remisiones sin transportador', 'Por despachar sin transportador asignado', 'warning', '/suministros/remisiones', 'entregas'),
    ('rc_por_confirmar', 'Pagos de clientes por confirmar', 'Pagos de recibos de caja en Pendiente', 'warning', '/recibos-caja', 'dinero'),
    ('ce_por_confirmar', 'Egresos por confirmar', 'Pagos a proveedores sin confirmar', 'warning', '/comprobantes-egreso', 'dinero'),
    ('facturas_vencidas', 'Facturas de proveedor vencidas', 'Pendientes con la fecha límite pasada', 'danger', '/suministros/facturas', 'dinero'),
    ('facturas_semana', 'Facturas que vencen esta semana', 'Fecha límite en los próximos 7 días', 'info', '/suministros/facturas', 'dinero'),
    ('nomina_abierta', 'Nómina por cerrar', 'Asesores con la nómina abierta de un período ya terminado', 'warning', '/nomina', 'nomina'),
]


def _f(valor):
    return float(valor or 0)


def _pct(actual, base):
    return round(float((Decimal(actual) - Decimal(base)) / Decimal(base) * 100), 1) if base else None


def _nombre(u):
    return (f'{u.first_name} {u.last_name}'.strip() or u.username) if u else ''


def _ventas_validas():
    return Venta.objects.exclude(estado=Venta.ESTADO_ANULADA)


def _ventas(hoy):
    inicio, fin = business_time.periodo_comercial(hoy)
    ant_inicio, ant_fin = business_time.periodo_comercial(inicio - timedelta(days=1))
    dias = (fin - inicio).days + 1
    transcurridos = (hoy - inicio).days + 1
    corte = min(ant_inicio + timedelta(days=transcurridos - 1), ant_fin)  # mismo día del período anterior
    validas = _ventas_validas()
    periodo = validas.filter(fecha_venta__gte=inicio, fecha_venta__lte=min(hoy, fin))
    en_periodo = Q(fecha_venta__gte=inicio, fecha_venta__lte=hoy)
    en_anterior = Q(fecha_venta__gte=ant_inicio, fecha_venta__lte=ant_fin)
    a = validas.filter(Q(fecha_venta__gte=ant_inicio, fecha_venta__lte=hoy)).aggregate(
        total=Sum('valor_total', filter=en_periodo), cantidad=Count('id', filter=en_periodo),
        hoy_total=Sum('valor_total', filter=Q(fecha_venta=hoy)), hoy_cantidad=Count('id', filter=Q(fecha_venta=hoy)),
        anterior_total=Sum('valor_total', filter=en_anterior),
        anterior_corte=Sum('valor_total', filter=Q(fecha_venta__gte=ant_inicio, fecha_venta__lte=corte)),
        lista=Sum('valor_lista', filter=en_periodo & Q(valor_lista__gt=0)),
        vendido_con_lista=Sum('valor_total', filter=en_periodo & Q(valor_lista__gt=0)),
        con_lista=Count('id', filter=en_periodo & Q(valor_lista__gt=0)),
    )
    total, cantidad = a['total'] or CERO, a['cantidad']
    lista = a['lista'] or CERO
    # Series acumuladas día a día (período actual hasta hoy y período anterior completo) en una consulta.
    por_dia = defaultdict(lambda: CERO)
    for f in validas.filter(fecha_venta__gte=ant_inicio, fecha_venta__lte=hoy).values('fecha_venta').annotate(t=Sum('valor_total')):
        por_dia[f['fecha_venta']] += f['t'] or CERO

    def acumulado(desde, n):
        serie, suma = [], CERO
        for i in range(n):
            suma += por_dia[desde + timedelta(days=i)]
            serie.append(_f(suma))
        return serie

    sedes = [{'sede': f['sede'] or 'Sin sede', 'total': _f(f['t']), 'cantidad': f['n']}
             for f in periodo.values('sede').annotate(t=Sum('valor_total'), n=Count('id')).order_by('-t')]
    return {
        'periodo': {'inicio': inicio, 'fin': fin, 'dias': dias, 'dia': transcurridos,
                    'anterior_inicio': ant_inicio, 'anterior_fin': ant_fin},
        'ventas': {
            'total': _f(total), 'cantidad': cantidad,
            'ticket_promedio': _f(total / cantidad) if cantidad else 0,
            'hoy_total': _f(a['hoy_total']), 'hoy_cantidad': a['hoy_cantidad'],
            'anterior_corte': _f(a['anterior_corte']), 'variacion_pct': _pct(total, a['anterior_corte'] or CERO),
            'anterior_total': _f(a['anterior_total']),
            'proyeccion': _f(total / transcurridos * dias) if transcurridos else 0,
            'descuento_pct': round(float((1 - (a['vendido_con_lista'] or CERO) / lista) * 100), 1) if lista else None,
            'con_lista': a['con_lista'],
            'serie_actual': acumulado(inicio, transcurridos),
            'serie_anterior': acumulado(ant_inicio, (ant_fin - ant_inicio).days + 1),
            'por_sede': sedes,
        },
        '_periodo_qs': periodo,
    }


def _asesores(periodo):
    """Ranking del período: cada participante recibe Total / N (regla de métricas personales)."""
    totales, cantidades, usuarios = defaultdict(lambda: CERO), defaultdict(int), {}
    for venta in periodo.select_related('vendedor').prefetch_related('vendedores_compartidos'):
        for persona in [venta.vendedor, *venta.vendedores_compartidos.all()]:
            if persona:
                usuarios[persona.id] = persona
        for pid in participantes(venta):
            totales[pid] += parte_de(venta, pid)
            cantidades[pid] += 1
    filas = [{'id': pid, 'nombre': _nombre(usuarios.get(pid)), 'total': _f(t), 'ventas': cantidades[pid]}
             for pid, t in totales.items()]
    return sorted(filas, key=lambda f: -f['total'])


def _contar(qs, **filtros):
    """Una sola consulta con conteo (y suma opcional) por cada filtro: {clave: (Q, campo_suma)}."""
    agregados = {}
    for clave, (filtro, campo) in filtros.items():
        agregados[f'{clave}__n'] = Count('pk', filter=filtro)
        if campo:
            agregados[f'{clave}__v'] = Sum(campo, filter=filtro)
    r = qs.aggregate(**agregados) if agregados else {}
    return {clave: (r[f'{clave}__n'], r.get(f'{clave}__v')) for clave in filtros}


def _atencion(request, hoy):
    """Pendientes accionables por módulo; solo los módulos que el usuario puede abrir."""
    from suministros.models import FacturaProveedor, RemisionSuministro

    puede = lambda codigo: tiene_permiso_codigo(request, codigo)  # noqa: E731
    datos = {}
    if puede('VER_VENTAS'):
        recientes = _ventas_validas().filter(estado=Venta.ESTADO_PENDIENTE, fecha_venta__gte=hoy - timedelta(days=VENTANA_DIAS))
        datos.update(_contar(recientes,
                             gestion_atrasada=(Q(estado_pedidos=False, fecha_venta__lt=hoy - timedelta(days=DIAS_LIMITE)), None),
                             entregas_vencidas=(Q(fecha_entrega__lt=hoy), None)))
    if puede('VER_ORDENES'):
        datos.update(_contar(OrdenPedido.objects.all(),
                             op_atrasadas=(Q(estado__in=('pendiente', 'en_proceso'), fecha_esperada__lt=hoy), None)))
    if puede('VER_TELAS'):
        datos.update(_contar(PedidoTela.objects.all(), telas_pendientes=(Q(estado='Pendiente'), None)))
    if puede('VER_REMISIONES'):
        datos.update(_contar(RemisionSuministro.objects.filter(estado__in=REMISION_ACTIVA),
                             remisiones_atrasadas=(Q(fecha_entrega__lt=hoy), None),
                             remisiones_hoy=(Q(fecha_entrega=hoy), None),
                             sin_transportador=(Q(estado='creada', transportador_usuario__isnull=True, transportador=''), None)))
    if puede('ACCESO_RECIBOS'):
        datos.update(_contar(PagoReciboCaja.objects.exclude(recibo__venta__estado=Venta.ESTADO_ANULADA),
                             rc_por_confirmar=(Q(estado='Pendiente'), 'valor')))
    if puede('ACCESO_EGRESOS'):
        datos.update(_contar(ComprobanteEgreso.objects.all(), ce_por_confirmar=(Q(estado='Por Confirmar Pago'), 'valor')))
    if puede('VER_FACTURAS'):
        datos.update(_contar(FacturaProveedor.objects.filter(estado__in=('pendiente', 'atrasada')),
                             facturas_vencidas=(Q(fecha_pago__lt=hoy), 'valor'),
                             facturas_semana=(Q(fecha_pago__gte=hoy, fecha_pago__lte=hoy + timedelta(days=7)), 'valor')))
    if puede('VER_NOMINA'):
        datos.update(_contar(AsesorCierre.objects.all(), nomina_abierta=(Q(estado='abierto', cierre__fecha_fin__lt=hoy), None)))

    salida = []
    for clave, titulo, detalle, tono, ruta, grupo in ATENCION:
        if clave in datos:
            cantidad, valor = datos[clave]
            salida.append({'clave': clave, 'titulo': titulo, 'detalle': detalle, 'cantidad': cantidad,
                           'valor': _f(valor) if valor is not None and cantidad else None,
                           'tono': tono, 'ruta': ruta, 'grupo': grupo})
    return salida


def _dinero(request, hoy, inicio):
    datos = {}
    if tiene_permiso_codigo(request, 'ACCESO_CAJA'):
        datos['saldo_caja'] = _f(saldo_caja())
    if tiene_permiso_codigo(request, 'ACCESO_RECIBOS'):
        r = PagoReciboCaja.objects.filter(estado='Confirmado', recibo__fecha__gte=inicio, recibo__fecha__lte=hoy).aggregate(
            periodo=Sum('valor'), hoy=Sum('valor', filter=Q(recibo__fecha=hoy)))
        datos['recaudo_periodo'], datos['recaudo_hoy'] = _f(r['periodo']), _f(r['hoy'])
    if tiene_permiso_codigo(request, 'VER_VENTAS'):
        r = _ventas_validas().filter(estado=Venta.ESTADO_PENDIENTE, saldo__gt=0,
                                     fecha_venta__gte=hoy - timedelta(days=VENTANA_DIAS)).aggregate(s=Sum('saldo'), n=Count('id'))
        datos['cartera'], datos['cartera_ventas'] = _f(r['s']), r['n']
    datos['ventana_dias'] = VENTANA_DIAS
    return datos


def _ia(request):
    if not tiene_permiso_codigo(request, 'USAR_ASISTENTE_IA'):
        return None
    ejecuciones = (EjecucionAutomatizacionIA.objects.filter(automatizacion__usuario=request.user, estado='listo')
                   .order_by('-finalizada', '-id')[:4])
    return {
        'agentes': list(PerfilAsistente.objects.filter(activo=True).values('id', 'nombre', 'rol', 'icono', 'color')[:8]),
        'informes': [{
            'id': e.id, 'nombre': e.nombre, 'agente': e.perfil_nombre, 'finalizada': e.finalizada, 'leida': e.leida,
            'extracto': ' '.join((e.resultado or '').replace('#', '').replace('*', '').split())[:220],
            'conversacion': e.conversacion_id,
        } for e in ejecuciones],
        'sin_leer': EjecucionAutomatizacionIA.objects.filter(automatizacion__usuario=request.user, estado='listo', leida=False).count(),
    }


def _ultimas(request):
    ventas = (_ventas_validas().select_related('cliente', 'vendedor').prefetch_related('vendedores_compartidos')
              .order_by('-fecha_venta', '-id')[:6])
    hoy = business_time.hoy()
    from .gestion_venta import estado_gestion
    return [{
        'id': v.id, 'cliente': v.cliente.nombre, 'fecha': v.fecha_venta, 'valor_total': _f(v.valor_total),
        'saldo': _f(v.saldo), 'estado': v.estado, 'gestion': estado_gestion(v, hoy), 'sede': v.sede,
        'vendedores': ', '.join(_nombre(u).split(' ')[0] for u in [v.vendedor, *v.vendedores_compartidos.all()] if u),
    } for v in ventas] if tiene_permiso_codigo(request, 'VER_VENTAS') else []


@api_view(['GET'])
@permission_classes([IsAuthenticated, check_feature_permission('VER_DASHBOARD_GENERAL')])
def dashboard_admin(request):
    hoy = business_time.hoy()
    base = _ventas(hoy)
    periodo_qs = base.pop('_periodo_qs')
    return Response({
        'hoy': hoy,
        **base,
        'asesores': _asesores(periodo_qs),
        'dinero': _dinero(request, hoy, base['periodo']['inicio']),
        'atencion': _atencion(request, hoy),
        'ia': _ia(request),
        'ultimas_ventas': _ultimas(request),
    })
