"""Consultas compartidas por pantallas y exportaciones operativas."""
from datetime import date
from django.db.models import Q, Exists, OuterRef, Case, When, Value, IntegerField
from rest_framework.exceptions import ValidationError
from . import business_time
from .models import Venta, ReciboCaja, PagoReciboCaja, ComprobanteEgreso
from .permissions import ventas_visibles


FILTROS = {
    'ventas': ('search', 'periods', 'start_date', 'end_date', 'month', 'year', 'estado', 'vendedor', 'excluir_vendedores', 'sede', 'es_feria_hogar'),
    'recibos': ('fecha_inicio', 'fecha_fin', 'medio_pago', 'venta_id', 'venta', 'query'),
    'egresos': ('fecha_inicio', 'fecha_fin', 'medio_pago', 'medios_pago', 'proveedor', 'proveedores', 'estado', 'estados', 'query'),
    'inventario': ('proveedor', 'search', 'categoria', 'subcategoria', 'disponibilidad', 'sede', 'zona', 'estado_fisico', 'fecha_inicio', 'fecha_fin'),
}


def validar_filtros(params):
    for campo in set(sum(FILTROS.values(), ())):
        valor = params.get(campo)
        if valor and len(str(valor)) > 1000:
            raise ValidationError({campo: 'Filtro demasiado largo (máximo 1000 caracteres).'})
    for campo in ('fecha_inicio', 'fecha_fin', 'start_date', 'end_date'):
        if params.get(campo):
            try:
                date.fromisoformat(params[campo])
            except ValueError:
                raise ValidationError({campo: 'Usa una fecha válida YYYY-MM-DD.'})
    for inicio, fin in [('fecha_inicio', 'fecha_fin'), ('start_date', 'end_date')]:
        if params.get(inicio) and params.get(fin) and params[inicio] > params[fin]:
            raise ValidationError({fin: 'La fecha final no puede ser anterior a la inicial.'})
    for campo in ('vendedor', 'excluir_vendedores', 'proveedor', 'proveedores', 'venta_id', 'venta', 'categoria', 'subcategoria', 'zona'):
        if params.get(campo):
            for token in str(params[campo]).split(','):
                if not token.strip():
                    continue
                try:
                    numero = int(token)
                    if not -1 <= numero <= 9223372036854775807:
                        raise ValueError
                except ValueError:
                    raise ValidationError({campo: 'Identificador inválido.'})
    for campo in ('search', 'query'):
        valor = params.get(campo, '')
        if valor.isdigit() and (len(valor) > 19 or not valor.isascii() or int(valor) > 9223372036854775807):
            raise ValidationError({campo: 'Identificador numérico fuera de rango.'})
    if params.get('periods'):
        for periodo in params['periods'].split(','):
            try:
                mes, anio = map(int, periodo.strip().split('-'))
                date(anio, mes, 6)
                if anio >= 9999:
                    raise ValueError
            except (ValueError, TypeError):
                raise ValidationError({'periods': 'Usa períodos mes-año válidos.'})


