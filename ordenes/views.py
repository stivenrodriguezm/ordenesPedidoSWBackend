# ==================== ordenes/views.py (CORRECCIÓN FINAL-FINAL) ====================

import logging
from rest_framework import viewsets, status, generics

logger = logging.getLogger(__name__)
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django.http import HttpResponse
from .models import (
    Referencia, Proveedor, OrdenPedido, DetallePedido, CustomUser, Cliente,
    Venta, ObservacionVenta, Caja, ReciboCaja, ComprobanteEgreso,
    ObservacionCliente, Remision
)
from .serializers import (
    ReferenciaSerializer, ProveedorSerializer, OrdenPedidoSerializer,
    DetallePedidoSerializer, ClienteSerializer, VentaSerializer,
    ObservacionVentaSerializer, CajaSerializer, ReciboCajaSerializer,
    ComprobanteEgresoSerializer, VentaDetalleSerializer,
    ObservacionClienteSerializer, RemisionSerializer
)
from .permissions import IsAdmin
from django.db import transaction
from django.db.models import Q, F, Sum, Sum
from rest_framework.exceptions import ValidationError
from datetime import date, timedelta
from django.utils import timezone
import calendar
import django_filters
from rest_framework.pagination import PageNumberPagination

@api_view(['POST'])
@permission_classes([IsAuthenticated])
@transaction.atomic
def cierre_caja(request):
    user = request.user
    descuadre = request.data.get('descuadre')

    last_movement = Caja.objects.order_by('-fecha_hora').first()
    total_acumulado = last_movement.total_acumulado if last_movement else 0

    if descuadre and float(descuadre) != 0:
        formatted_descuadre = f"${float(descuadre):,.0f}"
        concepto = f"Cierre de caja por {user.first_name}, descuadre de {formatted_descuadre}"
    else:
        concepto = f"Cierre de caja exitoso por {user.first_name}"

    Caja.objects.create(
        usuario=user,
        concepto=concepto,
        valor=0,
        tipo='cierre',
        total_acumulado=total_acumulado
    )
    return Response({"message": "Cierre de caja registrado exitosamente."}, status=status.HTTP_201_CREATED)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dashboard_stats(request):
    today = date.today()
    
    # Ventas del día (considerando solo ventas no anuladas)
    ventas_dia = Venta.objects.filter(fecha_venta=today).exclude(estado='anulado').aggregate(total=Sum('valor_total'))['total'] or 0

    # Ventas del mes actual (considerando solo ventas no anuladas)
    start_of_month = today.replace(day=1)
    ventas_mes = Venta.objects.filter(fecha_venta__gte=start_of_month).exclude(estado='anulado').aggregate(total=Sum('valor_total'))['total'] or 0

    # Órdenes abiertas
    ordenes_abiertas = OrdenPedido.objects.filter(estado='en_proceso').count()

    # Saldo en Caja
    ultimo_movimiento_caja = Caja.objects.order_by('-fecha_hora').first()
    saldo_caja = ultimo_movimiento_caja.total_acumulado if ultimo_movimiento_caja else 0
    
    # Últimas 5 ventas
    ultimas_ventas = Venta.objects.select_related('cliente').order_by('-fecha_venta', '-id')[:5]
    ultimas_ventas_serializer = VentaSerializer(ultimas_ventas, many=True)

    data = {
        'ventas_dia': ventas_dia,
        'ventas_mes': ventas_mes,
        'ordenes_abiertas': ordenes_abiertas,
        'saldo_caja': saldo_caja,
        'ultimas_ventas': ultimas_ventas_serializer.data
    }
    return Response(data)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def sales_chart_data(request):
    today = date.today()
    current_year = today.year
    last_year = current_year - 1

    # Ventas del año actual y anterior, excluyendo anuladas
    sales_current_year = Venta.objects.filter(fecha_venta__year=current_year).exclude(estado='anulado')
    sales_last_year = Venta.objects.filter(fecha_venta__year=last_year).exclude(estado='anulado')

    # Agrupar por mes y sumar
    current_year_data = {i: 0 for i in range(1, 13)}
    last_year_data = {i: 0 for i in range(1, 13)}

    current_sales_by_month = sales_current_year.values('fecha_venta__month').annotate(total=Sum('valor_total'))
    for item in current_sales_by_month:
        current_year_data[item['fecha_venta__month']] = item['total']

    last_sales_by_month = sales_last_year.values('fecha_venta__month').annotate(total=Sum('valor_total'))
    for item in last_sales_by_month:
        last_year_data[item['fecha_venta__month']] = item['total']

    # Formatear para el gráfico
    labels = [calendar.month_abbr[i].capitalize() for i in range(1, 13)]
    # Reordenar para que empiece en Diciembre
    december_index = 11
    ordered_labels = labels[december_index:] + labels[:december_index]
    ordered_current_year_data = list(current_year_data.values())[december_index:] + list(current_year_data.values())[:december_index]
    ordered_last_year_data = list(last_year_data.values())[december_index:] + list(last_year_data.values())[:december_index]

    chart_data = {
        'labels': ordered_labels,
        'datasets': [
            {
                'label': f'Ventas {last_year}',
                'data': ordered_last_year_data,
                'backgroundColor': '#ffc107', # Amarillo oscuro
            },
            {
                'label': f'Ventas {current_year}',
                'data': ordered_current_year_data,
                'backgroundColor': '#007bff', # Azul
            }
        ]
    }
    return Response(chart_data)


