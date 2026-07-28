# ==================== ordenes/views.py (CORRECCIÓN FINAL-FINAL) ====================

import logging
from rest_framework import viewsets, status, generics
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django.http import HttpResponse
from .models import (
    Referencia, Proveedor, OrdenPedido, DetallePedido, CustomUser, Cliente,
    Venta, ObservacionVenta, Caja, ReciboCaja, ComprobanteEgreso,
    ObservacionCliente, Remision, ProveedorTela, PedidoTela, DetallePedidoTela, DireccionEntrega
)
from .serializers import (
    ReferenciaSerializer, ProveedorSerializer, OrdenPedidoSerializer,
    DetallePedidoSerializer, ClienteSerializer, VentaSerializer,
    ObservacionVentaSerializer, CajaSerializer, ReciboCajaSerializer,
    ComprobanteEgresoSerializer, VentaDetalleSerializer,
    ObservacionClienteSerializer, RemisionSerializer,
    ProveedorTelaSerializer, PedidoTelaSerializer, DetallePedidoTelaSerializer, DireccionEntregaSerializer, UserManageSerializer
)
from .permissions import IsAdmin, IsAdministradorRole, check_feature_permission
from django.db import transaction
from django.db.models import Q, F, Sum, Case, When, Value, IntegerField
from decimal import Decimal, InvalidOperation
from rest_framework.exceptions import ValidationError
from datetime import date, timedelta, time, datetime
from django.utils import timezone
import calendar
import django_filters
from rest_framework.pagination import PageNumberPagination

