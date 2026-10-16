"""Herramientas de datos del asesor gerencial (Gemini function calling).

Solo lectura y agregados: el modelo nunca escribe ni ve documentos, teléfonos o
correos. Cada herramienta devuelve un dict serializable a JSON con cifras redondeadas.
Pocas consultas por herramienta: la base remota tarda ~0,5 s por consulta.
"""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.db import InterfaceError, OperationalError, connection
from django.db.models import Count, Q, Sum, F, DecimalField, ExpressionWrapper

from . import analitica, graficos, web
from .. import business_time
from ..gestion_venta import DIAS_LIMITE, estado_gestion
from ..models import (Caja, ComprobanteEgreso, CuentaCaja, CustomUser, DetallePedido, DetallePedidoTela,
                      LineaNomina, LineaVenta, AsesorNomina, CierreNomina, OrdenPedido, PagoReciboCaja,
                      PedidoTela, Venta, TrabajoOficina, MiembroOficina, InteraccionOficina)

ANULADAS = ['anulada', 'anulado']


def _n(v):
    """Número para JSON: pesos sin decimales."""
    return int(Decimal(str(v or 0)).quantize(Decimal('1')))


def _pct(parte, total):
    return round(float(parte) * 100 / float(total), 1) if total else None


def _fecha(valor):
    try:
        return date.fromisoformat(str(valor)[:10]) if valor else None
    except ValueError:
        return None


def _rango(args):
    """desde/hasta (AAAA-MM-DD); por defecto el período comercial actual."""
    inicio, fin = business_time.periodo_comercial()
    desde, hasta = _fecha(args.get('desde')) or inicio, _fecha(args.get('hasta')) or fin
    if desde > hasta:
        desde, hasta = hasta, desde
    return desde, hasta


def _ventas():
    return Venta.objects.exclude(estado__in=ANULADAS)


def _nombres(ids):
    return {u['id']: (u['first_name'] or u['username']) for u in CustomUser.objects.filter(id__in=set(ids)).values('id', 'first_name', 'username')}


def _participantes(ventas):
    """{venta_id: {ids}}: asesor principal + compartidos (regla Total / N)."""
    partes = {v['id']: {v['vendedor_id']} for v in ventas}
    through = Venta.vendedores_compartidos.through
    for fila in through.objects.filter(venta_id__in=list(partes)).values('venta_id', 'customuser_id'):
        partes[fila['venta_id']].add(fila['customuser_id'])
    return partes


class _VentaMin:
    """Lo mínimo que necesita estado_gestion sin cargar el modelo completo."""
    def __init__(self, fila):
        self.estado, self.estado_pedidos, self.fecha_venta = fila['estado'], fila['estado_pedidos'], fila['fecha_venta']


# --- Herramientas ---------------------------------------------------------------

def resumen_ventas(args):
    desde, hasta = _rango(args)
    qs = _ventas().filter(fecha_venta__range=(desde, hasta))
    if args.get('sede'):
        qs = qs.filter(sede=args['sede'])
    a = qs.aggregate(
        n=Count('id'), total=Sum('valor_total'), abonado=Sum('abono'), saldo=Sum('saldo'),
        entregadas=Count('id', filter=Q(estado='entregado')), con_traslado=Count('id', filter=Q(traslado=True)),
        feria=Count('id', filter=Q(es_feria_hogar=True)), postferia=Count('id', filter=Q(es_postferia=True)),
        n_lista=Count('id', filter=Q(valor_lista__gt=0)), venta_lista=Sum('valor_total', filter=Q(valor_lista__gt=0)),
        lista=Sum('valor_lista', filter=Q(valor_lista__gt=0)),
    )
    por_sede = [{'sede': f['sede'] or 'Sin sede (feria)', 'ventas': f['n'], 'total': _n(f['t'])}
                for f in qs.values('sede').annotate(n=Count('id'), t=Sum('valor_total')).order_by('-t')]
    gestion = defaultdict(int)
    for fila in qs.values('estado', 'estado_pedidos', 'fecha_venta'):
        gestion[estado_gestion(_VentaMin(fila)) or 'anulada'] += 1
    total = a['total'] or 0
    return {
        'periodo': {'desde': str(desde), 'hasta': str(hasta)},
        'ventas': a['n'], 'valor_vendido': _n(total), 'ticket_promedio': _n(total / a['n']) if a['n'] else 0,
        'abonado': _n(a['abonado']), 'saldo_por_cobrar': _n(a['saldo']), 'pct_recaudado': _pct(a['abonado'] or 0, total),
        'entregadas': a['entregadas'], 'pendientes_de_entrega': a['n'] - a['entregadas'],
        'con_traslado': a['con_traslado'], 'feria_del_hogar': a['feria'], 'postferia': a['postferia'],
        'descuento_sobre_lista': {
            'ventas_con_precio_de_lista': a['n_lista'],
            'descuento_promedio_pct': _pct((a['lista'] or 0) - (a['venta_lista'] or 0), a['lista'] or 0),
            'nota': 'Solo ventas con productos registrados (desde oct-2026).',
        },
        'por_sede': por_sede, 'gestion': dict(gestion),
    }


def ventas_por_asesor(args):
    desde, hasta = _rango(args)
    ventas = list(_ventas().filter(fecha_venta__range=(desde, hasta)).values('id', 'vendedor_id', 'valor_total', 'valor_lista', 'saldo'))
    partes = _participantes(ventas)
    acum = defaultdict(lambda: {'ventas': 0.0, 'total': Decimal(0), 'compartidas': 0, 'lista': Decimal(0), 'venta_con_lista': Decimal(0), 'saldo': Decimal(0)})
    for v in ventas:
        ids = partes[v['id']] - {None}
        for pid in ids:
            n = len(ids)
            fila = acum[pid]
            fila['ventas'] += 1 / n
            fila['total'] += Decimal(v['valor_total']) / n
            fila['saldo'] += Decimal(v['saldo'] or 0) / n
            fila['compartidas'] += 1 if n > 1 else 0
            if v['valor_lista']:
                fila['lista'] += Decimal(v['valor_lista']) / n
                fila['venta_con_lista'] += Decimal(v['valor_total']) / n
    nombres = _nombres(acum)
    metas = {m['asesor_id']: m['meta'] for m in AsesorNomina.objects.filter(asesor_id__in=list(acum)).values('asesor_id', 'meta')}
    total_empresa = sum((f['total'] for f in acum.values()), Decimal(0))
    filas = []
    for pid, f in sorted(acum.items(), key=lambda x: -x[1]['total']):
        meta = metas.get(pid)
        filas.append({'asesor': nombres.get(pid, pid), 'ventas_equivalentes': round(f['ventas'], 1), 'compartidas': f['compartidas'],
                      'total_atribuido': _n(f['total']), 'participacion_pct': _pct(f['total'], total_empresa),
                      'ticket_promedio': _n(f['total'] / Decimal(f['ventas'])) if f['ventas'] else 0,
                      'saldo_por_cobrar_atribuido': _n(f['saldo']),
                      'descuento_promedio_pct': _pct(f['lista'] - f['venta_con_lista'], f['lista']),
                      'meta_periodo': _n(meta) if meta else None, 'cumplimiento_meta_pct': _pct(f['total'], meta) if meta else None})
    return {'periodo': {'desde': str(desde), 'hasta': str(hasta)}, 'regla': 'Venta compartida = Total / N participantes',
            'asesores': filas, 'total_empresa': _n(total_empresa)}