# ... (El resto del código de paginación y vistas de utilidad no cambia) ...
class StandardResultsSetPagination(PageNumberPagination):
    page_size = 30
    page_size_query_param = 'page_size'
    max_page_size = 100

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def listar_vendedores(request):
    vendedores = CustomUser.objects.filter(is_active=True).only('id', 'first_name')
    data = [{"id": v.id, "first_name": v.first_name} for v in vendedores]
    return Response(data)

class UserDetailView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        user = request.user
        return Response({
            "id": user.id, "username": user.username, "first_name": user.first_name,
            "last_name": user.last_name, "role": user.role,
        })

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def cambiar_contrasena(request):
    user = request.user
    old_password = request.data.get("old_password")
    new_password = request.data.get("new_password")
    if not user.check_password(old_password):
        return Response({"error": "La contraseña actual es incorrecta."}, status=status.HTTP_400_BAD_REQUEST)
    user.set_password(new_password)
    user.save()
    return Response({"message": "Contraseña actualizada correctamente."}, status=status.HTTP_200_OK)

class ReferenciaViewSet(viewsets.ModelViewSet):
    queryset = Referencia.objects.select_related('proveedor').all()
    serializer_class = ReferenciaSerializer
    permission_classes = [IsAuthenticated]
    # pagination_class = StandardResultsSetPagination
    def get_queryset(self):
        queryset = super().get_queryset()
        proveedor_id = self.request.query_params.get('proveedor')
        if proveedor_id:
            queryset = queryset.filter(proveedor_id=proveedor_id)
        return queryset

class ProveedorViewSet(viewsets.ModelViewSet):
    queryset = Proveedor.objects.all()
    serializer_class = ProveedorSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsSetPagination

# ==============================================================================
# VIEWSETS PRINCIPALES (CORRECCIÓN AQUÍ)
# ==============================================================================

class OrdenPedidoViewSet(viewsets.ModelViewSet):
    # ===== LA LÍNEA DE CORRECCIÓN ESTÁ AQUÍ =====
    queryset = OrdenPedido.objects.all() # Se necesita para que el router de DRF funcione.
    # ==========================================
    serializer_class = OrdenPedidoSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ['get', 'post', 'put', 'patch', 'delete']
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        # Esta función sobreescribe el queryset base para cada petición, manteniendo la optimización.
        base_queryset = OrdenPedido.objects.select_related(
            'proveedor', 'usuario', 'venta'
        ).prefetch_related('detalles').all()
        
        if self.request.user.role in ["administrador", "auxiliar"]:
            return base_queryset
        return base_queryset.filter(usuario=self.request.user)

    def perform_create(self, serializer):
        serializer.save(usuario=self.request.user)
    
    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)

class DetallePedidoViewSet(viewsets.ModelViewSet):
    queryset = DetallePedido.objects.select_related('referencia', 'orden').all()
    serializer_class = DetallePedidoSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsSetPagination

# ... (El resto del archivo no cambia, lo incluyo para que sea el código completo) ...

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def listar_pedidos(request):
    # 1. OBTENER QUERYSET BASE
    pedidos = OrdenPedido.objects.select_related('proveedor', 'usuario', 'venta').all()

    # 2. FILTRAR POR ROL DE USUARIO
    if request.user.role not in ["ADMINISTRADOR", "AUXILIAR"]:
        pedidos = pedidos.filter(usuario=request.user)

    # 3. APLICAR FILTROS DE QUERY PARAMS
    estado = request.GET.get('estado')
    id_proveedor = request.GET.get('id_proveedor')
    id_vendedor = request.GET.get('id_vendedor')

    if estado:
        pedidos = pedidos.filter(estado=estado)
    if id_proveedor:
        pedidos = pedidos.filter(proveedor__id=id_proveedor)
    if id_vendedor:
        pedidos = pedidos.filter(usuario__id=id_vendedor)

    # 4. ORDENAR
    pedidos = pedidos.order_by('-id')

    # 5. PAGINAR EL RESULTADO FILTRADO Y ORDENADO
    paginator = StandardResultsSetPagination()
    page = paginator.paginate_queryset(pedidos, request)
    
    # 6. SERIALIZAR Y DEVOLVER RESPUESTA
    # Si la página es None (porque no se solicitó paginación), serializa el queryset completo
    if page is not None:
        serializer = OrdenPedidoSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)
    
    # Si no hay paginación, serializa el queryset completo
    serializer = OrdenPedidoSerializer(pedidos, many=True)
    return Response(serializer.data)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def detalles_pedido(request, orden_id):
    try:
        detalles = DetallePedido.objects.filter(orden_id=orden_id).select_related('referencia')
        data = [{"cantidad": d.cantidad, "especificaciones": d.especificaciones, "referencia": d.referencia.nombre if d.referencia else "N/A"} for d in detalles]
        return Response(data)
    except DetallePedido.DoesNotExist:
        return Response({"error": "No se encontraron detalles para esta orden."}, status=404)

class CrearVentaClienteView(APIView):
    permission_classes = [IsAuthenticated]
    @transaction.atomic
    def post(self, request):
        cliente_nuevo = request.data.get('cliente_nuevo', False)
        cliente_data = request.data.get('cliente', {})
        venta_data = request.data.get('venta', {})
        observacion_texto = request.data.get('observacion')
        if Venta.objects.filter(id=venta_data.get('id')).exists():
            return Response({"error": "El ID de la venta ya existe."}, status=400)
        if cliente_nuevo:
            cliente_serializer = ClienteSerializer(data=cliente_data)
            cliente_serializer.is_valid(raise_exception=True)
            cliente = cliente_serializer.save()
        else:
            try:
                cliente = Cliente.objects.get(pk=cliente_data.get('id'))
                cliente_serializer = ClienteSerializer(cliente, data=cliente_data, partial=True)
                cliente_serializer.is_valid(raise_exception=True)
                cliente = cliente_serializer.save()
            except Cliente.DoesNotExist:
                raise ValidationError({"cliente": "Cliente no encontrado."})
        try:
            vendedor = CustomUser.objects.get(pk=venta_data.get('id_vendedor'), is_active=True)
        except CustomUser.DoesNotExist:
            raise ValidationError({"vendedor": "Vendedor no encontrado."})
        venta_data.update({'cliente': cliente.id, 'vendedor': vendedor.id, 'estado': 'pendiente', 'saldo': venta_data.get('valor_total', 0)})
        venta_serializer = VentaSerializer(data=venta_data)
        venta_serializer.is_valid(raise_exception=True)
        venta = venta_serializer.save()
        if observacion_texto:
            venta.observaciones.create(autor=request.user, texto=observacion_texto)
        return Response({"message": "Venta creada.", "venta_id": venta.id, "cliente_id": cliente.id}, status=201)