@api_view(['POST'])
@permission_classes([IsAuthenticated, check_feature_permission('VER_CAJA')])
@transaction.atomic
def cierre_caja(request):
    user = request.user
    descuadre = request.data.get('descuadre', 0)
    signo = request.data.get('signo', 'faltante')

    try:
        descuadre_decimal = Decimal(descuadre)
    except (ValueError, TypeError, InvalidOperation):
        return Response({"error": "El valor de descuadre debe ser un número válido."}, status=status.HTTP_400_BAD_REQUEST)

    last_movement = Caja.objects.order_by('-fecha_hora').first()
    total_acumulado = last_movement.total_acumulado if last_movement else Decimal('0')

    if descuadre_decimal != 0:
        if signo == 'faltante':
            total_acumulado -= descuadre_decimal
            tipo_desc = 'faltante'
            valor_caja = -descuadre_decimal
        else:
            total_acumulado += descuadre_decimal
            tipo_desc = 'sobrante'
            valor_caja = descuadre_decimal
            
        formatted_descuadre = f"${descuadre_decimal:,.0f}"
        concepto = f"Cierre de caja por {user.first_name}, {tipo_desc} de {formatted_descuadre}"
    else:
        concepto = f"Cierre de caja exitoso por {user.first_name}"
        valor_caja = Decimal('0')

    Caja.objects.create(
        usuario=user,
        concepto=concepto,
        valor=valor_caja,
        tipo='cierre',
        total_acumulado=total_acumulado
    )
    return Response({"message": "Cierre de caja registrado exitosamente."}, status=status.HTTP_201_CREATED)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dashboard_stats(request):
    user = request.user

    # For vendedores: return their specific stats
    if user.role == 'vendedor':
        # Filter ventas by vendor
        ventas = Venta.objects.filter(Q(vendedor=user) | Q(vendedores_compartidos=user)).distinct().exclude(estado='anulado')

        # Vendor stat 1: Ventas Pendientes - count of their pending sales
        ventas_pendientes = ventas.filter(estado='pendiente').count()

        # Vendor stat 2: Pedidos Pendientes - count of their ventas with estado_pedidos=False
        pedidos_pendientes = ventas.filter(estado_pedidos=False).count()

        # Filter orders by vendor (created by vendor OR associated with vendor's sale)
        ordenes = OrdenPedido.objects.filter(
            Q(usuario=user) |
            Q(venta__vendedor=user) |
            Q(venta__vendedores_compartidos=user)
        ).distinct()
        
        # Vendor stat 3: Órdenes Atrasadas - count of their overdue orders
        today = date.today()
        ordenes_atrasadas = ordenes.filter(estado='en_proceso', fecha_esperada__lt=today).count()

        data = {
            'ventas_pendientes': ventas_pendientes,
            'pedidos_pendientes': pedidos_pendientes,
            'ordenes_atrasadas': ordenes_atrasadas,
            'saldo_caja': 0,
            'ultimas_ventas': []
        }
        return Response(data)

    # For admin/auxiliar: return global stats
    ventas = Venta.objects.exclude(estado='anulado')

    # Admin stat 1: Ventas Hoy - sum of sales today
    today = date.today()
    ventas_dia = ventas.filter(fecha_venta=today).aggregate(total=Sum('valor_total'))['total'] or 0

    # Admin stat 2: Ventas del Mes - sum of sales this month (Custom range: 6th to 5th)
    if today.day >= 6:
        start_date = date(today.year, today.month, 6)
        # Handle December rollover
        if today.month == 12:
            end_date = date(today.year + 1, 1, 5)
        else:
            end_date = date(today.year, today.month + 1, 5)
    else:
        # Handle January rollover
        if today.month == 1:
            start_date = date(today.year - 1, 12, 6)
        else:
            start_date = date(today.year, today.month - 1, 6)
        end_date = date(today.year, today.month, 5)

    ventas_mes = ventas.filter(fecha_venta__gte=start_date, fecha_venta__lte=end_date).aggregate(total=Sum('valor_total'))['total'] or 0

    # Admin stat 3: Pedidos Pendientes - count of ALL ventas with estado_pedidos=False
    pedidos_pendientes = ventas.filter(estado_pedidos=False).count()

    # Admin stat 4: Órdenes Atrasadas - count of ALL overdue orders (estado='pendiente' and fecha_esperada < today)
    ordenes_atrasadas = OrdenPedido.objects.filter(estado='pendiente', fecha_esperada__lt=today).count()

    # Keep saldo_caja for admin/auxiliar users
    ultimo_movimiento_caja = Caja.objects.order_by('-fecha_hora').first()
    saldo_caja = ultimo_movimiento_caja.total_acumulado if ultimo_movimiento_caja else 0
    
    # Keep ultimas_ventas for compatibility
    ultimas_ventas = ventas.select_related('cliente', 'vendedor').prefetch_related('vendedores_compartidos').order_by('-fecha_venta', '-id')[:5]
    ultimas_ventas_serializer = VentaSerializer(ultimas_ventas, many=True)

    data = {
        'ventas_dia': ventas_dia,
        'ventas_mes': ventas_mes,
        'pedidos_pendientes': pedidos_pendientes,
        'ordenes_atrasadas': ordenes_atrasadas,
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
    user = request.user

    ventas = Venta.objects.exclude(estado='anulado')
    
    from django.db.models import Count, ExpressionWrapper, DecimalField, F
    
    if user.role == 'vendedor':
        ventas = ventas.filter(Q(vendedor=user) | Q(vendedores_compartidos=user)).distinct()
        ventas = ventas.annotate(
            num_vendedores=Count('vendedores_compartidos') + 1
        ).annotate(
            valor_calculado=ExpressionWrapper(
                F('valor_total') / F('num_vendedores'),
                output_field=DecimalField(max_digits=10, decimal_places=2)
            )
        )
    else:
        ventas = ventas.annotate(valor_calculado=F('valor_total'))

    sales_current_year = ventas.filter(fecha_venta__year=current_year)
    sales_last_year = ventas.filter(fecha_venta__year=last_year)

    # Agrupar por mes y sumar
    current_year_data = {i: 0 for i in range(1, 13)}
    last_year_data = {i: 0 for i in range(1, 13)}

    current_sales_by_month = sales_current_year.values('fecha_venta__month').annotate(total=Sum('valor_calculado'))
    for item in current_sales_by_month:
        current_year_data[item['fecha_venta__month']] = item['total']

    last_sales_by_month = sales_last_year.values('fecha_venta__month').annotate(total=Sum('valor_calculado'))
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
    vendedores = CustomUser.objects.filter(is_active=True).exclude(role='transportador').only('id', 'first_name')
    data = [{"id": v.id, "first_name": v.first_name} for v in vendedores]
    return Response(data)

class UserDetailView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        user = request.user
        perms = []
        if user.role == 'administrador':
            perms = ['ALL']
        else:
            try:
                from .models import RolePermission
                rp = RolePermission.objects.filter(role=user.role).first()
                if rp and isinstance(rp.permissions, list):
                    perms = rp.permissions
                elif user.role == 'transportador':
                    perms = ['VER_REMISIONES']
            except Exception as e:
                print(f"Error cargando permisos de rol para {user.username}: {e}")
                if user.role == 'transportador':
                    perms = ['VER_REMISIONES']

        return Response({
            "id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "role": user.role,
            "permissions": perms
        })

class RolePermissionViewSet(viewsets.ModelViewSet):
    from .models import RolePermission
    queryset = RolePermission.objects.all()
    permission_classes = [IsAuthenticated, IsAdministradorRole]
    
    def get_queryset(self):
        from .models import RolePermission
        default_roles = ['vendedor', 'administrador', 'auxiliar', 'transportador']
        try:
            for role_code in default_roles:
                RolePermission.objects.get_or_create(role=role_code, defaults={'permissions': []})
        except Exception:
            pass
        return RolePermission.objects.all().order_by('id')

    def get_serializer_class(self):
        from rest_framework import serializers
        from .models import RolePermission
        class RolePermissionSerializer(serializers.ModelSerializer):
            class Meta:
                model = RolePermission
                fields = ['id', 'role', 'permissions']
        return RolePermissionSerializer

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
    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), check_feature_permission('ADMINISTRAR_BASES')()]
        return [IsAuthenticated()]
    queryset = Referencia.objects.select_related('proveedor').prefetch_related('categorias', 'subcategorias').all()
    serializer_class = ReferenciaSerializer
    # pagination_class = StandardResultsSetPagination
    def get_queryset(self):
        queryset = super().get_queryset()
        proveedor_id = self.request.query_params.get('proveedor')
        if proveedor_id:
            queryset = queryset.filter(proveedor_id=proveedor_id)
        return queryset

class ProveedorViewSet(viewsets.ModelViewSet):
    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), check_feature_permission('ADMINISTRAR_BASES')()]
        return [IsAuthenticated()]
    queryset = Proveedor.objects.all()
    serializer_class = ProveedorSerializer
    pagination_class = StandardResultsSetPagination

class UserViewSet(viewsets.ModelViewSet):
    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), check_feature_permission('ADMINISTRAR_USUARIOS')()]
        return [IsAuthenticated(), check_feature_permission('VER_USUARIOS')()]
    queryset = CustomUser.objects.all().order_by('-is_active', 'first_name', 'last_name')
    serializer_class = UserManageSerializer
    pagination_class = StandardResultsSetPagination