def consultar_ventas(request):
    validar_filtros(request.query_params)
    # OPTIMIZACIÓN: Iniciar con la consulta optimizada (select_related + prefetch_related)
    ventas = Venta.objects.select_related('cliente', 'vendedor').prefetch_related('vendedores_compartidos', 'lineas').all()

    # Alcance por objeto (propias/compartidas o todas) sin importar los filtros
    # o la búsqueda que envíe el cliente; misma regla en consulta y escritura.
    ventas = ventas_visibles(request, ventas)

    search_query = request.GET.get('search')

    if search_query:
        # Búsqueda exacta por ID cuando el término es numérico (id__icontains fuerza CAST + full scan)
        search_filter = Q(cliente__nombre__icontains=search_query)
        if str(search_query).isdigit():
            search_filter |= Q(id=int(search_query))
        ventas = ventas.filter(search_filter)
    else:
        # ... (lógica de filtrado por fecha, estado, etc. se mantiene igual)
        periods_param = request.GET.get('periods')
        start_date_param = request.GET.get('start_date')
        end_date_param = request.GET.get('end_date')
        
        # Backward compatibility for old fetch endpoints (e.g. reportSales if not updated yet)
        month_param = request.GET.get('month')
        year_param = request.GET.get('year')

        estado = request.GET.get('estado')
        vendedor_id_param = request.GET.get('vendedor')
        excluir_param = request.GET.get('excluir_vendedores')
        sede_param = request.GET.get('sede')
        feria_param = request.GET.get('es_feria_hogar')

        if periods_param:
            periods = [p.strip() for p in periods_param.split(',') if p.strip()]
            q_objects = Q()
            try:
                for period in periods:
                    parts = period.split('-')
                    if len(parts) == 2:
                        month = int(parts[0])
                        year = int(parts[1])
                        
                        start_day = 6
                        end_day = 5
                        
                        period_start = date(year, month, start_day)
                        
                        if month == 12:
                            period_end = date(year + 1, 1, end_day)
                        else:
                            period_end = date(year, month + 1, end_day)
                        
                        q_objects |= Q(fecha_venta__gte=period_start, fecha_venta__lte=period_end)
                
                if q_objects:
                    ventas = ventas.filter(q_objects)
                    
            except ValueError:
                raise ValidationError({"error": "Parámetros de mes o año inválidos en periods."})
        
        elif start_date_param or end_date_param:
            try:
                if start_date_param and end_date_param:
                    start_date = date.fromisoformat(start_date_param)
                    end_date = date.fromisoformat(end_date_param)
                    ventas = ventas.filter(fecha_venta__gte=start_date, fecha_venta__lte=end_date)
                elif start_date_param:
                    start_date = date.fromisoformat(start_date_param)
                    end_date = business_time.hoy()
                    ventas = ventas.filter(fecha_venta__gte=start_date, fecha_venta__lte=end_date)
                elif end_date_param:
                    end_date = date.fromisoformat(end_date_param)
                    ventas = ventas.filter(fecha_venta__lte=end_date)
            except ValueError:
                raise ValidationError({"error": "Formato de fecha inválido."})
                
        elif month_param and year_param:
            try:
                month = int(month_param)
                year = int(year_param)

                start_day = 6
                end_day = 5

                start_date = date(year, month, start_day)

                if month == 12:
                    end_date = date(year + 1, 1, end_day)
                else:
                    end_date = date(year, month + 1, end_day)
                
                ventas = ventas.filter(fecha_venta__gte=start_date, fecha_venta__lte=end_date)

            except ValueError:
                raise ValidationError({"error": "Parámetros de mes o año inválidos."})

        if estado:
            if ',' in estado:
                estados_list = [e.strip() for e in estado.split(',') if e.strip()]
                ventas = ventas.filter(estado__in=estados_list)
            else:
                ventas = ventas.filter(estado=estado)
        
        if vendedor_id_param:
            try:
                if ',' in str(vendedor_id_param):
                    vendedores_list = [int(v.strip()) for v in str(vendedor_id_param).split(',') if v.strip()]
                    ventas = ventas.filter(Q(vendedor_id__in=vendedores_list) | Q(vendedores_compartidos__id__in=vendedores_list)).distinct()
                else:
                    vendedor_id = int(vendedor_id_param)
                    ventas = ventas.filter(Q(vendedor_id=vendedor_id) | Q(vendedores_compartidos__id=vendedor_id)).distinct()
            except ValueError:
                raise ValidationError({"error": "ID de vendedor inválido."})

        if excluir_param:
            # Filtro de Ventas por exclusión: por defecto entran todos (también quienes ya
            # no están activos) y solo se quitan los que el usuario desmarca. Una venta
            # compartida sigue apareciendo mientras alguno de sus participantes no esté
            # excluido.
            excluidos = [int(v) for v in str(excluir_param).split(',') if v.strip()]
            if excluidos:
                otro_participante = Venta.vendedores_compartidos.through.objects.filter(
                    venta_id=OuterRef('pk')).exclude(customuser_id__in=excluidos)
                ventas = ventas.filter(
                    (Q(vendedor_id__isnull=False) & ~Q(vendedor_id__in=excluidos)) | Exists(otro_participante))

        if sede_param:
            # Las ventas sin sede (sede=None) son de Feria del Hogar y no pertenecen a
            # ninguna sede — el filtro de Sede nunca debe ocultarlas, eso lo controla
            # únicamente el filtro es_feria_hogar.
            if ',' in str(sede_param):
                sedes_list = [s.strip() for s in str(sede_param).split(',') if s.strip()]
                ventas = ventas.filter(Q(sede__in=sedes_list) | Q(sede__isnull=True))
            else:
                ventas = ventas.filter(Q(sede=sede_param) | Q(sede__isnull=True))

        if feria_param is not None:
            tokens = [t.strip().lower() for t in str(feria_param).split(',') if t.strip()]
            bool_values = [t == 'true' for t in tokens if t in ('true', 'false')]
            if bool_values:
                ventas = ventas.filter(es_feria_hogar__in=bool_values)
            else:
                ventas = ventas.filter(pk__in=[])

    ventas = ventas.order_by('-fecha_venta', '-id')

    return ventas