class EditarVentaClienteView(APIView):
    permission_classes = [IsAuthenticated]
    @transaction.atomic
    def put(self, request, id):
        try:
            venta = Venta.objects.get(id=id)
            cliente_data = request.data.get('cliente', {})
            venta_data = request.data.get('venta', {})

            cliente_serializer = ClienteSerializer(venta.cliente, data=cliente_data, partial=True)
            cliente_serializer.is_valid(raise_exception=True)
            cliente_serializer.save()

            venta_serializer = VentaSerializer(venta, data=venta_data, partial=True)
            venta_serializer.is_valid(raise_exception=True)

            # Correctly calculate the new saldo
            new_valor_total = venta_serializer.validated_data.get('valor_total', venta.valor_total)
            new_saldo = new_valor_total - venta.abono

            venta = venta_serializer.save(saldo=new_saldo)
            return Response({"message": "Venta actualizada.", "venta_id": venta.id}, status=200)
        except Venta.DoesNotExist:
            return Response({"error": "Venta no encontrada."}, status=404)
        except Exception as e:
            return Response({"error": str(e)}, status=500)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def listar_ventas(request):
    # OPTIMIZACIÓN: Iniciar con la consulta optimizada
    ventas = Venta.objects.select_related('cliente', 'vendedor').all()

    search_query = request.GET.get('search')

    if search_query:
        ventas = ventas.filter(Q(cliente__nombre__icontains=search_query) | Q(id__icontains=search_query))
    else:
        # ... (lógica de filtrado por fecha, estado, etc. se mantiene igual)
        month_param = request.GET.get('month')
        year_param = request.GET.get('year')
        estado = request.GET.get('estado')
        vendedor_id_param = request.GET.get('vendedor')

        if month_param and year_param:
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
                return Response({"error": "Parámetros de mes o año inválidos."}, status=status.HTTP_400_BAD_REQUEST)

        if estado:
            ventas = ventas.filter(estado=estado)
        
        if vendedor_id_param:
            try:
                vendedor_id = int(vendedor_id_param)
                ventas = ventas.filter(vendedor_id=vendedor_id)
            except ValueError:
                return Response({"error": "ID de vendedor inválido."}, status=status.HTTP_400_BAD_REQUEST)

    serializer = VentaSerializer(ventas, many=True)
    return Response(serializer.data)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def detalle_venta(request, id):
    try:
        # OPTIMIZACIÓN: Usar select_related para joins y prefetch_related para relaciones inversas/many-to-many
        venta = Venta.objects.select_related(
            'cliente', 
            'vendedor'
        ).prefetch_related(
            'observaciones__autor', 
            'recibos', 
            'remisiones', 
            'ordenes_pedido__proveedor', 
            'ordenes_pedido__usuario', 
            'cliente__observaciones'
        ).get(id=id)
        
        serializer = VentaDetalleSerializer(venta)
        return Response(serializer.data)
    except Venta.DoesNotExist:
        return Response({"error": "Venta no encontrada."}, status=404)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def anadir_observacion_venta(request, id):
    try:
        venta = Venta.objects.get(id=id)
        serializer = ObservacionVentaSerializer(data={'venta': venta.id, 'texto': request.data.get('texto')}, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=201)
    except Venta.DoesNotExist:
        return Response({"error": "Venta no encontrada."}, status=404)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def anadir_remision_a_venta(request, id):
    try:
        venta = Venta.objects.get(id=id)
        if Remision.objects.filter(codigo=request.data.get('codigo')).exists():
            return Response({"error": "El código de remisión ya existe."}, status=400)
        serializer = RemisionSerializer(data={'venta': venta.id, **request.data})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=201)
    except Venta.DoesNotExist:
        return Response({"error": "Venta no encontrada."}, status=404)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def ver_remisiones_de_venta(request, id):
    try:
        venta = Venta.objects.get(id=id)
        remisiones = Remision.objects.filter(venta=venta)
        serializer = RemisionSerializer(remisiones, many=True)
        return Response(serializer.data)
    except Venta.DoesNotExist:
        return Response({"error": "Venta no encontrada."}, status=404)

class ClientePagination(PageNumberPagination):
    page_size = 30
    page_size_query_param = 'page_size'
    max_page_size = 100

class ClienteFilter(django_filters.FilterSet):
    query = django_filters.CharFilter(method='filter_by_query', label='Buscar')
    class Meta:
        model = Cliente
        fields = ['query']
    def filter_by_query(self, queryset, name, value):
        return queryset.filter(Q(id__icontains=value) | Q(nombre__icontains=value) | Q(cedula__icontains=value))

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def listar_clientes(request):
    filtro = ClienteFilter(request.GET, queryset=Cliente.objects.all().order_by('-id'))
    paginator = ClientePagination()
    page = paginator.paginate_queryset(filtro.qs, request)
    serializer = ClienteSerializer(page, many=True)
    return paginator.get_paginated_response(serializer.data)