def tendencia_ventas(args):
    periodos = max(2, min(int(args.get('periodos') or 12), 24))
    inicio, fin = business_time.periodo_comercial()
    rangos = []
    mes, anio = inicio.month, inicio.year
    for _ in range(periodos):
        rangos.append(business_time.periodo_de_mes(mes, anio))
        mes, anio = (12, anio - 1) if mes == 1 else (mes - 1, anio)
    rangos.reverse()
    filas = _ventas().filter(fecha_venta__range=(rangos[0][0], rangos[-1][1])).values('fecha_venta', 'valor_total', 'abono')
    datos = [{'periodo': f'{a:%d %b %Y} – {b:%d %b %Y}', 'inicio': str(a), 'ventas': 0, 'valor': Decimal(0), 'abonado': Decimal(0)} for a, b in rangos]
    for f in filas:
        for i, (a, b) in enumerate(rangos):
            if a <= f['fecha_venta'] <= b:
                datos[i]['ventas'] += 1
                datos[i]['valor'] += f['valor_total']
                datos[i]['abonado'] += f['abono'] or 0
                break
    for d in datos:
        d['ticket_promedio'] = _n(d['valor'] / d['ventas']) if d['ventas'] else 0
        d['valor'], d['abonado'] = _n(d['valor']), _n(d['abonado'])
    return {'periodo_actual_incompleto_hasta': str(business_time.hoy()), 'periodos': datos}


def saldos_por_cobrar(args):
    top = max(1, min(int(args.get('top') or 15), 40))
    hoy = business_time.hoy()
    qs = _ventas().filter(saldo__gt=0)
    tramos = {'0-30 días': [0, Decimal(0)], '31-60 días': [0, Decimal(0)], '61-90 días': [0, Decimal(0)], 'más de 90 días': [0, Decimal(0)]}
    entregadas = [0, Decimal(0)]
    for f in qs.values('fecha_venta', 'saldo', 'estado'):
        dias = (hoy - f['fecha_venta']).days
        clave = '0-30 días' if dias <= 30 else '31-60 días' if dias <= 60 else '61-90 días' if dias <= 90 else 'más de 90 días'
        tramos[clave][0] += 1
        tramos[clave][1] += f['saldo']
        if f['estado'] == 'entregado':
            entregadas[0] += 1
            entregadas[1] += f['saldo']
    mayores = [{'venta': f['id'], 'cliente': f['cliente__nombre'], 'asesor': f['vendedor__first_name'], 'fecha_venta': str(f['fecha_venta']),
                'dias': (hoy - f['fecha_venta']).days, 'valor': _n(f['valor_total']), 'saldo': _n(f['saldo']), 'estado': f['estado'],
                'fecha_entrega': str(f['fecha_entrega']) if f['fecha_entrega'] else None}
               for f in qs.order_by('-saldo').values('id', 'cliente__nombre', 'vendedor__first_name', 'fecha_venta', 'valor_total', 'saldo', 'estado', 'fecha_entrega')[:top]]
    total = sum((t[1] for t in tramos.values()), Decimal(0))
    return {'saldo_total': _n(total), 'ventas_con_saldo': sum(t[0] for t in tramos.values()),
            'por_antiguedad': {k: {'ventas': v[0], 'saldo': _n(v[1])} for k, v in tramos.items()},
            'entregadas_con_saldo': {'ventas': entregadas[0], 'saldo': _n(entregadas[1]), 'nota': 'Mercancía ya entregada sin pago completo: mayor riesgo.'},
            'mayores_saldos': mayores}


def gestion_ventas(args):
    top = max(1, min(int(args.get('top') or 15), 40))
    hoy = business_time.hoy()
    filas = list(_ventas().exclude(estado='entregado').values('id', 'estado', 'estado_pedidos', 'fecha_venta', 'fecha_entrega', 'valor_total', 'vendedor__first_name'))
    conteo = defaultdict(int)
    recientes = []
    entregas_en_riesgo = []
    corte = hoy - timedelta(days=60)
    for f in filas:
        estado = estado_gestion(_VentaMin(f))
        conteo[estado] += 1
        if estado == 'atrasada' and f['fecha_venta'] >= corte:
            recientes.append(f)
        if estado != 'finalizada' and f['fecha_entrega'] and hoy <= f['fecha_entrega'] <= hoy + timedelta(days=21):
            entregas_en_riesgo.append(f)
    fmt = lambda f: {'venta': f['id'], 'asesor': f['vendedor__first_name'], 'fecha_venta': str(f['fecha_venta']), 'dias_desde_venta': (hoy - f['fecha_venta']).days,
                     'fecha_entrega': str(f['fecha_entrega']) if f['fecha_entrega'] else None, 'valor': _n(f['valor_total'])}
    por_asesor = defaultdict(int)
    for f in recientes:
        por_asesor[f['vendedor__first_name']] += 1
    return {'regla': f'Atrasada = sin finalizar más de {DIAS_LIMITE} días después de la venta', 'ventas_no_entregadas_por_estado': dict(conteo),
            'atrasadas_ultimos_60_dias': len(recientes), 'atrasadas_recientes_por_asesor': dict(sorted(por_asesor.items(), key=lambda x: -x[1])),
            'atrasadas_recientes': [fmt(f) for f in sorted(recientes, key=lambda f: f['fecha_venta'])[:top]],
            'entregas_proximas_21_dias_sin_gestion_finalizada': [fmt(f) for f in sorted(entregas_en_riesgo, key=lambda f: f['fecha_entrega'])[:top]],
            'nota': 'Las ventas anteriores a oct-2026 casi nunca se marcaron: su "atrasada" no siempre es un problema real.'}