def consultar_recibos_caja(request):
    validar_filtros(request.query_params)
    # OPTIMIZACIÓN: Cargar datos del cliente y priorizar los recibos con algún pago
    # pendiente primero — como estado/metodo_pago/valor ahora viven en PagoReciboCaja
    # (un recibo puede tener varias líneas), "pendiente" se resuelve con un Exists.
    recibos = ReciboCaja.objects.select_related('venta__cliente', 'venta__vendedor').prefetch_related(
        'venta__vendedores_compartidos', 'pagos'
    ).annotate(
        tiene_pendiente=Exists(PagoReciboCaja.objects.filter(recibo=OuterRef('pk'), estado='Pendiente')),
        orden_estado=Case(
            When(tiene_pendiente=True, then=Value(0)),
            default=Value(1),
            output_field=IntegerField(),
        )
    ).order_by('orden_estado', '-fecha', '-id')

    recibos = recibos.filter(venta_id__in=ventas_visibles(request).values('pk'))

    fecha_inicio = request.GET.get('fecha_inicio')
    fecha_fin = request.GET.get('fecha_fin')
    medio_pago = request.GET.get('medio_pago')
    venta_id_param = request.GET.get('venta_id') or request.GET.get('venta')
    query = request.GET.get('query')

    if fecha_inicio:
        recibos = recibos.filter(fecha__gte=fecha_inicio)
    if fecha_fin:
        recibos = recibos.filter(fecha__lte=fecha_fin)
    if medio_pago:
        recibos = recibos.filter(pagos__metodo_pago=medio_pago).distinct()
    if venta_id_param:
        try:
            v_id = int(venta_id_param)
            recibos = recibos.filter(venta__id=v_id)
        except ValueError:
            raise ValidationError({'venta_id': 'Identificador inválido.'})
    if query:
        recibos_filter = Q(venta__cliente__nombre__icontains=query)
        if str(query).isdigit():
            recibos_filter |= Q(id=int(query)) | Q(venta__id=int(query))
        recibos = recibos.filter(recibos_filter)

    return recibos