@api_view(['GET', 'PUT'])
@permission_classes([IsAuthenticated])
def obtener_cliente(request, id):
    try:
        cliente = Cliente.objects.get(id=id)
        if request.method == 'GET':
            return Response(ClienteSerializer(cliente).data)
        elif request.method == 'PUT':
            serializer = ClienteSerializer(cliente, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data)
    except Cliente.DoesNotExist:
        return Response({"error": "Cliente no encontrado."}, status=404)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def ventas_y_observaciones_cliente(request, id):
    try:
        cliente = Cliente.objects.prefetch_related('ventas', 'observaciones').get(id=id)
        return Response({
            "cliente_id": cliente.id, "nombre_cliente": cliente.nombre,
            "ventas": VentaSerializer(cliente.ventas.all(), many=True).data,
            "observaciones_cliente": ObservacionClienteSerializer(cliente.observaciones.all(), many=True).data
        })
    except Cliente.DoesNotExist:
        return Response({"error": "Cliente no encontrado."}, status=404)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def anadir_observacion_cliente(request, id):
    try:
        cliente = Cliente.objects.get(id=id)
        serializer = ObservacionClienteSerializer(data={'cliente': cliente.id, 'texto': request.data.get('texto')}, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=201)
    except Cliente.DoesNotExist:
        return Response({"error": "Cliente no encontrado."}, status=404)

class CajaPagination(PageNumberPagination):
    page_size = 30
    page_size_query_param = 'page_size'
    max_page_size = 100

from django.db.models import Q, F, Sum, Case, When, DecimalField

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def caja_view(request):
    if request.method == 'GET':
        # 1. Estadísticas
        today = timezone.now().date()
        ingresos_hoy = Caja.objects.filter(fecha_hora__date=today, tipo='ingreso').aggregate(total=Sum('valor'))['total'] or 0
        egresos_hoy = Caja.objects.filter(fecha_hora__date=today, tipo='egreso').aggregate(total=Sum('valor'))['total'] or 0
        ultimo_movimiento = Caja.objects.order_by('-fecha_hora').first()
        saldo_actual = ultimo_movimiento.total_acumulado if ultimo_movimiento else 0
        stats = {
            'ingresos_hoy': ingresos_hoy,
            'egresos_hoy': egresos_hoy,
            'saldo_actual': saldo_actual
        }

        # 2. Movimientos Paginados con filtros
        movimientos = Caja.objects.select_related('usuario').order_by('-fecha_hora')
        fecha_inicio = request.GET.get('fecha_inicio')
        fecha_fin = request.GET.get('fecha_fin')
        query = request.GET.get('query')
        if fecha_inicio:
            movimientos = movimientos.filter(fecha_hora__date__gte=fecha_inicio)
        if fecha_fin:
            movimientos = movimientos.filter(fecha_hora__date__lte=fecha_fin)
        if query:
            movimientos = movimientos.filter(Q(id__icontains=query) | Q(concepto__icontains=query))
        
        paginator = CajaPagination()
        page = paginator.paginate_queryset(movimientos, request)
        serializer = CajaSerializer(page, many=True)
        paginated_response = paginator.get_paginated_response(serializer.data)

        # 3. Combinar todo en una sola respuesta
        data = {
            'stats': stats,
            'movimientos': paginated_response.data
        }
        return Response(data)

    elif request.method == 'POST':
        serializer = CajaSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class ReciboCajaPagination(PageNumberPagination):
    page_size = 30
    page_size_query_param = 'page_size'
    max_page_size = 100

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def listar_recibos_caja(request):
    # OPTIMIZACIÓN: Cargar datos del cliente relacionados en una sola consulta
    recibos = ReciboCaja.objects.select_related('venta__cliente').order_by('-fecha', '-id')
    
    fecha_inicio = request.GET.get('fecha_inicio')
    fecha_fin = request.GET.get('fecha_fin')
    medio_pago = request.GET.get('medio_pago')
    query = request.GET.get('query')

    if fecha_inicio:
        recibos = recibos.filter(fecha__gte=fecha_inicio)
    if fecha_fin:
        recibos = recibos.filter(fecha__lte=fecha_fin)
    if medio_pago:
        recibos = recibos.filter(metodo_pago=medio_pago)
    if query:
        recibos = recibos.filter(Q(id__icontains=query) | Q(venta__id__icontains=query) | Q(venta__cliente__nombre__icontains=query))

    paginator = ReciboCajaPagination()
    page = paginator.paginate_queryset(recibos, request)
    return paginator.get_paginated_response(ReciboCajaSerializer(page, many=True).data)

