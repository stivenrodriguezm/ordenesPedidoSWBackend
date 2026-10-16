"""Consultas analíticas parametrizadas. Solo ORM/SELECT, columnas permitidas y agregados.
No acepta SQL, nombres de tabla ni expresiones del modelo de lenguaje.
"""
from datetime import date
from decimal import Decimal

from django.db.models import Avg, Count, DecimalField, F, Sum, ExpressionWrapper
from django.db.models.functions import TruncDay, TruncMonth, TruncWeek
from django.utils import timezone

from .. import business_time
from ..models import Venta, LineaVenta, OrdenPedido, PagoReciboCaja

DIMENSIONES = {
    'ventas': {'sede': 'sede', 'estado': 'estado', 'ciudad': 'cliente__ciudad', 'feria': 'es_feria_hogar', 'postferia': 'es_postferia'},
    'productos': {'producto': 'producto_nombre', 'categoria': 'categoria_nombre', 'grupo_tela': 'grupo_tela'},
    'pedidos': {'proveedor': 'proveedor__nombre_empresa', 'estado': 'estado'},
    'cobros': {'medio_pago': 'metodo_pago', 'estado': 'estado'},
    'inventario': {'disponibilidad': 'disponibilidad', 'zona': 'zona__nombre'},
}
METRICAS = {
    'ventas': {'ventas': 'unidades', 'valor_vendido': 'COP', 'abonado': 'COP', 'saldo': 'COP', 'ticket_promedio': 'COP'},
    'productos': {'unidades': 'unidades', 'valor_lista': 'COP'},
    'pedidos': {'pedidos': 'unidades'},
    'cobros': {'valor_confirmado': 'COP', 'pagos': 'unidades'},
    'inventario': {'unidades': 'unidades', 'costo_registrado': 'COP'},
}


def _fechas(args):
    inicio, fin = business_time.periodo_comercial()
    desde = date.fromisoformat(args['desde']) if args.get('desde') else inicio
    hasta = date.fromisoformat(args['hasta']) if args.get('hasta') else min(fin, business_time.hoy())
    if desde > hasta or (hasta - desde).days > 1860:
        raise ValueError('Usa un rango ordenado de hasta cinco años.')
    return desde, hasta


def _numero(v):
    return float(v.quantize(Decimal('.01'))) if isinstance(v, Decimal) else v