def pedidos_proveedor(args):
    top = max(1, min(int(args.get('top') or 15), 40))
    hoy = business_time.hoy()
    ops = OrdenPedido.objects.all()
    por_estado = {f['estado']: f['n'] for f in ops.values('estado').annotate(n=Count('id'))}
    abiertas = ops.filter(estado__in=['pendiente', 'en_proceso'])
    vencidas = abiertas.filter(fecha_esperada__lt=hoy)
    por_proveedor = [{'proveedor': f['proveedor__nombre_empresa'], 'abiertas': f['n'], 'vencidas': f['v']}
                     for f in abiertas.values('proveedor__nombre_empresa').annotate(n=Count('id'), v=Count('id', filter=Q(fecha_esperada__lt=hoy))).order_by('-v', '-n')[:top]]
    lista = [{'op': f['id'], 'proveedor': f['proveedor__nombre_empresa'], 'venta': f['venta_id'], 'fecha_esperada': str(f['fecha_esperada']),
              'dias_de_retraso': (hoy - f['fecha_esperada']).days, 'tela': f['tela']}
             for f in vencidas.order_by('fecha_esperada').values('id', 'proveedor__nombre_empresa', 'venta_id', 'fecha_esperada', 'tela')[:top]]
    tela = {f['tela'] or 'Sin dato': f['n'] for f in abiertas.values('tela').annotate(n=Count('id'))}
    return {'por_estado': por_estado, 'abiertas': abiertas.count(), 'vencidas': vencidas.count(), 'estado_tela_de_abiertas': tela,
            'por_proveedor': por_proveedor, 'mas_vencidas': lista}


def pedidos_tela(args):
    top = max(1, min(int(args.get('top') or 15), 40))
    hoy = business_time.hoy()
    qs = PedidoTela.objects.exclude(estado='Anulado')
    por_estado = {f['estado']: f['n'] for f in qs.values('estado').annotate(n=Count('id'))}
    pendientes = qs.filter(estado='Pendiente')
    viejos = [{'pt': f['id'], 'proveedor_tela': f['proveedor__nombre_empresa'], 'creado': str(f['fecha_creacion']), 'dias': (hoy - f['fecha_creacion']).days,
               'op': f['orden_asociada_id'], 'venta': f['venta_id'] or f['orden_asociada__venta_id']}
              for f in pendientes.filter(fecha_creacion__lte=hoy - timedelta(days=7)).order_by('fecha_creacion')
              .values('id', 'proveedor__nombre_empresa', 'fecha_creacion', 'orden_asociada_id', 'venta_id', 'orden_asociada__venta_id')[:top]]
    por_proveedor = [{'proveedor_tela': f['proveedor__nombre_empresa'], 'pendientes': f['n']}
                     for f in pendientes.values('proveedor__nombre_empresa').annotate(n=Count('id')).order_by('-n')[:top]]
    sin_pedir = LineaVenta.objects.filter(tela_modo=LineaVenta.TELA_APARTE, detalles_tela__isnull=True).exclude(venta__estado__in=ANULADAS).count()
    return {'por_estado': por_estado, 'pendientes_mas_de_7_dias': viejos, 'pendientes_por_proveedor': por_proveedor,
            'productos_con_tela_aparte_sin_pedir': sin_pedir}


def finanzas(args):
    desde, hasta = _rango(args)
    hoy = business_time.hoy()
    from suministros.models import FacturaProveedor
    pagos = PagoReciboCaja.objects.filter(recibo__fecha__range=(desde, hasta)).exclude(estado='Anulado')
    recaudo = [{'medio': f['metodo_pago'], 'valor': _n(f['v']), 'pagos': f['n'], 'pendiente_confirmar': _n(f['p'])}
               for f in pagos.values('metodo_pago').annotate(v=Sum('valor', filter=Q(estado='Confirmado')), n=Count('id'), p=Sum('valor', filter=Q(estado='Pendiente'))).order_by('-v')]
    egresos_qs = ComprobanteEgreso.objects.filter(fecha__range=(desde, hasta)).exclude(estado__icontains='anul')
    egresos = egresos_qs.aggregate(t=Sum('valor'), n=Count('id'), por_confirmar=Sum('valor', filter=Q(estado='Por Confirmar Pago')))
    top_egresos = [{'beneficiario': f['proveedor__nombre_empresa'] or f['proveedor_otro_nombre'] or 'Otro', 'valor': _n(f['v'])}
                   for f in egresos_qs.values('proveedor__nombre_empresa', 'proveedor_otro_nombre').annotate(v=Sum('valor')).order_by('-v')[:10]]
    inicio_dt, _ = business_time.rango_dia_local(desde)
    _, fin_dt = business_time.rango_dia_local(hasta)
    caja = {f['tipo']: _n(f['v']) for f in Caja.objects.filter(fecha_hora__gte=inicio_dt, fecha_hora__lt=fin_dt).values('tipo').annotate(v=Sum('valor'))}
    facturas = FacturaProveedor.objects.filter(estado__in=['pendiente', 'pago_en_proceso'])
    fac = facturas.aggregate(t=Sum('valor'), n=Count('id'), vencidas=Sum('valor', filter=Q(fecha_pago__lt=hoy)), n_vencidas=Count('id', filter=Q(fecha_pago__lt=hoy)),
                             proximas=Sum('valor', filter=Q(fecha_pago__range=(hoy, hoy + timedelta(days=15)))))
    total_recaudo = sum(r['valor'] for r in recaudo)
    return {'periodo': {'desde': str(desde), 'hasta': str(hasta)},
            'recaudo_clientes': {'total_confirmado': total_recaudo, 'por_medio': recaudo, 'nota': 'Solo confirmado; pendientes separados, anulados excluidos.'},
            'egresos': {'total': _n(egresos['t']), 'comprobantes': egresos['n'], 'por_confirmar_pago': _n(egresos['por_confirmar']), 'mayores_beneficiarios': top_egresos},
            'flujo_neto_aprox': total_recaudo - _n(egresos['t']),
            'caja_movimientos_del_periodo': caja, 'saldo_actual_caja': _n(CuentaCaja.objects.filter(activa=True).aggregate(s=Sum('saldo'))['s']),
            'facturas_proveedor_por_pagar': {'total': _n(fac['t']), 'facturas': fac['n'], 'vencidas_valor': _n(fac['vencidas']), 'vencidas': fac['n_vencidas'],
                                             'vencen_proximos_15_dias': _n(fac['proximas'])}}