class ComprobanteEgresoPagination(PageNumberPagination):
    page_size = 30
    page_size_query_param = 'page_size'
    max_page_size = 100

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def listar_comprobantes_egreso(request):
    # OPTIMIZACIÓN: Cargar datos del proveedor relacionados en una sola consulta
    egresos = ComprobanteEgreso.objects.select_related('proveedor').order_by('-fecha', '-id')

    fecha_inicio = request.GET.get('fecha_inicio')
    fecha_fin = request.GET.get('fecha_fin')
    metodo_pago = request.GET.get('metodo_pago')
    proveedor_id = request.GET.get('proveedor')
    query = request.GET.get('query')

    if fecha_inicio:
        egresos = egresos.filter(fecha__gte=fecha_inicio)
    if fecha_fin:
        egresos = egresos.filter(fecha__lte=fecha_fin)
    if metodo_pago:
        egresos = egresos.filter(metodo_pago=metodo_pago)
    if proveedor_id:
        egresos = egresos.filter(proveedor__id=proveedor_id)
    if query:
        egresos = egresos.filter(Q(id__icontains=query) | Q(concepto__icontains=query) | Q(descripcion__icontains=query) | Q(proveedor__nombre_empresa__icontains=query))

    paginator = ComprobanteEgresoPagination()
    page = paginator.paginate_queryset(egresos, request)
    return paginator.get_paginated_response(ComprobanteEgresoSerializer(page, many=True).data)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
@transaction.atomic
def crear_comprobante_egreso(request):
    logger.info(f"Received data for crear_comprobante_egreso: {request.data}")
    try:
        serializer = ComprobanteEgresoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        egreso = serializer.save()
        if egreso.metodo_pago == 'Efectivo':
            # Lógica de caja
            concepto_caja = f"Pago a {egreso.proveedor.nombre_empresa}, CE. {egreso.id}"
            caja_data = {
                'concepto': concepto_caja,
                'valor': egreso.valor,
                'tipo': 'egreso',
            }
            caja_serializer = CajaSerializer(data=caja_data, context={'request': request})
            caja_serializer.is_valid(raise_exception=True)
            caja_serializer.save()
        return Response(serializer.data, status=201)
    except Exception as e:
        logger.error(f"Error creating comprobante de egreso: {e}", exc_info=True)
        return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
@transaction.atomic
def crear_recibo_caja(request):
    serializer = ReciboCajaSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    
    metodo_pago = request.data.get('metodo_pago')
    
    if metodo_pago == 'Efectivo':
        recibo = serializer.save(estado='Confirmado')
        # Actualizar abono y saldo de la venta
        venta = recibo.venta
        venta.abono = F('abono') + recibo.valor
        venta.saldo = F('saldo') - recibo.valor
        venta.save(update_fields=['abono', 'saldo'])

        # Crear movimiento de caja usando el serializador
        concepto_caja = f"RC. {recibo.id}, OP. {recibo.venta.id}"
        caja_data = {
            'concepto': concepto_caja,
            'valor': recibo.valor,
            'tipo': 'ingreso',
        }
        caja_serializer = CajaSerializer(data=caja_data, context={'request': request})
        caja_serializer.is_valid(raise_exception=True)
        caja_serializer.save()
    else:
        recibo = serializer.save(estado='Pendiente')
        
    return Response(serializer.data, status=201)

@api_view(['PATCH'])
@permission_classes([IsAdmin])
@transaction.atomic
def confirmar_recibo(request, id):
    try:
        recibo = ReciboCaja.objects.get(id=id)
    except ReciboCaja.DoesNotExist:
        return Response({"error": "Recibo de Caja no encontrado."}, status=status.HTTP_404_NOT_FOUND)

    if recibo.estado == 'Confirmado':
        return Response({"message": "El recibo ya está confirmado."}, status=status.HTTP_200_OK)

    recibo.estado = 'Confirmado'
    recibo.save(update_fields=['estado'])

    # Actualizar abono y saldo de la venta
    venta = recibo.venta
    venta.abono = F('abono') + recibo.valor
    venta.saldo = F('saldo') - recibo.valor
    venta.save(update_fields=['abono', 'saldo'])

    return Response({"message": "Recibo confirmado y venta actualizada."}, status=status.HTTP_200_OK)



@api_view(['GET'])
@permission_classes([IsAuthenticated])
def listar_ventas_pendientes_ids(request):
    ids = Venta.objects.filter(estado='pendiente').order_by('-id').values_list('id', flat=True)
    return Response(list(ids))