def consultar(args):
    dominio = args.get('dominio', 'ventas')
    grupo = args.get('agrupar', 'sede' if dominio == 'ventas' else next(iter(DIMENSIONES.get(dominio, {'': ''}))))
    permitidos = {'dominio', 'agrupar', 'desde', 'hasta', 'sede', 'estado', 'proveedor_id', 'categoria', 'limite', 'orden', 'metrica'}
    if set(args) - permitidos or dominio not in DIMENSIONES:
        raise ValueError('Consulta no permitida. Usa los parámetros de consulta_datos.')
    desde, hasta = _fechas(args)
    limite = int(args.get('limite', 20))
    if not 1 <= limite <= 50:
        raise ValueError('El límite debe estar entre 1 y 50 grupos.')
    temporales = {'dia': TruncDay, 'semana': TruncWeek, 'mes': TruncMonth}
    if grupo not in DIMENSIONES[dominio] and grupo not in temporales:
        raise ValueError('Agrupación no válida para ese dominio; para asesores usa ventas_por_asesor (Total/N).')
    if dominio == 'ventas':
        qs = Venta.objects.exclude(estado__in=['anulada', 'anulado'])
        fecha = 'fecha_venta'
        metricas = dict(ventas=Count('pk'), valor_vendido=Sum('valor_total'), abonado=Sum('abono'), saldo=Sum('saldo'), ticket_promedio=Avg('valor_total'))
        nota = 'Ventas no anuladas; importes completos de empresa. Abonado y saldo actuales, no un corte histórico de cartera.'
    elif dominio == 'productos':
        qs = LineaVenta.objects.filter(tipo=LineaVenta.TIPO_PRODUCTO, venta__productos_confirmados=True).exclude(venta__estado__in=['anulada', 'anulado'])
        fecha = 'venta__fecha_venta'
        valor = ExpressionWrapper(F('cantidad') * F('precio_lista_unitario'), output_field=DecimalField(max_digits=20, decimal_places=2))
        metricas = dict(unidades=Sum('cantidad'), valor_lista=Sum(valor))
        nota = 'Solo productos de ventas con desglose confirmado. Lista = cantidad × precio de lista unitario; no es ingreso pactado. Históricos sin líneas excluidos.'
    elif dominio == 'pedidos':
        qs = OrdenPedido.objects.exclude(estado='anulado')
        fecha = 'fecha_creacion'
        metricas = dict(pedidos=Count('pk'))
        nota = 'Pedidos al proveedor creados en el rango; no equivalen a productos vendidos.'
    elif dominio == 'cobros':
        qs = PagoReciboCaja.objects.filter(estado='Confirmado')
        fecha = 'recibo__fecha'
        metricas = dict(valor_confirmado=Sum('valor'), pagos=Count('pk'))
        nota = 'Solo pagos confirmados; pagos anulados o pendientes excluidos. Fecha del recibo.'
    else:
        from suministros.models import Inventario
        qs = Inventario.objects.all()
        fecha = 'fecha_ingreso'
        metricas = dict(unidades=Count('pk'), costo_registrado=Sum('costo_especifico'))
        nota = 'Inventario ingresado en el rango, con disponibilidad actual; costo registrado puede ser incompleto.'
    filtros = {'desde': str(desde), 'hasta': str(hasta)}
    mapas = {
        'ventas': {'sede': 'sede', 'estado': 'estado'},
        'productos': {'sede': 'venta__sede', 'estado': 'venta__estado', 'categoria': 'categoria_nombre'},
        'pedidos': {'proveedor_id': 'proveedor_id', 'estado': 'estado'},
        'cobros': {'sede': 'recibo__venta__sede', 'estado': 'estado'},
        'inventario': {'estado': 'disponibilidad'},
    }
    for nombre in ('sede', 'estado', 'proveedor_id', 'categoria'):
        if args.get(nombre) is not None:
            if nombre not in mapas[dominio]:
                raise ValueError(f'El filtro {nombre} no aplica a {dominio}.')
            valor = args[nombre]
            if not isinstance(valor, (str, int)) or len(str(valor)) > 100:
                raise ValueError('Valor de filtro inválido.')
            qs = qs.filter(**{mapas[dominio][nombre]: valor})
            filtros[nombre] = valor
    qs = qs.filter(**{fecha + '__range': (desde, hasta)}).order_by()
    metrica = args.get('metrica') or next(iter(metricas))
    if metrica not in metricas:
        raise ValueError('Métrica inválida para ese dominio.')
    orden = args.get('orden', 'etiqueta' if grupo in temporales else 'desc')
    if orden not in ('asc', 'desc', 'etiqueta'):
        raise ValueError('Orden inválido.')
    dimension = temporales[grupo](fecha) if grupo in temporales else F(DIMENSIONES[dominio][grupo])
    agrupado = qs.annotate(etiqueta=dimension).values('etiqueta').annotate(**metricas)
    total_grupos = agrupado.count()
    orden_sql = ['etiqueta'] if orden == 'etiqueta' else [('' if orden == 'asc' else '-') + metrica, 'etiqueta']
    filas = []
    for fila in agrupado.order_by(*orden_sql)[:limite]:
        etiqueta = fila.pop('etiqueta')
        if isinstance(etiqueta, date):
            etiqueta = etiqueta.isoformat()[:10]
        elif isinstance(etiqueta, bool):
            etiqueta = 'Sí' if etiqueta else 'No'
        else:
            etiqueta = str(etiqueta) if etiqueta not in (None, '') else 'Sin dato'
        filas.append({'etiqueta': etiqueta, **{k: _numero(v) for k, v in fila.items()}})
    return {'dominio': dominio, 'agrupacion': grupo, 'filtros': filtros, 'consultado_en': timezone.now().isoformat(),
            'columnas': {'etiqueta': grupo, **METRICAS[dominio]}, 'filas': filas,
            'totales': {k: _numero(v) for k, v in qs.aggregate(**metricas).items()},
            'grupos_totales': total_grupos, 'truncado': total_grupos > limite, 'limite': limite, 'nota': nota}


PROPIEDADES = {
    'dominio': {'type': 'string', 'enum': list(DIMENSIONES)},
    'agrupar': {'type': 'string', 'description': 'ventas: sede, estado, ciudad, feria, postferia; productos: producto, categoria, grupo_tela; pedidos: proveedor, estado; cobros: medio_pago, estado; inventario: disponibilidad, zona. Todos admiten dia, semana o mes CALENDARIO. Asesores: usar ventas_por_asesor.'},
    'desde': {'type': 'string', 'description': 'AAAA-MM-DD, incluido; defecto inicio comercial actual.'},
    'hasta': {'type': 'string', 'description': 'AAAA-MM-DD, incluido; defecto hoy.'},
    'sede': {'type': 'string'}, 'estado': {'type': 'string'}, 'proveedor_id': {'type': 'integer'}, 'categoria': {'type': 'string'},
    'limite': {'type': 'integer', 'description': '1–50 grupos; defecto 20.'},
    'metrica': {'type': 'string', 'description': 'ventas: ventas, valor_vendido, abonado, saldo, ticket_promedio; productos: unidades, valor_lista; pedidos: pedidos; cobros: valor_confirmado, pagos; inventario: unidades, costo_registrado.'},
    'orden': {'type': 'string', 'enum': ['asc', 'desc', 'etiqueta']},
}