# ==============================================================================
# VIEWSETS PRINCIPALES (CORRECCIÓN AQUÍ)
# ==============================================================================

class OrdenPedidoViewSet(viewsets.ModelViewSet):
    # ===== LA LÍNEA DE CORRECCIÓN ESTÁ AQUÍ =====
    queryset = OrdenPedido.objects.all() # Se necesita para que el router de DRF funcione.
    # ==========================================
    serializer_class = OrdenPedidoSerializer
    
    def get_permissions(self):
        from .permissions import check_feature_permission
        from rest_framework.permissions import BasePermission
        if self.action in ['create']:
            class DynamicCreateOrderPermission(BasePermission):
                def has_permission(self, request, view):
                    if not request.user or not request.user.is_authenticated:
                        return False
                    if request.user.role == 'administrador':
                        return True
                    from .models import RolePermission
                    rp = RolePermission.objects.filter(role=request.user.role).first()
                    if rp:
                        p = rp.permissions
                        return ('CREAR_ORDEN' in p or 'CREAR_PROPIAS_ORDENES' in p or 'CREAR_ORDENES_OTROS' in p)
                    return False
            return [IsAuthenticated(), DynamicCreateOrderPermission()]
        elif self.action in ['update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), check_feature_permission('EDITAR_ESTADO_ORDEN')()]
        return [IsAuthenticated(), check_feature_permission('VER_ORDENES')()]
    http_method_names = ['get', 'post', 'put', 'patch', 'delete']
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        # Esta función sobreescribe el queryset base para cada petición, manteniendo la optimización.
        base_queryset = OrdenPedido.objects.select_related(
            'proveedor', 'usuario', 'venta'
        ).prefetch_related('detalles').all()
        
        from .permissions import check_feature_permission
        if check_feature_permission('VER_TODAS_ORDENES')().has_permission(self.request, None):
            return base_queryset
        elif check_feature_permission('VER_PROPIAS_ORDENES')().has_permission(self.request, None) or self.request.user.role == 'vendedor':
            user = self.request.user
            return base_queryset.filter(
                Q(usuario=user) |
                Q(venta__vendedor=user) |
                Q(venta__vendedores_compartidos=user)
            ).distinct()
        else:
            return base_queryset.none()

    def perform_create(self, serializer):
        user = self.request.user
        vendedor_id = self.request.data.get('vendedor') or self.request.data.get('usuario')
        
        can_create_others = False
        if user.role == 'administrador':
            can_create_others = True
        else:
            from .models import RolePermission
            rp = RolePermission.objects.filter(role=user.role).first()
            if rp and ('CREAR_ORDENES_OTROS' in rp.permissions or 'CREAR_ORDEN' in rp.permissions):
                can_create_others = True
                
        if can_create_others and vendedor_id:
            from .models import CustomUser
            try:
                target_user = CustomUser.objects.get(id=vendedor_id)
                serializer.save(usuario=target_user)
                return
            except CustomUser.DoesNotExist:
                pass
                
        serializer.save(usuario=user)
    
    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        data = request.data.copy()
        # Vendedores solo pueden actualizar el estado de tela
        if request.user.role == 'vendedor':
            data = {'tela': data.get('tela', instance.tela)}
        serializer = self.get_serializer(instance, data=data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)

class DetallePedidoViewSet(viewsets.ModelViewSet):
    queryset = DetallePedido.objects.select_related('referencia', 'orden').all()
    serializer_class = DetallePedidoSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsSetPagination

# ... (El resto del archivo no cambia, lo incluyo para que sea el código completo) ...

import logging

logger = logging.getLogger(__name__)

@api_view(['GET'])
@permission_classes([IsAuthenticated, check_feature_permission('VER_ORDENES')])
def listar_pedidos(request):
    try:
        pedidos = OrdenPedido.objects.select_related('proveedor', 'usuario', 'venta').all()

        # If user is a vendedor, they can see their own orders OR orders tied to their sales
        if request.user.role == 'vendedor':
            pedidos = pedidos.filter(
                Q(usuario=request.user) |
                Q(venta__vendedor=request.user) |
                Q(venta__vendedores_compartidos=request.user)
            ).distinct()
        else:
        # If admin or auxiliar, they can filter by vendedor
            id_vendedor = request.GET.get('id_vendedor')
            if id_vendedor:
                if id_vendedor == '-1':
                    pedidos = pedidos.none()
                elif ',' in id_vendedor:
                    vendedores_list = [v.strip() for v in id_vendedor.split(',') if v.strip()]
                    pedidos = pedidos.filter(usuario__id__in=vendedores_list)
                else:
                    pedidos = pedidos.filter(usuario__id=id_vendedor)

        # Other filters
        estado = request.GET.get('estado')
        if estado:
            if estado == 'ninguno_imposible':
                pedidos = pedidos.none()
            elif ',' in estado:
                estados_list = [e.strip() for e in estado.split(',') if e.strip()]
                if 'en_proceso' in estados_list and 'pendiente' not in estados_list:
                    estados_list.append('pendiente')
                pedidos = pedidos.filter(estado__in=estados_list)
            else:
                if estado == 'en_proceso':
                    pedidos = pedidos.filter(estado__in=['en_proceso', 'pendiente'])
                else:
                    pedidos = pedidos.filter(estado=estado)
        
        id_proveedor = request.GET.get('id_proveedor')
        if id_proveedor:
            if id_proveedor == 'ninguno_imposible':
                pedidos = pedidos.none()
            elif ',' in id_proveedor:
                proveedores_list = [p.strip() for p in id_proveedor.split(',') if p.strip()]
                pedidos = pedidos.filter(proveedor__id__in=proveedores_list)
            else:
                pedidos = pedidos.filter(proveedor__id=id_proveedor)

        es_exhibicion = request.GET.get('es_exhibicion')
        if es_exhibicion:
            if ',' in es_exhibicion:
                # If they pass "true,false", we just don't filter (show both)
                pass
            elif es_exhibicion == 'true':
                pedidos = pedidos.filter(es_exhibicion=True)
            elif es_exhibicion == 'false':
                pedidos = pedidos.filter(es_exhibicion=False)

        tela = request.GET.get('tela')
        if tela:
            pedidos = pedidos.filter(tela=tela)

        pedidos = pedidos.order_by('-id')

        serializer = OrdenPedidoSerializer(pedidos, many=True)
        return Response(serializer.data)
    except Exception as e:
        logger.error(f"Error en listar_pedidos: {e}", exc_info=True)
        return Response({"error": "Ocurrió un error inesperado en el servidor."}, status=500)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def detalles_pedido(request, orden_id):
    try:
        # OPTIMIZACIÓN: Usar `select_related` y `only` para traer solo lo necesario
        detalles = DetallePedido.objects.filter(orden_id=orden_id).select_related('referencia').only(
            'cantidad', 'especificaciones', 'referencia__nombre'
        )
        
        # Obtener la observación de la orden
        try:
            orden = OrdenPedido.objects.get(id=orden_id)
            observacion = orden.observacion
        except OrdenPedido.DoesNotExist:
            observacion = None

        detalles_data = [{
            "cantidad": d.cantidad,
            "especificaciones": d.especificaciones,
            "referencia": d.referencia.nombre if d.referencia else "N/A"
        } for d in detalles]

        # --- NUEVO: Obtener los PedidoTela asociados a esta orden ---
        pedidos_tela_qs = PedidoTela.objects.filter(
            orden_asociada_id=orden_id
        ).select_related('proveedor').prefetch_related('detalles')

        pedidos_telas_data = []
        for pt in pedidos_tela_qs:
            detalles_tela = [{
                "tela": dt.tela,
                "cantidad": str(dt.cantidad),
                "observacion": dt.observacion or '',
            } for dt in pt.detalles.all()]
            pedidos_telas_data.append({
                "id": pt.id,
                "proveedor": pt.proveedor.nombre_empresa if pt.proveedor else "N/A",
                "fecha_creacion": str(pt.fecha_creacion) if pt.fecha_creacion else None,
                "estado": pt.estado,
                "detalles": detalles_tela,
            })
        # -------------------------------------------------------
        
        return Response({
            "detalles": detalles_data,
            "observacion": observacion,
            "pedidos_telas": pedidos_telas_data,
        })
    except Exception as e:
        # Log del error para depuración
        logger.error(f"Error al obtener detalles del pedido {orden_id}: {str(e)}")
        return Response({"error": "Ocurrió un error inesperado al cargar los detalles."}, status=500)

class CrearVentaClienteView(APIView):
    permission_classes = [IsAuthenticated, check_feature_permission('CREAR_VENTA')]
    @transaction.atomic
    def post(self, request):
        cliente_nuevo = request.data.get('cliente_nuevo', False)
        cliente_data = request.data.get('cliente', {})
        venta_data = request.data.get('venta', {})
        observacion_texto = request.data.get('observacion')
        venta_id = venta_data.get('id')
        if venta_id:
            if Venta.objects.filter(id=venta_id).exists():
                return Response({"error": "El ID de la venta ya existe."}, status=400)
        else:
            venta_data.pop('id', None)
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
        user = request.user

        # Both EDITAR_VENTA (full) and EDITAR_ESTADO_VENTA/EDITAR_ESTADO_PEDIDOS_VENTA uses this endpoint, 
        # so we will check internally based on payload
        has_full = check_feature_permission('EDITAR_VENTA')().has_permission(request, self)
        has_estado = check_feature_permission('EDITAR_ESTADO_VENTA')().has_permission(request, self)
        has_pedidos = check_feature_permission('EDITAR_ESTADO_PEDIDOS_VENTA')().has_permission(request, self)

        if not (has_full or has_estado or has_pedidos):
            return Response({"error": "No tienes permiso para editar ventas."}, status=status.HTTP_403_FORBIDDEN)

        try:
            venta = Venta.objects.get(id=id)
            cliente_data = request.data.get('cliente', {})
            venta_data = request.data.get('venta', {})

            if not has_full and (has_estado or has_pedidos):
                allowed_keys = set()
                if has_estado: allowed_keys.add('estado')
                if has_pedidos: allowed_keys.add('estado_pedidos')
                
                submitted_keys = set(venta_data.keys())
                if not submitted_keys.issubset(allowed_keys):
                    return Response({"error": "Solo tienes permiso para modificar los estados autorizados."}, status=status.HTTP_403_FORBIDDEN)

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
@permission_classes([IsAuthenticated, check_feature_permission('VER_VENTAS')])
def listar_ventas(request):
    # OPTIMIZACIÓN: Iniciar con la consulta optimizada (select_related + prefetch_related)
    ventas = Venta.objects.select_related('cliente', 'vendedor').prefetch_related('vendedores_compartidos').all()

    search_query = request.GET.get('search')

    if search_query:
        ventas = ventas.filter(Q(cliente__nombre__icontains=search_query) | Q(id__icontains=search_query))
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
        sede_param = request.GET.get('sede')

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
                return Response({"error": "Parámetros de mes o año inválidos en periods."}, status=status.HTTP_400_BAD_REQUEST)
        
        elif start_date_param and end_date_param:
            try:
                start_date = date.fromisoformat(start_date_param)
                end_date = date.fromisoformat(end_date_param)
                ventas = ventas.filter(fecha_venta__gte=start_date, fecha_venta__lte=end_date)
            except ValueError:
                return Response({"error": "Formato de fecha inválido."}, status=status.HTTP_400_BAD_REQUEST)
                
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
                return Response({"error": "Parámetros de mes o año inválidos."}, status=status.HTTP_400_BAD_REQUEST)

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
                return Response({"error": "ID de vendedor inválido."}, status=status.HTTP_400_BAD_REQUEST)
                
        if sede_param:
            if ',' in str(sede_param):
                sedes_list = [s.strip() for s in str(sede_param).split(',') if s.strip()]
                ventas = ventas.filter(sede__in=sedes_list)
            else:
                ventas = ventas.filter(sede=sede_param)

    ventas = ventas.order_by('-fecha_venta', '-id')

    page_param = request.GET.get('page')
    page_size_param = request.GET.get('page_size')

    if page_param and page_size_param:
        try:
            page = int(page_param)
            page_size = int(page_size_param)
            total_count = ventas.count()
            start = (page - 1) * page_size
            end = start + page_size
            ventas_page = ventas[start:end]
            serializer = VentaSerializer(ventas_page, many=True)
            return Response({
                'count': total_count,
                'results': serializer.data
            })
        except ValueError:
            pass

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
            # 'recibos', # REMOVED FOR PERFORMANCE
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
    search = django_filters.CharFilter(method='filter_by_query', label='Buscar')

    class Meta:
        model = Cliente
        fields = ['query', 'search']

    def filter_by_query(self, queryset, name, value):
        if not value or not str(value).strip():
            return queryset
        val = str(value).strip()
        return queryset.filter(Q(id__icontains=val) | Q(nombre__icontains=val) | Q(cedula__icontains=val))

@api_view(['GET'])
@permission_classes([IsAuthenticated, check_feature_permission('VER_CLIENTES')])
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
    except Cliente.DoesNotExist:
        return Response({"error": "Cliente no encontrado."}, status=status.HTTP_404_NOT_FOUND)
        
    if request.method == 'GET':
        if not check_feature_permission('VER_CLIENTES')().has_permission(request, None):
            return Response({"error": "No tienes permiso para ver clientes."}, status=status.HTTP_403_FORBIDDEN)
        return Response(ClienteSerializer(cliente).data)
        
    elif request.method == 'PUT':
        if not check_feature_permission('EDITAR_CLIENTE')().has_permission(request, None):
            return Response({"error": "No tienes permiso para editar clientes."}, status=status.HTTP_403_FORBIDDEN)
        serializer = ClienteSerializer(cliente, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

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
@permission_classes([IsAuthenticated, check_feature_permission('VER_CAJA')])
def caja_view(request):
    if request.method == 'GET':
        # 1. Estadísticas
        today = timezone.now().date()
        start_of_day = timezone.make_aware(datetime.combine(today, time.min))
        end_of_day = timezone.make_aware(datetime.combine(today, time.max))

        logging.info(f"Fetching stats for date range: {start_of_day} to {end_of_day}")

        ingresos_hoy_qs = Caja.objects.filter(fecha_hora__range=(start_of_day, end_of_day), tipo='ingreso')
        egresos_hoy_qs = Caja.objects.filter(fecha_hora__range=(start_of_day, end_of_day), tipo='egreso')

        ingresos_hoy = ingresos_hoy_qs.aggregate(total=Sum('valor'))['total'] or 0
        egresos_hoy = egresos_hoy_qs.aggregate(total=Sum('valor'))['total'] or 0

        logging.info(f"Found {ingresos_hoy_qs.count()} ingresos for today with a total of {ingresos_hoy}")
        logging.info(f"Found {egresos_hoy_qs.count()} egresos for today with a total of {egresos_hoy}")

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
            start_datetime = datetime.combine(datetime.strptime(fecha_inicio, '%Y-%m-%d').date(), time.min)
            movimientos = movimientos.filter(fecha_hora__gte=start_datetime)
        if fecha_fin:
            end_datetime = datetime.combine(datetime.strptime(fecha_fin, '%Y-%m-%d').date(), time.max)
            movimientos = movimientos.filter(fecha_hora__lte=end_datetime)
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
        from ordenes.permissions import check_feature_permission
        tipo = request.data.get('tipo')
        if tipo == 'ingreso' and not check_feature_permission('CREAR_INGRESO_CAJA')().has_permission(request, None):
            return Response({'error': 'No tienes permiso para crear ingresos.'}, status=403)
        if tipo == 'egreso' and not check_feature_permission('CREAR_EGRESO_CAJA')().has_permission(request, None):
            return Response({'error': 'No tienes permiso para crear egresos.'}, status=403)
        
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
@permission_classes([IsAuthenticated, check_feature_permission('VER_RECIBOS')])
def listar_recibos_caja(request):
    # OPTIMIZACIÓN: Cargar datos del cliente y priorizar los recibos no confirmados ('Pendiente') primero
    recibos = ReciboCaja.objects.select_related('venta__cliente').annotate(
        orden_estado=Case(
            When(estado='Pendiente', then=Value(0)),
            default=Value(1),
            output_field=IntegerField(),
        )
    ).order_by('orden_estado', '-fecha', '-id')
    
    fecha_inicio = request.GET.get('fecha_inicio')
    fecha_fin = request.GET.get('fecha_fin')
    medio_pago = request.GET.get('medio_pago')
    venta_id_param = request.GET.get('venta_id') or request.GET.get('venta')
    query = request.GET.get('query')

    logger.info(f"Listar Recibos Caja - Full Params: {request.GET}")
    logger.info(f"Listar Recibos Caja - Parsed: venta_id={venta_id_param}, query={query}")

    if fecha_inicio:
        recibos = recibos.filter(fecha__gte=fecha_inicio)
    if fecha_fin:
        recibos = recibos.filter(fecha__lte=fecha_fin)
    if medio_pago:
        recibos = recibos.filter(metodo_pago=medio_pago)
    if venta_id_param:
        try:
            v_id = int(venta_id_param)
            recibos = recibos.filter(venta__id=v_id)
            logger.info(f"Filtering recibos by venta_id={v_id}. Count before pagination: {recibos.count()}")
        except ValueError:
            logger.warning(f"Invalid venta_id parameter: {venta_id_param}")
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
@permission_classes([IsAuthenticated, check_feature_permission('VER_COMPROBANTES_EGRESO')])
def listar_comprobantes_egreso(request):
    # OPTIMIZACIÓN: Cargar datos del proveedor relacionados en una sola consulta
    egresos = ComprobanteEgreso.objects.select_related('proveedor').order_by('-fecha', '-id')

    fecha_inicio = request.GET.get('fecha_inicio')
    fecha_fin = request.GET.get('fecha_fin')
    medio_pago = request.GET.get('medio_pago')
    proveedor_id = request.GET.get('proveedor')
    query = request.GET.get('query')

    if fecha_inicio:
        egresos = egresos.filter(fecha__gte=fecha_inicio)
    if fecha_fin:
        egresos = egresos.filter(fecha__lte=fecha_fin)
    if medio_pago:
        egresos = egresos.filter(medio_pago=medio_pago)
    if proveedor_id:
        egresos = egresos.filter(proveedor__id=proveedor_id)
    if query:
        egresos = egresos.filter(Q(id__icontains=query) | Q(concepto__icontains=query) | Q(descripcion__icontains=query) | Q(proveedor__nombre_empresa__icontains=query))

    paginator = ComprobanteEgresoPagination()
    page = paginator.paginate_queryset(egresos, request)
    return paginator.get_paginated_response(ComprobanteEgresoSerializer(page, many=True).data)

@api_view(['POST'])
@permission_classes([IsAuthenticated, check_feature_permission('CREAR_COMPROBANTE_EGRESO')])
@transaction.atomic
def crear_comprobante_egreso(request):
    from suministros.models import FacturaProveedor
    logger.info(f"Received data for crear_comprobante_egreso: {request.data}")
    try:
        facturas_ids = request.data.get('facturas_ids', [])
        
        # Build payload for serializer (exclude facturas_ids)
        data = {k: v for k, v in request.data.items() if k != 'facturas_ids'}
        
        # Auto-generate concepto if facturas selected
        if facturas_ids:
            facturas = FacturaProveedor.objects.filter(id__in=facturas_ids)
            ids_str = ', '.join(str(f.id_manual) for f in facturas)
            data['concepto'] = f"Pago fact. {ids_str}"
        
        serializer = ComprobanteEgresoSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        egreso = serializer.save()
        
        # Mark facturas as paid
        if facturas_ids:
            today = date.today()
            FacturaProveedor.objects.filter(id__in=facturas_ids).update(
                estado='pagada',
                fecha_pago=today
            )
        
        if egreso.medio_pago == 'Efectivo':
            proveedor_nombre = egreso.proveedor.nombre_empresa
            if facturas_ids:
                facturas = FacturaProveedor.objects.filter(id__in=facturas_ids)
                ids_str = ', '.join(str(f.id_manual) for f in facturas)
                concepto_caja = f"Pago a {proveedor_nombre}, Fact. {ids_str}"
            else:
                concepto_caja = f"Pago a {proveedor_nombre}, CE. {egreso.id}"
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
@permission_classes([IsAuthenticated, check_feature_permission('CREAR_RECIBO')])
@transaction.atomic
def crear_recibo_caja(request):
    serializer = ReciboCajaSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    
    metodo_pago = request.data.get('metodo_pago')
    
    # Use provided date or default to today
    fecha_str_input = request.data.get('fecha')
    if fecha_str_input:
        try:
            fecha_creacion = datetime.strptime(fecha_str_input, '%Y-%m-%d').date()
        except ValueError:
            fecha_creacion = date.today()
    else:
        fecha_creacion = date.today()
        
    usuario_nombre = request.user.first_name or request.user.username
    
    # Format date as "20-nov-2025"
    fecha_str = fecha_creacion.strftime('%d-%b-%Y').lower()
    
    if metodo_pago == 'Efectivo':
        confirmacion_text = f"Confirmado el {fecha_str} por {usuario_nombre}"
        recibo = serializer.save(estado='Confirmado', confirmacion=confirmacion_text, fecha=fecha_creacion)
        # Actualizar abono y saldo de la venta
        venta = recibo.venta
        venta.abono = F('abono') + recibo.valor
        venta.saldo = F('saldo') - recibo.valor
        venta.save(update_fields=['abono', 'saldo'])
        
        # Crear movimiento de caja (ingreso)
        caja_data = {
            'concepto': f"OC. {venta.id}, RC. {recibo.id}",
            'valor': recibo.valor,
            'tipo': 'ingreso',
        }
        caja_serializer = CajaSerializer(data=caja_data, context={'request': request})
        caja_serializer.is_valid(raise_exception=True)
        caja_serializer.save()
    else:
        recibo = serializer.save(estado='Pendiente', fecha=fecha_creacion)
        
    return Response(ReciboCajaSerializer(recibo).data, status=status.HTTP_201_CREATED)

class ProveedorTelaViewSet(viewsets.ModelViewSet):
    def get_permissions(self):
        from .permissions import check_feature_permission
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), check_feature_permission('ADMINISTRAR_PROVEEDORES_TELA')()]
        return [IsAuthenticated()]
    queryset = ProveedorTela.objects.all()
    serializer_class = ProveedorTelaSerializer
    pagination_class = StandardResultsSetPagination