def inventario(args):
    from suministros.models import Inventario
    hoy = business_time.hoy()
    qs = Inventario.objects.all()
    por_disp = [{'disponibilidad': f['disponibilidad'], 'unidades': f['n'], 'costo': _n(f['c'])}
                for f in qs.values('disponibilidad').annotate(n=Count('pk'), c=Sum('costo_especifico')).order_by('-n')]
    exhibicion = qs.filter(disponibilidad='exhibicion')
    edades = {'0-90 días': 0, '91-180 días': 0, '181-365 días': 0, 'más de 1 año': 0, 'sin fecha': 0}
    for f in exhibicion.values('fecha_ingreso'):
        if not f['fecha_ingreso']:
            edades['sin fecha'] += 1
            continue
        d = (hoy - f['fecha_ingreso']).days
        edades['0-90 días' if d <= 90 else '91-180 días' if d <= 180 else '181-365 días' if d <= 365 else 'más de 1 año'] += 1
    por_zona = [{'zona': f['zona__nombre'] or 'Sin zona', 'unidades': f['n']} for f in exhibicion.values('zona__nombre').annotate(n=Count('pk')).order_by('-n')[:10]]
    return {'por_disponibilidad': por_disp, 'exhibicion_por_antiguedad': edades, 'exhibicion_por_zona': por_zona,
            'nota': 'Costo = costo de compra registrado (puede faltar en unidades antiguas).'}


def productos_mas_pedidos(args):
    desde, hasta = _rango(args)
    top = max(1, min(int(args.get('top') or 15), 40))
    detalles = DetallePedido.objects.filter(orden__fecha_creacion__range=(desde, hasta)).exclude(orden__estado='anulado')
    refs = [{'referencia': f['referencia__nombre'], 'proveedor': f['referencia__proveedor__nombre_empresa'], 'unidades': f['u'], 'ordenes': f['o']}
            for f in detalles.values('referencia__nombre', 'referencia__proveedor__nombre_empresa').annotate(u=Sum('cantidad'), o=Count('orden', distinct=True)).order_by('-u')[:top]]
    proveedores = [{'proveedor': f['orden__proveedor__nombre_empresa'], 'unidades': f['u'], 'ordenes': f['o']}
                   for f in detalles.values('orden__proveedor__nombre_empresa').annotate(u=Sum('cantidad'), o=Count('orden', distinct=True)).order_by('-u')[:top]]
    lineas = LineaVenta.objects.filter(venta__fecha_venta__range=(desde, hasta), tipo=LineaVenta.TIPO_PRODUCTO).exclude(venta__estado__in=ANULADAS)
    categorias = [{'categoria': f['categoria_nombre'] or 'Especial', 'unidades': f['u'], 'valor_lista': _n(f['l'])}
                  for f in lineas.values('categoria_nombre').annotate(u=Sum('cantidad'), l=Sum(ExpressionWrapper(F('precio_lista_unitario') * F('cantidad'), output_field=DecimalField(max_digits=20, decimal_places=2)))).order_by('-u')[:top]]
    return {'periodo': {'desde': str(desde), 'hasta': str(hasta)}, 'referencias_mas_pedidas_a_fabrica': refs, 'por_fabricante': proveedores,
            'categorias_vendidas_con_desglose': categorias, 'nota': 'Referencias según órdenes de pedido creadas en el período; categorías solo de ventas con productos registrados.'}


def clientes(args):
    desde, hasta = _rango(args)
    top = max(1, min(int(args.get('top') or 10), 30))
    qs = _ventas().filter(fecha_venta__range=(desde, hasta))
    por_cliente = list(qs.values('cliente_id', 'cliente__nombre', 'cliente__ciudad').annotate(t=Sum('valor_total'), n=Count('id')).order_by('-t'))
    ids = [c['cliente_id'] for c in por_cliente]
    recurrentes = set(_ventas().filter(cliente_id__in=ids, fecha_venta__lt=desde).values_list('cliente_id', flat=True).distinct())
    ciudades = defaultdict(lambda: [0, Decimal(0)])
    for c in por_cliente:
        ciudad = (c['cliente__ciudad'] or 'Sin ciudad').strip().title()
        ciudades[ciudad][0] += 1
        ciudades[ciudad][1] += c['t']
    return {'periodo': {'desde': str(desde), 'hasta': str(hasta)}, 'clientes_que_compraron': len(por_cliente),
            'clientes_recurrentes': len(recurrentes), 'clientes_nuevos': len(por_cliente) - len(recurrentes),
            'por_ciudad': [{'ciudad': k, 'clientes': v[0], 'valor': _n(v[1])} for k, v in sorted(ciudades.items(), key=lambda x: -x[1][1])[:10]],
            'mayores_clientes': [{'cliente': c['cliente__nombre'], 'compras': c['n'], 'valor': _n(c['t']), 'recurrente': c['cliente_id'] in recurrentes} for c in por_cliente[:top]]}