def consultar_comprobantes_egreso(request):
    validar_filtros(request.query_params)
    from django.db.models import Prefetch
    from suministros.models import FacturaProveedor, Inventario

    # select_related (JOIN, 1 query) para los items en vez de 3 prefetch_related
    # encadenados (3 round-trips extra) — con la BD remota cada query cuenta.
    items_qs = Inventario.objects.select_related('referencia', 'categoria', 'subcategoria')
    facturas_qs = FacturaProveedor.objects.prefetch_related(Prefetch('items_inventario', queryset=items_qs))

    egresos = ComprobanteEgreso.objects.select_related('proveedor').prefetch_related(
        Prefetch('facturas', queryset=facturas_qs),
    ).order_by('-fecha', '-id')

    fecha_inicio = request.GET.get('fecha_inicio')
    fecha_fin = request.GET.get('fecha_fin')
    medio_pago_param = request.GET.get('medio_pago') or request.GET.get('medios_pago')
    proveedor_param = request.GET.get('proveedor') or request.GET.get('proveedores')
    estado_param = request.GET.get('estado') or request.GET.get('estados')
    query = request.GET.get('query')

    if fecha_inicio:
        egresos = egresos.filter(fecha__gte=fecha_inicio)
    if fecha_fin:
        egresos = egresos.filter(fecha__lte=fecha_fin)

    if medio_pago_param:
        medios = [m.strip() for m in medio_pago_param.split(',') if m.strip()]
        if medios:
            egresos = egresos.filter(medio_pago__in=medios)

    if estado_param:
        estados = [e.strip() for e in estado_param.split(',') if e.strip()]
        if estados:
            expanded = set(estados)
            if 'Por Confirmar Pago' in expanded or 'Por Confirmar' in expanded:
                expanded.add('Por Confirmar Pago')
                expanded.add('Por Confirmar')
            egresos = egresos.filter(estado__in=list(expanded))

    if proveedor_param:
        prov_ids = [p.strip() for p in proveedor_param.split(',') if p.strip().isdigit()]
        if prov_ids:
            egresos = egresos.filter(proveedor__id__in=prov_ids)

    if query:
        q_filter = Q(concepto__icontains=query) | Q(descripcion__icontains=query) | Q(proveedor__nombre_empresa__icontains=query)
        if str(query).isdigit():
            q_filter |= Q(id=int(query))
        egresos = egresos.filter(q_filter)

    return egresos

def consultar_inventario(request):
    from django.db.models import CharField
    from django.db.models.functions import Coalesce, Cast
    from suministros.models import Inventario

    p = request.query_params
    validar_filtros(p)
    qs = Inventario.objects.select_related('referencia__proveedor', 'factura__proveedor', 'categoria', 'subcategoria', 'grupo', 'zona__sede').annotate(
        proveedor_exportacion=Coalesce('referencia__proveedor_id', 'factura__proveedor_id'),
        grupo_texto=Cast('grupo_id', output_field=CharField()),
    )
    if p.get('proveedor'):
        grupos = qs.filter(proveedor_exportacion=p['proveedor'], grupo__isnull=False).values('grupo_id')
        qs = qs.filter(Q(proveedor_exportacion=p['proveedor']) | Q(grupo_id__in=grupos))
    for campo in ('categoria', 'subcategoria'):
        if p.get(campo):
            qs = qs.filter(Q(**{campo + '_id': p[campo]}) | Q(**{'grupo__' + campo + '_id': p[campo]}))
    for campo, lookup in [('disponibilidad', 'disponibilidad'), ('zona', 'zona_id'), ('sede', 'zona__sede_id'), ('estado_fisico', 'estado_fisico')]:
        if p.get(campo):
            if campo == 'sede' and (not p[campo].isascii() or not p[campo].isdigit() or len(p[campo]) > 19 or int(p[campo]) > 9223372036854775807):
                raise ValidationError({'sede': 'Identificador inválido.'})
            qs = qs.filter(**{lookup: p[campo]})
    if p.get('fecha_inicio'):
        qs = qs.filter(Q(fecha_ingreso__gte=p['fecha_inicio']) | Q(fecha_ingreso__isnull=True))
    if p.get('fecha_fin'):
        qs = qs.filter(Q(fecha_ingreso__lte=p['fecha_fin']) | Q(fecha_ingreso__isnull=True))
    if p.get('search'):
        consulta = Q()
        for campo in ('referencia__nombre', 'categoria__nombre', 'subcategoria__nombre', 'variacion', 'id_referencia', 'observacion', 'grupo__nombre', 'grupo_texto', 'grupo__observacion'):
            consulta |= Q(**{campo + '__icontains': p['search']})
        consulta |= Q(factura__id_manual__icontains=p['search']) | Q(factura__isnull=True, factura_manual__icontains=p['search'])
        qs = qs.filter(consulta)
    return qs.order_by('id_referencia')