class DireccionEntregaViewSet(viewsets.ModelViewSet):
    def get_permissions(self):
        from .permissions import check_feature_permission
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), check_feature_permission('ADMINISTRAR_DIRECCIONES_TELA')()]
        return [IsAuthenticated()]
    queryset = DireccionEntrega.objects.all()
    serializer_class = DireccionEntregaSerializer
    pagination_class = StandardResultsSetPagination

class PedidoTelaViewSet(viewsets.ModelViewSet):
    def get_permissions(self):
        from .permissions import check_feature_permission
        if self.action in ['update', 'partial_update']:
            return [IsAuthenticated(), check_feature_permission('EDITAR_ESTADO_TELA_ORDEN')()]
        elif self.action in ['create']:
            return [IsAuthenticated(), check_feature_permission('CREAR_PEDIDO_TELA')()]
        elif self.action in ['destroy']:
            return [IsAuthenticated(), check_feature_permission('ELIMINAR_PEDIDO_TELA')()]
        return [IsAuthenticated(), check_feature_permission('VER_PEDIDOS_TELAS')()]
    queryset = PedidoTela.objects.all()
    serializer_class = PedidoTelaSerializer
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        queryset = PedidoTela.objects.select_related('proveedor', 'usuario', 'orden_asociada').prefetch_related('detalles').all().order_by('-id')

        from .permissions import check_feature_permission
        if check_feature_permission('VER_TODOS_PEDIDOS_TELAS')().has_permission(self.request, None):
            pass # Keep all
        elif check_feature_permission('VER_PROPIOS_PEDIDOS_TELAS')().has_permission(self.request, None) or self.request.user.role == 'vendedor':
            user = self.request.user
            queryset = queryset.filter(
                Q(usuario=user) |
                Q(orden_asociada__usuario=user) |
                Q(orden_asociada__venta__vendedor=user) |
                Q(orden_asociada__venta__vendedores_compartidos=user)
            ).distinct()
        else:
            queryset = queryset.none()

        # Filter by provider
        proveedor_id = self.request.query_params.get('proveedor')
        if proveedor_id:
            if proveedor_id == 'ninguno_imposible':
                queryset = queryset.none()
            elif ',' in proveedor_id:
                proveedores_list = [p.strip() for p in proveedor_id.split(',') if p.strip()]
                queryset = queryset.filter(proveedor_id__in=proveedores_list)
            else:
                queryset = queryset.filter(proveedor_id=proveedor_id)

        # Filter by status
        estado = self.request.query_params.get('estado')
        if estado:
            if estado == 'ninguno_imposible':
                queryset = queryset.none()
            elif ',' in estado:
                estados_list = [e.strip() for e in estado.split(',') if e.strip()]
                queryset = queryset.filter(estado__in=estados_list)
            else:
                queryset = queryset.filter(estado=estado)

        return queryset

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        user = request.user

        # Vendedores can edit fabric orders that are theirs or associated with their orders/sales
        if user.role == 'vendedor':
            is_associated = (
                instance.usuario == user or
                (instance.orden_asociada and instance.orden_asociada.usuario == user) or
                (instance.orden_asociada and instance.orden_asociada.venta and (
                    instance.orden_asociada.venta.vendedor == user or
                    user in instance.orden_asociada.venta.vendedores_compartidos.all()
                ))
            )
            if not is_associated:
                return Response(
                    {'error': 'No tienes permiso para editar este pedido.'},
                    status=status.HTTP_403_FORBIDDEN
                )

        # Non-admins cannot change estado when it is already 'En fabrica'
        if user.role != 'administrador' and instance.estado == 'En fabrica':
            return Response(
                {'error': 'No puedes editar un pedido en estado "En fabrica".'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Only allow the 'estado' field to be updated via PATCH
        new_estado = request.data.get('estado', instance.estado)
        serializer = self.get_serializer(instance, data={'estado': new_estado}, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)

class DetallePedidoTelaViewSet(viewsets.ModelViewSet):
    queryset = DetallePedidoTela.objects.all()
    serializer_class = DetallePedidoTelaSerializer
    permission_classes = [IsAuthenticated]


@api_view(['PATCH'])
@permission_classes([IsAuthenticated, check_feature_permission('APROBAR_RECIBO')])
@transaction.atomic
def confirmar_recibo(request, id):
    try:
        recibo = ReciboCaja.objects.get(id=id)
    except ReciboCaja.DoesNotExist:
        return Response({"error": "Recibo de Caja no encontrado."}, status=status.HTTP_404_NOT_FOUND)

    if recibo.estado == 'Confirmado':
        return Response({"message": "El recibo ya está confirmado."}, status=status.HTTP_200_OK)

    # Get current date and admin user
    fecha_confirmacion = date.today()
    admin_nombre = request.user.first_name or request.user.username
    
    # Format date as "20-nov-2025"
    fecha_str = fecha_confirmacion.strftime('%d-%b-%Y').lower()
    confirmacion_text = f"Confirmado el {fecha_str} por {admin_nombre}"
    
    recibo.estado = 'Confirmado'
    recibo.confirmacion = confirmacion_text
    recibo.save(update_fields=['estado', 'confirmacion'])

    # Actualizar abono y saldo de la venta
    venta = recibo.venta
    venta.abono = F('abono') + recibo.valor
    venta.saldo = F('saldo') - recibo.valor
    venta.save(update_fields=['abono', 'saldo'])

    return Response({"message": "Recibo confirmado y venta actualizada."}, status=status.HTTP_200_OK)



from itertools import chain
from operator import attrgetter

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def vendedor_recent_activity(request):
    user = request.user
    if user.role != 'vendedor':
        return Response({"error": "No autorizado"}, status=403)

    recent_sales = Venta.objects.filter(vendedor=user).select_related('cliente').order_by('-fecha_venta')[:5]
    for sale in recent_sales:
        sale.fecha = sale.fecha_venta
        sale.type = 'venta'

    recent_orders = OrdenPedido.objects.filter(
        Q(usuario=user) |
        Q(venta__vendedor=user) |
        Q(venta__vendedores_compartidos=user)
    ).distinct().select_related('proveedor').order_by('-fecha_creacion')[:5]
    for order in recent_orders:
        order.fecha = order.fecha_creacion
        order.type = 'pedido'

    combined_activity = sorted(
        chain(recent_sales, recent_orders),
        key=attrgetter('fecha'),
        reverse=True
    )

    data = []
    for item in combined_activity[:5]:
        if item.type == 'venta':
            data.append({
                "type": "venta",
                "id": item.id,
                "cliente": item.cliente.nombre,
                "fecha": item.fecha,
            })
        elif item.type == 'pedido':
            data.append({
                "type": "pedido",
                "id": item.id,
                "proveedor": item.proveedor.nombre_empresa,
                "fecha": item.fecha,
            })
            
    return Response(data)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def listar_ventas_pendientes_ids(request):
    user = request.user
    # Se filtran solo las ventas en estado pendiente que no hayan finalizado pedidos
    ventas = Venta.objects.filter(estado__iexact='pendiente', estado_pedidos=False)
    
    can_see_all = False
    if user.role == 'administrador':
        can_see_all = True
    else:
        from .models import RolePermission
        rp = RolePermission.objects.filter(role=user.role).first()
        if rp:
            p = rp.permissions
            if 'CREAR_ORDENES_OTROS' in p or 'VER_TODAS_VENTAS' in p or 'VER_TODAS_ORDENES' in p or 'ALL' in p:
                can_see_all = True
                
    if not can_see_all:
        ventas = ventas.filter(Q(vendedor=user) | Q(vendedores_compartidos=user)).distinct()
        
    ids = ventas.order_by('-id').values_list('id', flat=True)
    return Response(list(ids))

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def listar_transportadores(request):
    transportadores = CustomUser.objects.filter(is_active=True, role='transportador').only('id', 'first_name', 'username')
    data = [{"id": t.id, "first_name": t.first_name, "username": t.username} for t in transportadores]
    return Response(data)

@api_view(['GET'])
@permission_classes([])
def test_view(request):
    return Response({"message": "Test successful"}, status=status.HTTP_200_OK)

@api_view(['PUT', 'DELETE'])
@permission_classes([IsAuthenticated])
def editar_eliminar_observacion_venta(request, obs_id):
    try:
        observacion = ObservacionVenta.objects.get(id=obs_id)
    except ObservacionVenta.DoesNotExist:
        return Response({'error': 'Observación no encontrada.'}, status=404)

    if request.method == 'PUT':
        texto = request.data.get('texto')
        if not texto:
            return Response({'error': 'El texto de la observación no puede estar vacío.'}, status=400)
        observacion.texto = texto
        observacion.save()
        return Response({'mensaje': 'Observación actualizada correctamente.'}, status=200)

    elif request.method == 'DELETE':
        observacion.delete()
        return Response({'mensaje': 'Observación eliminada correctamente.'}, status=200)

@api_view(['PUT', 'DELETE'])
@permission_classes([IsAuthenticated])
def editar_eliminar_observacion_cliente(request, obs_id):
    try:
        observacion = ObservacionCliente.objects.get(id=obs_id)
    except ObservacionCliente.DoesNotExist:
        return Response({'error': 'Observación no encontrada.'}, status=404)

    if request.method == 'PUT':
        texto = request.data.get('texto')
        if not texto:
            return Response({'error': 'El texto de la observación no puede estar vacío.'}, status=400)
        observacion.texto = texto
        observacion.save()
        return Response({'mensaje': 'Observación actualizada correctamente.'}, status=200)

    elif request.method == 'DELETE':
        observacion.delete()
        return Response({'mensaje': 'Observación eliminada correctamente.'}, status=200)