def detalle_venta(args):
    try:
        venta = Venta.objects.select_related('cliente', 'vendedor').get(pk=int(args.get('venta_id')))
    except (Venta.DoesNotExist, TypeError, ValueError):
        return {'error': 'No existe esa venta.'}
    compartidos = list(venta.vendedores_compartidos.values_list('first_name', flat=True))
    lineas = [{'tipo': l.tipo, 'producto': f'{l.cantidad} × {l.producto_nombre}{" · " + l.variante_nombre if l.variante_nombre else ""}',
               'precio_lista': _n((l.precio_lista_unitario or 0) * l.cantidad), 'tela': l.tela_modo}
              for l in venta.lineas.all()]
    ops = [{'op': o['id'], 'proveedor': o['proveedor__nombre_empresa'], 'estado': o['estado'], 'tela': o['tela'], 'fecha_esperada': str(o['fecha_esperada'])}
           for o in venta.ordenes_pedido.values('id', 'proveedor__nombre_empresa', 'estado', 'tela', 'fecha_esperada')]
    telas = [{'pt': p['id'], 'proveedor_tela': p['proveedor__nombre_empresa'], 'estado': p['estado']}
             for p in PedidoTela.objects.filter(Q(venta=venta) | Q(orden_asociada__venta=venta)).distinct().values('id', 'proveedor__nombre_empresa', 'estado')]
    pagos = {f['estado']: _n(f['v']) for f in PagoReciboCaja.objects.filter(recibo__venta=venta).values('estado').annotate(v=Sum('valor'))}
    return {'venta': venta.pk, 'cliente': venta.cliente.nombre, 'ciudad': venta.cliente.ciudad, 'asesor': venta.vendedor.first_name, 'compartida_con': compartidos,
            'sede': venta.sede, 'fecha_venta': str(venta.fecha_venta), 'fecha_entrega': str(venta.fecha_entrega), 'estado': venta.estado,
            'gestion': estado_gestion(venta), 'valor': _n(venta.valor_total), 'precio_lista': _n(venta.valor_lista) if venta.valor_lista else None,
            'descuento_pct': _pct(venta.valor_lista - venta.valor_total, venta.valor_lista) if venta.valor_lista else None,
            'abono': _n(venta.abono), 'saldo': _n(venta.saldo), 'pagos_por_estado': pagos, 'postferia': venta.es_postferia, 'feria': venta.es_feria_hogar,
            'productos': lineas, 'ordenes_de_pedido': ops, 'pedidos_de_tela': telas}


def nomina(args):
    cierre = CierreNomina.objects.filter(pk=args['cierre_id']).first() if args.get('cierre_id') else CierreNomina.objects.order_by('-fecha_fin', '-id').first()
    if not cierre:
        return {'error': 'Aún no hay cierres de nómina.'}
    filas = defaultdict(lambda: defaultdict(Decimal))
    for f in LineaNomina.objects.filter(asesor_cierre__cierre=cierre).values('asesor_cierre__asesor__first_name', 'tipo', 'pagar').annotate(v=Sum('valor')):
        fila = filas[f['asesor_cierre__asesor__first_name']]
        fila[f'{f["tipo"]}_{"a_pagar" if f["pagar"] else "pendiente"}'] += f['v'] or 0
    basicos = {f['asesor__first_name']: f['salario_basico'] for f in cierre.asesores.values('asesor__first_name', 'salario_basico')} if hasattr(cierre, 'asesores') else {}
    otros = [{'cierre': c.pk, 'nombre': c.nombre, 'estado': c.estado} for c in CierreNomina.objects.order_by('-fecha_fin')[:6]]
    return {'cierre': {'id': cierre.pk, 'nombre': cierre.nombre, 'desde': str(cierre.fecha_inicio), 'hasta': str(cierre.fecha_fin), 'estado': cierre.estado},
            'por_asesor': [{'asesor': k, **{c: _n(v) for c, v in f.items()}, 'basico': _n(basicos.get(k))} for k, f in filas.items()],
            'otros_cierres': otros}


def agenda_entregas(args):
    dias = max(1, min(int(args.get('dias') or 15), 60))
    hoy = business_time.hoy()
    qs = _ventas().filter(estado='pendiente', fecha_entrega__range=(hoy - timedelta(days=30), hoy + timedelta(days=dias)))
    filas = list(qs.order_by('fecha_entrega').values('id', 'fecha_entrega', 'saldo', 'valor_total', 'estado', 'estado_pedidos', 'fecha_venta', 'vendedor__first_name'))
    abiertas = defaultdict(int)
    for f in OrdenPedido.objects.filter(venta_id__in=[f['id'] for f in filas], estado__in=['pendiente', 'en_proceso']).values('venta_id').annotate(n=Count('id')):
        abiertas[f['venta_id']] = f['n']
    lista = [{'venta': f['id'], 'asesor': f['vendedor__first_name'], 'fecha_entrega': str(f['fecha_entrega']), 'vencida': f['fecha_entrega'] < hoy,
              'saldo': _n(f['saldo']), 'ops_abiertas': abiertas[f['id']], 'gestion': estado_gestion(_VentaMin(f))} for f in filas]
    return {'desde': str(hoy - timedelta(days=30)), 'hasta': str(hoy + timedelta(days=dias)),
            'entregas_vencidas_sin_entregar': sum(1 for f in lista if f['vencida']), 'entregas_proximas': sum(1 for f in lista if not f['vencida']),
            'saldo_a_cobrar_en_estas_entregas': sum(f['saldo'] for f in lista), 'ventas': lista[:40]}


def asignar_tarea_oficina(args, usuario=None, perfil=None, mensaje_id=None):
    """Crea una tarea formal en la plataforma asignada a un colaborador del equipo."""
    from django.db import transaction
    responsable_raw = args.get('responsable')
    if not responsable_raw:
        return {'error': 'Debes especificar el responsable de la tarea (nombre o ID).'}

    responsable = None
    if isinstance(responsable_raw, int) or (isinstance(responsable_raw, str) and responsable_raw.isdigit()):
        responsable = CustomUser.objects.filter(pk=int(responsable_raw), is_active=True).first()
    else:
        nombre_buscar = str(responsable_raw).strip()
        miembro = MiembroOficina.objects.filter(
            habilitado=True,
            usuario__is_active=True
        ).filter(
            Q(usuario__first_name__icontains=nombre_buscar) |
            Q(usuario__last_name__icontains=nombre_buscar) |
            Q(usuario__username__icontains=nombre_buscar)
        ).select_related('usuario').first()
        if miembro:
            responsable = miembro.usuario
        else:
            responsable = CustomUser.objects.filter(is_active=True).filter(
                Q(first_name__icontains=nombre_buscar) |
                Q(last_name__icontains=nombre_buscar) |
                Q(username__icontains=nombre_buscar)
            ).first()

    if not responsable:
        return {'error': f'No se encontró ningún colaborador activo con el nombre "{responsable_raw}". Usa consultar_equipo_oficina para verificar los nombres.'}

    # La intención no puede autorizarla el propio modelo mediante sus argumentos.
    # Solo una orden explícita del humano que nombra a esta persona permite asignar.
    import re, unicodedata
    from ..models import MensajeAsistente
    normalizar = lambda s: unicodedata.normalize('NFKD',s or '').encode('ascii','ignore').decode().lower()
    origen = MensajeAsistente.objects.filter(pk=mensaje_id,conversacion__usuario=usuario).first() if mensaje_id and usuario else None
    pregunta = origen.conversacion.mensajes.filter(rol='usuario',id__lt=origen.pk).order_by('-id').first() if origen else None
    texto = pregunta.texto if pregunta else ''
    from . import operaciones
    if operaciones.trabajo_actual.get():
        t, _ = operaciones.contexto()
        if t.contexto_usuario:
            texto = t.contexto_usuario[-1]['texto']
    texto = normalizar(texto)
    nombres = [normalizar(v) for v in (responsable.username,responsable.first_name,responsable.get_full_name()) if v]
    nombrado = any(re.search(r'\b'+re.escape(n)+r'\b',texto) for n in nombres)
    pedido = re.search(r'\b(?:asign\w*|encarg\w*|deleg\w*|pidel\w*)\b',texto)
    prohibido = re.search(r'\b(?:no|nunca)\b.{0,50}(?:asign|persona|manuel|deleg)',texto)
    if not (nombrado and pedido) or prohibido:
        return {'error':'El humano no pidió asignar trabajo a esta persona. Usa ejecutar_con_agente para ejecutar su solicitud; no crees una tarea humana.'}

    creador = usuario or CustomUser.objects.filter(role='administrador', is_active=True).first() or responsable
    titulo = str(args.get('titulo') or 'Nueva tarea asignada por IA')[:140].strip()
    descripcion = str(args.get('descripcion') or '')[:3000].strip()
    prioridad = 'alta' if str(args.get('prioridad', '')).lower() in ['alta', 'urgente'] else 'normal'

    fecha_limite = _fecha(args.get('fecha_limite'))
    if not fecha_limite and 'hoy' in str(args.get('fecha_limite', '')).lower():
        fecha_limite = business_time.hoy()

    venta_id = args.get('venta_id')
    if isinstance(venta_id, str) and venta_id.isdigit():
        venta_id = int(venta_id)
    elif not isinstance(venta_id, int):
        venta_id = None

    with transaction.atomic():
        t = TrabajoOficina.objects.create(
            tipo='tarea',
            creador=creador,
            responsable=responsable,
            titulo=titulo,
            descripcion=descripcion,
            prioridad=prioridad,
            fecha_limite=fecha_limite,
            venta_id=venta_id
        )
        try:
            from ..servicios import auditar
            auditar(creador, 'oficina.trabajo.crear', t, {
                'tipo': 'tarea',
                'responsable': responsable.pk,
                'origen': 'ia_asistente'
            })
        except Exception:
            pass

        try:
            InteraccionOficina.objects.create(
                actor=f'ia-{perfil.pk}' if perfil else 'ia-general',
                destino=f'persona-{responsable.pk}',
                tipo='solicitud',
                texto=f'Tarea asignada: {titulo}',
                trabajo=t
            )
        except Exception:
            pass

    return {
        'asignada': True,
        'trabajo_id': t.pk,
        'titulo': t.titulo,
        'descripcion': t.descripcion,
        'responsable': {
            'id': responsable.pk,
            'nombre': responsable.get_full_name().strip() or responsable.username,
            'rol': responsable.get_role_display()
        },
        'prioridad': t.prioridad,
        'fecha_limite': str(t.fecha_limite) if t.fecha_limite else None,
        'estado': t.estado,
        'mensaje': f'Tarea #{t.pk} creada y asignada exitosamente a {responsable.get_full_name().strip() or responsable.username}.'
    }


def consultar_equipo_oficina(args=None, usuario=None):
    """Lista las personas activas del equipo para identificar colaboradores por nombre o rol."""
    miembros = list(MiembroOficina.objects.filter(habilitado=True, usuario__is_active=True).select_related('usuario', 'zona'))
    lista = []
    for m in miembros:
        u = m.usuario
        lista.append({
            'id': u.pk,
            'nombre': u.get_full_name().strip() or u.username,
            'rol': u.get_role_display(),
            'zona': m.zona.nombre if m.zona else 'Sin zona'
        })
    if not lista:
        for u in CustomUser.objects.filter(is_active=True)[:25]:
            lista.append({
                'id': u.pk,
                'nombre': u.get_full_name().strip() or u.username,
                'rol': u.get_role_display(),
                'zona': 'General'
            })
    from ..models import PerfilAsistente
    agentes = [{'id':p.pk,'nombre':p.nombre,'tipo':'agente_ia','ejecutor':p.clave_sistema=='ejecutor','zona':p.zona.nombre if p.zona else None}
        for p in PerfilAsistente.objects.filter(activo=True).select_related('zona')]
    return {'equipo': lista, 'total': len(lista),'agentes_ia':agentes,'nota':'Los agentes IA no son usuarios humanos. Para ejecutar usa ejecutar_con_agente.'}


# --- Declaraciones para Gemini --------------------------------------------------

_RANGO = {'desde': {'type': 'string', 'description': 'Fecha inicial AAAA-MM-DD. Por defecto, inicio del período comercial actual.'},
          'hasta': {'type': 'string', 'description': 'Fecha final AAAA-MM-DD (incluida). Por defecto, fin del período comercial actual.'}}
_TOP = {'top': {'type': 'integer', 'description': 'Cuántos elementos listar (por defecto 15).'}}

HERRAMIENTAS = {
    'consultar_pagina_web': (web.consultar, 'Consulta el sitio público LOTTUS: índice de archivos, textos, enlaces, SEO, diseño, catálogo vigente y asesores publicados. Solo lectura. El código local puede diferir del despliegue. Usa sección archivos para descubrir rutas, y pagina para continuar.',
        {'proyecto': {'type':'string','enum':['web','landing','gestion','backend_web']},
         'seccion': {'type':'string','enum':['resumen','archivos','contenido','diseno','catalogo','asesores']},
         'archivo': {'type':'string','description':'Ruta HTML del índice para consultar una página específica.'},
         'buscar': {'type':'string','description':'Filtrar archivos o productos por nombre.'},
         'categoria': {'type':'string','description':'Categoría del catálogo.'},
         'limite': {'type':'integer','description':'Productos por página, de 1 a 5; por defecto 3.'},
         'pagina': {'type':'integer','description':'Página de archivos o catálogo, desde 1.'}}),
    'leer_codigo_pagina_web': (web.leer_codigo, 'Lee el código real HTML, CSS, JS, React y Python de la web, su gestión y API, numerado por líneas. Elige proyecto y archivo del índice; continua con siguiente_linea. No modifica ni ejecuta código.',
        {'proyecto': {'type':'string','enum':['web','landing','gestion','backend_web']}, 'archivo': {'type':'string'},
         'desde_linea': {'type':'integer'}, 'lineas': {'type':'integer','description':'De 1 a 160; por defecto 100.'}}),
    'ver_imagen_pagina_web': (web.ver_imagen, 'Ve una imagen real del sitio para analizar fotografía, composición y marca. Elige archivo del índice o producto publicado por ID/slug e indice de su imagen. No es una captura del navegador. Máximo tres imágenes por respuesta.',
        {'proyecto': {'type':'string','enum':['web','landing']}, 'archivo': {'type':'string'},
         'producto': {'type':'string'}, 'indice': {'type':'integer','description':'Imagen del producto, desde 0.'}}),
    'consulta_datos': (analitica.consultar, 'Consulta precisa de agregados en la base: filtros, agrupación y totales. Preferir a traer registros. Fechas incluidas; devuelve hasta 50 grupos y avisa truncamiento. Solo lectura.', analitica.PROPIEDADES),
    'resumen_ventas': (resumen_ventas, 'Resumen de ventas de un rango: número, valor vendido, ticket, abonado, saldo, entregas, sedes, feria/postferia, descuento sobre lista y estado de gestión.',
                       {**_RANGO, 'sede': {'type': 'string', 'description': 'Opcional: "Lottus 1" o "Lottus 2".'}}),
    'ventas_por_asesor': (ventas_por_asesor, 'Desempeño por asesor en un rango (ventas compartidas divididas Total/N): total, participación, ticket, descuento promedio, saldo y cumplimiento de meta.', _RANGO),
    'tendencia_ventas': (tendencia_ventas, 'Ventas por período comercial (6 al 5) de los últimos N períodos, para tendencias y comparativos.',
                         {'periodos': {'type': 'integer', 'description': 'Cuántos períodos (2 a 24, por defecto 12).'}}),
    'saldos_por_cobrar': (saldos_por_cobrar, 'Saldos pendientes de clientes: total, antigüedad, entregadas con saldo y mayores saldos.', _TOP),
    'gestion_ventas': (gestion_ventas, 'Estado de la gestión de ventas no entregadas: atrasadas recientes por asesor y entregas próximas sin gestión finalizada.', _TOP),
    'pedidos_proveedor': (pedidos_proveedor, 'Órdenes de pedido a fabricantes: por estado, abiertas, vencidas, por proveedor y estado de tela.', _TOP),
    'pedidos_tela': (pedidos_tela, 'Pedidos de tela y cuero: por estado, pendientes viejos, por proveedor y productos con tela por pedir.', _TOP),
    'finanzas': (finanzas, 'Recaudo por medio de pago, egresos, flujo neto, caja y facturas de proveedor por pagar/vencidas en un rango.', _RANGO),
    'inventario': (inventario, 'Inventario por disponibilidad (cliente, exhibición, por despachar…), antigüedad de la exhibición y zonas.', {}),
    'productos_mas_pedidos': (productos_mas_pedidos, 'Referencias y fabricantes más pedidos en un rango y categorías vendidas (ventas con desglose).', {**_RANGO, **_TOP}),
    'clientes': (clientes, 'Clientes de un rango: nuevos vs recurrentes, ciudades y mayores clientes.', {**_RANGO, **_TOP}),
    'detalle_venta': (detalle_venta, 'Detalle completo de una venta por su número: pagos, productos, órdenes, telas y gestión.',
                      {'venta_id': {'type': 'integer', 'description': 'Número de la venta (OC).'}}),
    'nomina': (nomina, 'Nómina de asesores: comisiones, bonificaciones y ajustes del último cierre (o del indicado).',
               {'cierre_id': {'type': 'integer', 'description': 'Opcional: id del cierre.'}}),
    'agenda_entregas': (agenda_entregas, 'Entregas pendientes vencidas y próximas, con saldo a cobrar, órdenes abiertas y gestión.',
                        {'dias': {'type': 'integer', 'description': 'Días hacia adelante (por defecto 15).'}}),
    'asignar_tarea_oficina': (asignar_tarea_oficina, 'Asigna una tarea humana únicamente si el usuario pide expresamente asignarla y nombra al destinatario. Para ejecutar operaciones del usuario usa ejecutar_con_agente.',
                              {'responsable': {'type': 'string', 'description': 'Nombre o ID del colaborador expresamente indicado por el usuario.'},
                               'titulo': {'type': 'string', 'description': 'Título conciso y claro de la tarea (máx. 140 caracteres).'},
                               'descripcion': {'type': 'string', 'description': 'Instrucciones y especificaciones detalladas de la tarea.'},
                               'prioridad': {'type': 'string', 'description': 'Prioridad ("normal" o "alta"). Por defecto normal.'},
                               'fecha_limite': {'type': 'string', 'description': 'Fecha objetivo AAAA-MM-DD (ej. hoy).'},
                               'venta_id': {'type': 'integer', 'description': 'Opcional: ID de la venta relacionada si aplica.'}}),
    'consultar_equipo_oficina': (consultar_equipo_oficina, 'Consulta las personas activas del equipo de oficina (nombres, roles e IDs) para identificar con precisión a quién asignar tareas.', {}),
}

NOMBRES_VISIBLES = {
    'ejecutar_con_agente':'Ejecución con Agente', 'consultar_formulario':'Consulta del formulario real',
    'consultar_registros_plataforma':'Consulta de registros', 'ejecutar_operacion_plataforma':'Operación en la plataforma',
    'registrar_ventas_con_productos':'Registro de ventas y productos', 'solicitar_datos_operacion':'Datos para continuar',
    'consultar_ejecucion_agente':'Resultado de Agente',
    'consultar_pagina_web':'Consulta de página web', 'leer_codigo_pagina_web':'Código de la página web',
    'ver_imagen_pagina_web':'Análisis visual de la web',
    'crear_curso': 'Creación de curso en la Academia',
    'consulta_datos': 'Consulta analítica', 'graficar_consulta': 'Gráfico de datos',
    'resumen_ventas': 'Resumen de ventas', 'ventas_por_asesor': 'Ventas por asesor', 'tendencia_ventas': 'Tendencia de ventas',
    'saldos_por_cobrar': 'Saldos por cobrar', 'gestion_ventas': 'Gestión de ventas', 'pedidos_proveedor': 'Pedidos a proveedores',
    'pedidos_tela': 'Pedidos de tela', 'finanzas': 'Finanzas', 'inventario': 'Inventario', 'productos_mas_pedidos': 'Productos más pedidos',
    'clientes': 'Clientes', 'detalle_venta': 'Detalle de venta', 'nomina': 'Nómina', 'agenda_entregas': 'Agenda de entregas',
    'asignar_tarea_oficina': 'Asignación de tarea en oficina', 'consultar_equipo_oficina': 'Consulta de equipo en oficina',
}


# Áreas de datos que se pueden habilitar a un perfil de IA. consulta_datos queda limitada
# a los dominios de las áreas habilitadas. None (IA Lottus general) = todas.
AREAS = {
    'pagina_web': {'nombre': 'Página web', 'descripcion': 'Contenido publicado, catálogo, imágenes, diseño visual y código de la web y su gestión (frontend y backend). Solo consulta.',
                   'herramientas': ['consultar_pagina_web', 'leer_codigo_pagina_web', 'ver_imagen_pagina_web'], 'dominios': []},
    'operaciones': {'nombre': 'Operaciones y tareas', 'descripcion': 'Ejecución de formularios con el agente ejecutor (Alan), consulta del equipo y tareas humanas por petición expresa.',
                    'herramientas': ['asignar_tarea_oficina', 'consultar_equipo_oficina'], 'dominios': []},
    'formacion': {'nombre': 'Academia y cursos', 'descripcion': 'Crear cursos, investigar fuentes y generar lecciones, evaluaciones y videos en Gemini Notebook.',
                  'herramientas': [], 'dominios': []},
    'ventas': {'nombre': 'Ventas y asesores', 'descripcion': 'Ventas, desempeño de asesores, tendencias, gestión, entregas y productos vendidos.',
               'herramientas': ['resumen_ventas', 'ventas_por_asesor', 'tendencia_ventas', 'gestion_ventas', 'detalle_venta',
                                'agenda_entregas', 'productos_mas_pedidos'], 'dominios': ['ventas', 'productos']},
    'cobros': {'nombre': 'Cobros y cartera', 'descripcion': 'Saldos por cobrar, antigüedad y pagos recibidos por medio de pago.',
               'herramientas': ['saldos_por_cobrar'], 'dominios': ['cobros']},
    'pedidos': {'nombre': 'Pedidos y telas', 'descripcion': 'Órdenes a fabricantes, atrasos, proveedores y pedidos de tela o cuero.',
                'herramientas': ['pedidos_proveedor', 'pedidos_tela'], 'dominios': ['pedidos']},
    'finanzas': {'nombre': 'Caja y finanzas', 'descripcion': 'Recaudo, egresos, flujo de caja y facturas de proveedor por pagar.',
                 'herramientas': ['finanzas'], 'dominios': []},
    'inventario': {'nombre': 'Inventario', 'descripcion': 'Unidades por disponibilidad, exhibición y zonas.',
                   'herramientas': ['inventario'], 'dominios': ['inventario']},
    'clientes': {'nombre': 'Clientes', 'descripcion': 'Clientes nuevos y recurrentes, ciudades y mayores compradores.',
                 'herramientas': ['clientes'], 'dominios': []},
    'nomina': {'nombre': 'Nómina', 'descripcion': 'Comisiones, bonificaciones y ajustes de asesores.',
               'herramientas': ['nomina'], 'dominios': []},
}


def permitidas(areas=None):
    """(herramientas, dominios de consulta_datos) habilitados para esas áreas."""
    if areas is None:
        return set(HERRAMIENTAS), set(analitica.DIMENSIONES)
    nombres, dominios = set(), set()
    for area in areas:
        if area in AREAS:
            nombres.update(AREAS[area]['herramientas'])
            dominios.update(AREAS[area]['dominios'])
    if dominios:
        nombres.add('consulta_datos')
    return nombres, dominios


def declaraciones(areas=None):
    nombres, dominios = permitidas(areas)
    funciones = []
    for nombre, (_, desc, props) in HERRAMIENTAS.items():
        if nombre not in nombres:
            continue
        if nombre == 'consulta_datos' and areas is not None:
            props = {**props, 'dominio': {**props['dominio'], 'enum': [d for d in analitica.DIMENSIONES if d in dominios]}}
        funciones.append({'name': nombre, 'description': desc, 'parameters': {'type': 'object', 'properties': props}} if props else {'name': nombre, 'description': desc})
    if not funciones:
        return []
    return [{'functionDeclarations': funciones + [graficos.DECLARACION]}]


def ejecutar(nombre, argumentos, areas=None, usuario=None, perfil=None, mensaje_id=None):
    if nombre not in HERRAMIENTAS:
        return {'error': f'Herramienta desconocida: {nombre}'}
    nombres, dominios = permitidas(areas)
    if nombre not in nombres or (nombre == 'consulta_datos' and (argumentos or {}).get('dominio', 'ventas') not in dominios):
        return {'error': 'Este perfil no tiene acceso a esos datos. Dilo al usuario y sugiere otro perfil o la IA Lottus general.'}
    for intento in range(2):
        # Mientras Gemini piensa, la base remota puede cerrar la conexión por inactividad:
        # se descarta la conexión caída y se reintenta una vez con una nueva.
        # Nunca dentro de una transacción: cerrar ahí rompería la transacción en curso.
        en_transaccion = connection.in_atomic_block
        if not en_transaccion:
            connection.close_if_unusable_or_obsolete()
        try:
            fn = HERRAMIENTAS[nombre][0]
            if nombre == 'asignar_tarea_oficina':
                return fn(argumentos or {}, usuario=usuario, perfil=perfil, mensaje_id=mensaje_id)
            if nombre == 'consultar_equipo_oficina':
                return fn(argumentos or {}, usuario=usuario)
            return fn(argumentos or {})
        except (ValueError, TypeError) as exc:
            return {'error': str(exc)[:250] if nombre == 'consulta_datos' or nombre in AREAS['pagina_web']['herramientas'] else 'Parámetros inválidos para la consulta.'}
        except (InterfaceError, OperationalError) as exc:
            if not en_transaccion:
                connection.close()
            if intento or en_transaccion:
                return {'error': f'No se pudo consultar la base de datos ({exc.__class__.__name__}).'}
        except Exception as exc:  # una consulta fallida no debe tumbar la respuesta
            return {'error': f'No se pudo consultar ({exc.__class__.__name__}).'}
