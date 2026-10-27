# ==================== ordenes/views.py (CORRECCIÓN FINAL-FINAL) ====================

import logging
from rest_framework import viewsets, status, generics
from rest_framework.permissions import IsAuthenticated, BasePermission
from rest_framework.views import APIView
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from .models import (
    Referencia, Proveedor, OrdenPedido, DetallePedido, CustomUser, Cliente,
    Venta, LineaVenta, ObservacionVenta, Caja, ReciboCaja, PagoReciboCaja, ComprobanteEgreso,
    ObservacionCliente, Remision, ProveedorTela, PedidoTela, DetallePedidoTela, DireccionEntrega
)
from .serializers import (
    ReferenciaSerializer, ProveedorSerializer, OrdenPedidoSerializer, OrdenPedidoListSerializer,
    DetallePedidoSerializer, ClienteSerializer, VentaSerializer,
    ObservacionVentaSerializer, CajaSerializer, ReciboCajaSerializer,
    ComprobanteEgresoSerializer, VentaDetalleSerializer,
    ObservacionClienteSerializer, RemisionSerializer,
    ProveedorTelaSerializer, PedidoTelaSerializer, DetallePedidoTelaSerializer, DireccionEntregaSerializer, UserManageSerializer
)
from .permissions import (
    IsAdministradorRole, check_feature_permission, tiene_permiso_codigo, permisos_efectivos, ADMIN_SIEMPRE,
    ventas_visibles, ordenes_visibles, clientes_visibles, ve_todas_las_ventas,
)
from .consultas_reportes import consultar_ventas, consultar_recibos_caja, consultar_comprobantes_egreso
from .clientes_datos import filtrar_clientes
from .servicios import (
    ErrorNegocio, a_decimal, auditar, formato_cop, idempotente, registrar_cierre_caja, registrar_movimiento_caja,
    saldo_caja, siguiente_consecutivo,
)
from . import business_time
from .estadisticas import total_personal, totales_personales_por_mes
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Q, F, Sum, Max, Case, When, Value, IntegerField, Exists, OuterRef, Count, Prefetch
from suministros.recepcion import contar_recibidas, rechazar, sumar_rechazadas
from decimal import Decimal, InvalidOperation
from rest_framework.exceptions import ValidationError
from datetime import date, timedelta, time, datetime
from django.utils import timezone
import calendar
import django_filters
from rest_framework.filters import SearchFilter
from rest_framework.pagination import PageNumberPagination

@api_view(['POST'])
@permission_classes([IsAuthenticated, check_feature_permission('VER_CAJA'), check_feature_permission('CERRAR_CAJA')])
def cierre_caja(request):
    user = request.user
    descuadre = request.data.get('descuadre', 0)
    signo = request.data.get('signo', 'faltante')

    try:
        descuadre_decimal = Decimal(str(descuadre))
    except (ValueError, TypeError, InvalidOperation):
        return Response({"error": "El valor de descuadre debe ser un número válido."}, status=status.HTTP_400_BAD_REQUEST)
    if not descuadre_decimal.is_finite() or descuadre_decimal < 0:
        return Response({"error": "El descuadre debe ser un número no negativo; indica faltante o sobrante en 'signo'."}, status=status.HTTP_400_BAD_REQUEST)

    if descuadre_decimal != 0:
        if signo == 'faltante':
            tipo_desc = 'faltante'
        else:
            tipo_desc = 'sobrante'
            
        formatted_descuadre = f"${descuadre_decimal:,.0f}"
        concepto = f"Cierre de caja por {user.first_name}, {tipo_desc} de {formatted_descuadre}"
    else:
        concepto = f"Cierre de caja exitoso por {user.first_name}"

    # El cierre deja constancia y conserva el saldo calculado por el servidor;
    # el descuadre queda solo en el texto (su ajuste requiere decisión, D02/P10-04).
    with transaction.atomic():
        cierre = registrar_cierre_caja(user, concepto)
        auditar(user, 'caja.cierre', cierre, {'descuadre': str(descuadre_decimal), 'signo': signo})
    return Response({"message": "Cierre de caja registrado exitosamente."}, status=status.HTTP_201_CREATED)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def dashboard_stats(request):
    user = request.user
    today = business_time.hoy()
    start_date, end_date = business_time.periodo_comercial(today)

    # For vendedores: return their specific stats with divided shared sales totals
    if user.role == 'vendedor':
        ventas = Venta.objects.filter(Q(vendedor=user) | Q(vendedores_compartidos=user)).distinct().exclude(estado=Venta.ESTADO_ANULADA)

        ventas_pendientes = ventas.filter(estado='pendiente').count()
        pedidos_pendientes = ventas.filter(estado_pedidos=False).count()

        ordenes = OrdenPedido.objects.filter(
            Q(usuario=user) |
            Q(venta__vendedor=user) |
            Q(venta__vendedores_compartidos=user)
        ).distinct()
        
        ordenes_atrasadas = ordenes.filter(estado='en_proceso', fecha_esperada__lt=today).count()

        # Reparto Total / N participantes únicos, contados ANTES del filtro
        # personal (antes se contaban sobre la relación ya filtrada, H13).
        ventas_dia = total_personal(ventas.filter(fecha_venta=today), user)
        ventas_mes = total_personal(ventas.filter(fecha_venta__gte=start_date, fecha_venta__lte=end_date), user)

        data = {
            'ventas_dia': float(ventas_dia),
            'ventas_mes': float(ventas_mes),
            'ventas_pendientes': ventas_pendientes,
            'pedidos_pendientes': pedidos_pendientes,
            'ordenes_atrasadas': ordenes_atrasadas,
            'saldo_caja': 0,
            'ultimas_ventas': []
        }
        return Response(data)

    # Dashboard general: requiere el permiso explícito (administrador lo tiene
    # siempre vía check_feature_permission) — sin esto, cualquier rol
    # autenticado (marketing, transportador, etc.) podía ver las cifras
    # globales del negocio con solo pegarle a este endpoint.
    if not check_feature_permission('VER_DASHBOARD_GENERAL')().has_permission(request, None):
        return Response({'detail': 'No tienes permiso para ver este dashboard.'}, status=403)

    # For admin/auxiliar: return global stats
    ventas = Venta.objects.exclude(estado=Venta.ESTADO_ANULADA)
    ventas_dia = ventas.filter(fecha_venta=today).aggregate(total=Sum('valor_total'))['total'] or 0
    ventas_mes = ventas.filter(fecha_venta__gte=start_date, fecha_venta__lte=end_date).aggregate(total=Sum('valor_total'))['total'] or 0

    pedidos_pendientes = ventas.filter(estado_pedidos=False).count()
    ordenes_atrasadas = OrdenPedido.objects.filter(estado='pendiente', fecha_esperada__lt=today).count()

    saldo_actual_caja = saldo_caja()

    ultimas_ventas = ventas.select_related('cliente', 'vendedor').prefetch_related('vendedores_compartidos').order_by('-fecha_venta', '-id')[:5]
    ultimas_ventas_serializer = VentaSerializer(ultimas_ventas, many=True, context={'request': request, 'ver_margenes': tiene_permiso_codigo(request, 'VER_MARGENES')})

    data = {
        'ventas_dia': float(ventas_dia),
        'ventas_mes': float(ventas_mes),
        'pedidos_pendientes': pedidos_pendientes,
        'ordenes_atrasadas': ordenes_atrasadas,
        'saldo_caja': float(saldo_actual_caja),
        'ultimas_ventas': ultimas_ventas_serializer.data
    }
    return Response(data)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def sales_chart_data(request):
    today = business_time.hoy()
    current_year = today.year
    last_year = current_year - 1
    user = request.user

    # Salvo cuando el propio vendedor pide sus datos, esto es el gráfico
    # global (o el de otro vendedor puntual) del dashboard general.
    if user.role != 'vendedor' and not check_feature_permission('VER_DASHBOARD_GENERAL')().has_permission(request, None):
        return Response({'detail': 'No tienes permiso para ver este gráfico.'}, status=403)

    ventas = Venta.objects.exclude(estado=Venta.ESTADO_ANULADA).filter(fecha_venta__year__in=[last_year, current_year])

    vendedor_param = request.GET.get('vendedor') or request.GET.get('id_vendedor')
    persona_id = None
    if user.role == 'vendedor':
        persona_id = user.id
    elif vendedor_param:
        try:
            persona_id = int(vendedor_param)
        except ValueError:
            persona_id = None

    if persona_id is not None:
        # Métrica personal: Total / N participantes únicos (H13).
        ventas = ventas.filter(Q(vendedor_id=persona_id) | Q(vendedores_compartidos__id=persona_id)).distinct()
        por_mes = totales_personales_por_mes(ventas, persona_id)
    else:
        # Empresa: 100 % de cada venta.
        from django.db.models.functions import ExtractMonth, ExtractYear
        por_mes = {}
        filas = ventas.annotate(y=ExtractYear('fecha_venta'), m=ExtractMonth('fecha_venta')).values('y', 'm').annotate(total=Sum('valor_total'))
        for fila in filas:
            por_mes[(fila['y'], fila['m'])] = fila['total'] or 0

    current_year_data = {i: por_mes.get((current_year, i), 0) for i in range(1, 13)}
    last_year_data = {i: por_mes.get((last_year, i), 0) for i in range(1, 13)}

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
        # Misma función que usa cada endpoint protegido: lo que /user/ anuncia
        # es exactamente lo que la API concede (P02-03).
        perms = sorted(permisos_efectivos(user))
        from .oficina import acceso_oficina
        return Response({
            "id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "role": user.role,
            "acceso_rapido_ia": user.acceso_rapido_ia,
            "permissions": perms,
            "acceso_oficina": acceso_oficina(user)
        })

class RolePermissionViewSet(viewsets.ModelViewSet):
    from .models import RolePermission
    queryset = RolePermission.objects.all()
    permission_classes = [IsAuthenticated, IsAdministradorRole]
    # Los roles son fijos (CustomUser.ROLE_CHOICES) y se siembran por migración:
    # aquí solo se consultan y editan (nunca se crean ni se borran).
    http_method_names = ['get', 'put', 'patch', 'head', 'options']

    def get_queryset(self):
        # Solo lectura: antes este GET creaba filas vacías y con eso quitaba
        # los permisos por defecto del auxiliar (H20).
        from .models import RolePermission
        return RolePermission.objects.all().order_by('id')

    def get_serializer_class(self):
        from rest_framework import serializers
        from .models import RolePermission
        class RolePermissionSerializer(serializers.ModelSerializer):
            permissions = serializers.ListField(child=serializers.CharField(max_length=60), allow_empty=True)

            class Meta:
                model = RolePermission
                fields = ['id', 'role', 'permissions']
                read_only_fields = ['role']
        return RolePermissionSerializer

    def perform_update(self, serializer):
        antes = list(serializer.instance.permissions or [])
        # Resguardo: el rol administrador nunca debe poder quedar sin acceso
        # a esta misma pantalla, para no bloquear la única vía de recuperación.
        if serializer.instance.role == 'administrador':
            perms = set(serializer.validated_data.get('permissions') or [])
            perms.update(ADMIN_SIEMPRE)
            instancia = serializer.save(permissions=sorted(perms))
        else:
            instancia = serializer.save()
        auditar(self.request.user, 'permisos.rol', instancia, {'antes': antes, 'despues': instancia.permissions})

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def cambiar_contrasena(request):
    user = request.user
    old_password = request.data.get("old_password")
    new_password = request.data.get("new_password")
    if not new_password:
        return Response({"error": "La nueva contraseña es obligatoria."}, status=status.HTTP_400_BAD_REQUEST)
    if not user.check_password(old_password):
        return Response({"error": "La contraseña actual es incorrecta."}, status=status.HTTP_400_BAD_REQUEST)
    try:
        validate_password(new_password, user)
    except DjangoValidationError as e:
        return Response({"error": " ".join(e.messages)}, status=status.HTTP_400_BAD_REQUEST)
    user.set_password(new_password)
    user.save()
    return Response({"message": "Contraseña actualizada correctamente."}, status=status.HTTP_200_OK)

class ReferenciaViewSet(viewsets.ModelViewSet):
    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), check_feature_permission('ADMINISTRAR_REFERENCIAS')()]
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
            return [IsAuthenticated(), check_feature_permission('ADMINISTRAR_PROVEEDORES')()]
        return [IsAuthenticated()]
    # Orden estable (nombre + id) para paginar sin repetir ni saltar, y búsqueda
    # en servidor para alcanzar registros más allá de la primera página (H25).
    queryset = Proveedor.objects.all().order_by('nombre_empresa', 'id')
    serializer_class = ProveedorSerializer
    pagination_class = StandardResultsSetPagination
    filter_backends = [SearchFilter]
    search_fields = ['nombre_empresa', 'nombre_encargado']

class UserViewSet(viewsets.ModelViewSet):
    """Administración de usuarios (P02-04, H21; política provisional D01).
    Quien no es administrador puede gestionar cuentas no administradoras, pero
    no asignar ni quitar el rol administrador, ni tocar cuentas administradoras,
    ni cambiar su propio rol. El último administrador activo no puede quedar
    degradado ni desactivado. Borrar = desactivar (se conserva la historia)."""
    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), check_feature_permission('ADMINISTRAR_USUARIOS')()]
        return [IsAuthenticated(), check_feature_permission('VER_USUARIOS')()]
    queryset = CustomUser.objects.all().order_by('-is_active', 'first_name', 'last_name')
    serializer_class = UserManageSerializer
    pagination_class = StandardResultsSetPagination

    def _es_admin(self):
        return self.request.user.role == 'administrador'

    def _otros_admins_activos(self, user):
        return CustomUser.objects.filter(role='administrador', is_active=True).exclude(pk=user.pk).exists()

    def _validar_cambio(self, instancia, datos):
        """None si el cambio está permitido; Response de rechazo si no."""
        actor = self.request.user
        nuevo_rol = datos.get('role', instancia.role if instancia else None)
        if not self._es_admin():
            if 'acceso_rapido_ia' in datos:
                return Response({'error': 'Solo un administrador puede configurar el acceso rápido a IA por usuario.'}, status=status.HTTP_403_FORBIDDEN)
            if nuevo_rol == 'administrador' or (instancia and instancia.role == 'administrador'):
                return Response({'error': 'Solo un administrador puede asignar o modificar cuentas de administrador.'}, status=status.HTTP_403_FORBIDDEN)
            if instancia and instancia.pk == actor.pk and 'role' in datos and datos['role'] != instancia.role:
                return Response({'error': 'No puedes cambiar tu propio rol.'}, status=status.HTTP_403_FORBIDDEN)
        if instancia and instancia.role == 'administrador' and instancia.is_active:
            pierde_admin = nuevo_rol != 'administrador'
            se_desactiva = str(datos.get('is_active', True)).lower() in ('false', '0')
            if (pierde_admin or se_desactiva) and not self._otros_admins_activos(instancia):
                return Response({'error': 'No se puede dejar el sistema sin un administrador activo.'}, status=status.HTTP_400_BAD_REQUEST)
        return None

    def create(self, request, *args, **kwargs):
        rechazo = self._validar_cambio(None, request.data)
        return rechazo or super().create(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        rechazo = self._validar_cambio(self.get_object(), request.data)
        return rechazo or super().update(request, *args, **kwargs)

    def perform_create(self, serializer):
        user = serializer.save()
        auditar(self.request.user, 'usuario.crear', user, {'role': user.role, 'is_active': user.is_active, 'acceso_rapido_ia': user.acceso_rapido_ia})

    def perform_update(self, serializer):
        antes = {'role': serializer.instance.role, 'is_active': serializer.instance.is_active, 'acceso_rapido_ia': serializer.instance.acceso_rapido_ia}
        cambia_clave = bool(serializer.validated_data.get('password'))
        user = serializer.save()
        auditar(self.request.user, 'usuario.editar', user, {
            'antes': antes, 'despues': {'role': user.role, 'is_active': user.is_active, 'acceso_rapido_ia': user.acceso_rapido_ia},
            'cambio_contrasena': cambia_clave,
        })

    def destroy(self, request, *args, **kwargs):
        instancia = self.get_object()
        rechazo = self._validar_cambio(instancia, {'is_active': False})
        if rechazo:
            return rechazo
        # Desactivar en vez de borrar: el usuario es autor/vendedor de documentos
        # históricos (H12). El acceso se pierde de inmediato.
        instancia.is_active = False
        instancia.save(update_fields=['is_active'])
        auditar(request.user, 'usuario.desactivar', instancia)
        return Response(status=status.HTTP_204_NO_CONTENT)

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
                    # Misma fuente de permisos que el resto de la API (P02-03).
                    return any(
                        tiene_permiso_codigo(request, codigo)
                        for codigo in ('CREAR_ORDEN', 'CREAR_PROPIAS_ORDENES', 'CREAR_ORDENES_OTROS')
                    )
            return [IsAuthenticated(), DynamicCreateOrderPermission()]
        elif self.action in ['update', 'partial_update']:
            class DynamicUpdateOrderPermission(BasePermission):
                def has_permission(self, request, view):
                    if not request.user or not request.user.is_authenticated:
                        return False
                    from .permissions import check_feature_permission
                    can_edit_estado = check_feature_permission('EDITAR_ESTADO_ORDEN')().has_permission(request, view)
                    can_edit_tela = check_feature_permission('EDITAR_ESTADO_TELA_ORDEN')().has_permission(request, view)
                    return can_edit_estado or can_edit_tela or request.user.role == 'vendedor'
            return [IsAuthenticated(), DynamicUpdateOrderPermission()]
        elif self.action in ['destroy']:
            return [IsAuthenticated(), check_feature_permission('EDITAR_ESTADO_ORDEN')()]
        return [IsAuthenticated(), check_feature_permission('VER_ORDENES')()]
    http_method_names = ['get', 'post', 'put', 'patch', 'delete']
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        # Esta función sobreescribe el queryset base para cada petición, manteniendo la optimización.
        # Relaciones que lee OrdenPedidoSerializer; sin ellas eran ~3 consultas
        # por orden (P08-04).
        base_queryset = OrdenPedido.objects.select_related(
            'proveedor', 'usuario', 'venta__vendedor'
        ).prefetch_related(_detalles_con_recibidas(), 'pedidos_telas__detalles').order_by('-id')
        if tiene_permiso_codigo(self.request, 'VER_TODAS_ORDENES'):
            return base_queryset
        if tiene_permiso_codigo(self.request, 'VER_PROPIAS_ORDENES') or self.request.user.role == 'vendedor':
            user = self.request.user
            return base_queryset.filter(
                Q(usuario=user) |
                Q(venta__vendedor=user) |
                Q(venta__vendedores_compartidos=user)
            ).distinct()
        return base_queryset.none()

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['ver_costos'] = tiene_permiso_codigo(self.request, 'VER_COSTOS_ORDEN')
        return context

    def perform_create(self, serializer):
        user = self.request.user
        vendedor_id = self.request.data.get('vendedor') or self.request.data.get('usuario')
        
        can_create_others = tiene_permiso_codigo(self.request, 'CREAR_ORDENES_OTROS') or tiene_permiso_codigo(self.request, 'CREAR_ORDEN')

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
        from .permissions import check_feature_permission

        can_edit_estado = check_feature_permission('EDITAR_ESTADO_ORDEN')().has_permission(request, self)
        can_edit_tela = (
            request.user.role == 'vendedor' or 
            check_feature_permission('EDITAR_ESTADO_TELA_ORDEN')().has_permission(request, self)
        )
        can_edit_costo = (
            request.user.role in ['administrador', 'auxiliar'] and 
            check_feature_permission('VER_COSTOS_ORDEN')().has_permission(request, self)
        )

        new_estado = data.get('estado')
        if new_estado == 'anulado' and instance.estado != 'anulado':
            if not check_feature_permission('ANULAR_ORDEN_PEDIDO')().has_permission(request, self):
                return Response({"error": "No tienes permiso para anular órdenes de pedido."}, status=status.HTTP_403_FORBIDDEN)

        filtered_data = {}
        if 'costo' in data and can_edit_costo:
            filtered_data['costo'] = data['costo']
        if 'estado' in data and can_edit_estado:
            filtered_data['estado'] = data['estado']
        if 'tela' in data and can_edit_tela:
            filtered_data['tela'] = data['tela']

        if not filtered_data and data:
            return Response({"error": "No tienes permisos para modificar estos campos de la orden."}, status=status.HTTP_403_FORBIDDEN)

        serializer = self.get_serializer(instance, data=filtered_data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)

class DetallePedidoViewSet(viewsets.ModelViewSet):
    queryset = DetallePedido.objects.select_related('referencia', 'orden').all()
    serializer_class = DetallePedidoSerializer
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        return self.queryset.filter(orden__in=ordenes_visibles(self.request))

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            from .serializers import DetallePedidoWriteSerializer
            return DetallePedidoWriteSerializer
        return DetallePedidoSerializer

    def perform_create(self, serializer):
        if not ordenes_visibles(self.request).filter(pk=serializer.validated_data['orden'].pk).exists():
            raise ValidationError({'orden': 'Orden no encontrada.'})
        serializer.save()

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), check_feature_permission('EDITAR_ESTADO_ORDEN')()]
        if self.action == 'rechazos' and self.request.method == 'POST':
            return [IsAuthenticated(), check_feature_permission('CREAR_FACTURA')()]
        return [IsAuthenticated(), check_feature_permission('VER_ORDENES')()]

    @action(detail=True, methods=['get', 'post'])
    def rechazos(self, request, pk=None):
        """Mercancía rechazada al recibir (P11-01): no crea unidades y la línea sigue pendiente."""
        linea = self.get_object()
        if request.method == 'POST':
            rechazar(linea.pk, request.data.get('cantidad'), request.data.get('motivo'), request.user)
        filas = linea.rechazos.select_related('usuario').order_by('-fecha', '-id')
        return Response([{'cantidad': r.cantidad, 'motivo': r.motivo, 'fecha': r.fecha,
                          'usuario': (r.usuario.first_name or r.usuario.username) if r.usuario else None} for r in filas],
                        status=status.HTTP_201_CREATED if request.method == 'POST' else status.HTTP_200_OK)

# ... (El resto del archivo no cambia, lo incluyo para que sea el código completo) ...

import logging

logger = logging.getLogger(__name__)

@api_view(['GET'])
@permission_classes([IsAuthenticated, check_feature_permission('VER_ORDENES')])
def listar_pedidos(request):
    try:
        # select_related cubre todos los accesos de FK en OrdenPedidoListSerializer
        # de un solo golpe, eliminando N+1 queries
        pedidos = OrdenPedido.objects.select_related(
            'proveedor', 'usuario', 'venta__vendedor'
        ).all()

        # Mismo alcance que las rutas de detalle (ordenes_visibles).
        pedidos = ordenes_visibles(request, pedidos)
        if request.user.role != 'vendedor':
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
            # Las órdenes de Feria del Hogar deben poder recibir pedidos de material aunque
            # no se haya marcado "requiere tela" al crearlas (no siempre se sabe de antemano) —
            # por eso siempre se incluyen aquí, sin importar su campo `tela`.
            pedidos = pedidos.filter(Q(tela=tela) | Q(es_feria_hogar=True))

        pedidos = pedidos.order_by('-id')

        # Usar el serializer ligero — sin detalles ni telas_asociadas
        serializer = OrdenPedidoListSerializer(
            pedidos, many=True, context={'ver_costos': tiene_permiso_codigo(request, 'VER_COSTOS_ORDEN')}
        )
        return Response(serializer.data)
    except Exception as e:
        logger.error(f"Error en listar_pedidos: {e}", exc_info=True)
        return Response({"error": "Ocurrió un error inesperado en el servidor."}, status=500)


def _detalles_con_recibidas():
    """Líneas con su referencia y las unidades recibidas por factura (P11-01), en una consulta."""
    return Prefetch('detalles', queryset=DetallePedido.objects.select_related('referencia', 'subcategoria').annotate(
        n_recibidas=contar_recibidas(), n_rechazadas=sumar_rechazadas()))


@api_view(['GET'])
@permission_classes([IsAuthenticated, check_feature_permission('VER_ORDENES')])
def detalle_orden_completo(request, orden_id):
    """Endpoint ligero para obtener los detalles completos de una OP (para NuevaFactura).
    Devuelve detalles del pedido + telas_asociadas. Usado de forma lazy al seleccionar la OP."""
    try:
        # Mismo alcance por objeto que la ruta normal (antes devolvía órdenes
        # ajenas con costo, H06).
        orden = ordenes_visibles(request, OrdenPedido.objects.select_related(
            'proveedor', 'usuario', 'venta__vendedor'
        ).prefetch_related(
            _detalles_con_recibidas(),
            'pedidos_telas__detalles'
        )).get(id=orden_id)
        serializer = OrdenPedidoSerializer(orden, context={'ver_costos': tiene_permiso_codigo(request, 'VER_COSTOS_ORDEN')})
        return Response(serializer.data)
    except OrdenPedido.DoesNotExist:
        return Response({"error": "Orden no encontrada"}, status=404)
    except Exception as e:
        logger.error(f"Error en detalle_orden_completo {orden_id}: {e}", exc_info=True)
        return Response({"error": "Error al obtener la orden"}, status=500)


class _PuedeCrearOrdenPermission(BasePermission):
    """Mismo criterio que la acción 'create' de OrdenPedidoViewSet — se
    reutiliza aquí para gatear la subida de la foto de Feria del Hogar, ya
    que solo tiene sentido para quien puede crear el pedido al que se anexa."""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return any(tiene_permiso_codigo(request, c) for c in ('CREAR_ORDEN', 'CREAR_PROPIAS_ORDENES', 'CREAR_ORDENES_OTROS'))


@api_view(['POST'])
@permission_classes([IsAuthenticated, _PuedeCrearOrdenPermission])
def subir_imagen_pedido_feria(request):
    """
    POST /api/ordenes-pedido/feria-hogar/subir-imagen/
    Sube la foto de un pedido de Feria del Hogar a Cloudinary (mismo mecanismo
    que las imágenes de Gestión Web) y devuelve su URL — se guarda luego en
    OrdenPedido.imagen_feria_hogar como parte del payload normal de creación.
    """
    import uuid
    from paginaweb.cloudinary_client import upload_to_cloudinary, CloudinaryUploadError
    from paginaweb.image_utils import validate_image, InvalidImageError, optimize_image_for_upload

    f = request.FILES.get('imagen') or request.FILES.get('file') or request.FILES.get('image')
    if not f:
        return Response({"error": "No se envió ningún archivo"}, status=status.HTTP_400_BAD_REQUEST)

    max_size = 15 * 1024 * 1024
    if f.size > max_size:
        return Response({"error": "La imagen supera el máximo de 15 MB"}, status=status.HTTP_400_BAD_REQUEST)

    file_bytes = f.read()
    try:
        ext, content_type = validate_image(file_bytes)
    except InvalidImageError:
        return Response({"error": "El archivo no es una imagen válida."}, status=status.HTTP_400_BAD_REQUEST)

    file_bytes, ext, content_type = optimize_image_for_upload(file_bytes, ext, content_type)

    filename = f"pedidos_feria_hogar/{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}{ext}"
    try:
        url = upload_to_cloudinary(file_bytes, filename, content_type)
    except CloudinaryUploadError:
        logger.exception("Error subiendo imagen de pedido Feria del Hogar a Cloudinary")
        return Response({"error": "No se pudo subir la imagen. Intenta de nuevo."}, status=status.HTTP_502_BAD_GATEWAY)

    return Response({"ok": True, "url": url})


@api_view(['GET'])
@permission_classes([IsAuthenticated, check_feature_permission('VER_ORDENES')])
def detalles_pedido(request, orden_id):
    if not ordenes_visibles(request).filter(id=orden_id).exists():
        return Response({"error": "Orden no encontrada"}, status=404)
    try:
        # OPTIMIZACIÓN: Usar `select_related` y `only` para traer solo lo necesario
        detalles = DetallePedido.objects.filter(orden_id=orden_id).select_related('referencia', 'subcategoria').only(
            'cantidad', 'especificaciones', 'referencia__nombre', 'subcategoria__nombre'
        ).annotate(n_recibidas=contar_recibidas(), n_rechazadas=sumar_rechazadas())
        
        # Obtener la observación de la orden
        try:
            orden = OrdenPedido.objects.get(id=orden_id)
            observacion = orden.observacion
        except OrdenPedido.DoesNotExist:
            observacion = None

        detalles_data = [{
            "cantidad": d.cantidad,
            "especificaciones": d.especificaciones,
            "referencia": d.referencia.nombre if d.referencia else "N/A",
            "referencia_nombre": d.referencia.nombre if d.referencia else "N/A",
            "subcategoria_nombre": d.subcategoria.nombre if d.subcategoria_id else "",
            # Unidades recibidas por factura y rechazadas al recibir (P11-01).
            "id": d.id,
            "recibidas": d.n_recibidas,
            "rechazadas": d.n_rechazadas,
        } for d in detalles]

        # --- NUEVO: Obtener los PedidoTela asociados a esta orden ---
        # También los pedidos de tela hechos desde la venta para los mismos productos de esta
        # orden (sin OP asociada: se enlazan por la línea de venta, 2026-10-09).
        lineas = [l for l in DetallePedido.objects.filter(orden_id=orden_id, linea_venta__isnull=False).values_list('linea_venta_id', flat=True)]
        pedidos_tela_qs = PedidoTela.objects.filter(
            Q(orden_asociada_id=orden_id) | Q(detalles__linea_venta_id__in=lineas)
        ).distinct().select_related('proveedor').prefetch_related('detalles').order_by('id')

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
                "observacion": pt.observacion or '',
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
    @idempotente('venta.crear')
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
            # El ejecutor y otros clientes API pueden dejar que el servidor
            # reserve el consecutivo; nunca se inventa un número comercial.
            from django.db.models import Max
            venta_data['id'] = siguiente_consecutivo('venta', 1, Venta.objects.aggregate(n=Max('id'))['n'] or 0)
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
        except (TypeError, ValueError):
            raise ValidationError({"vendedor": "El id del vendedor no es válido."})
        venta_data.update({'cliente': cliente.id, 'vendedor': vendedor.id, 'estado': 'pendiente', 'saldo': venta_data.get('valor_total', 0)})
        venta_serializer = VentaSerializer(data=venta_data)
        venta_serializer.is_valid(raise_exception=True)
        venta = venta_serializer.save()

        # Guardar líneas propias si vienen en la petición (P09-03 / P12-01)
        from listaprecios.models import VarianteProducto, GrupoTela, Cotizacion
        from listaprecios.services import tope_descuento, costo_lista

        lineas_data = request.data.get('lineas') or venta_data.get('lineas') or []
        for l_data in lineas_data:
            cant = max(1, int(l_data.get('cantidad', 1)))
            pu = Decimal(str(l_data.get('precio_unitario', 0)))
            desc = Decimal(str(l_data.get('descuento', 0)))
            subt_bruto = (pu * cant).quantize(Decimal('0.01'))

            variante_id = l_data.get('variante') or l_data.get('variante_id')
            variante = None
            if variante_id:
                try:
                    variante = VarianteProducto.objects.filter(id=int(variante_id)).prefetch_related('cargos').first()
                except (ValueError, TypeError):
                    pass

            # Validar tope de descuento por variante (o 25% por defecto)
            tope_pct = tope_descuento(variante)
            tope_valor = (subt_bruto * tope_pct / Decimal('100')).quantize(Decimal('0.01'))
            if desc > tope_valor:
                nombre_prod = l_data.get('variante_nombre') or (variante.nombre if variante else 'línea')
                raise ValidationError({
                    'lineas': f"El descuento de ${desc:,.2f} en '{nombre_prod}' supera el tope permitido del {tope_pct}% (${tope_valor:,.2f})."
                })

            subt = max(Decimal('0.00'), subt_bruto - desc)

            # Calcular o asignar costo estimado congelado
            costo_est = None
            if variante:
                grupo_val = l_data.get('grupo_tela') or l_data.get('grupo_nombre') or l_data.get('grupoId')
                grupo_obj = None
                if grupo_val is not None:
                    try:
                        grupo_obj = GrupoTela.objects.filter(id=int(grupo_val)).first()
                    except (ValueError, TypeError):
                        grupo_obj = GrupoTela.objects.filter(nombre__iexact=str(grupo_val)).first()
                costo_est = costo_lista(variante, grupo_obj, l_data.get('opcionales') or [])
            elif l_data.get('costo_estimado') is not None:
                try:
                    costo_est = Decimal(str(l_data['costo_estimado'])).quantize(Decimal('0.01'))
                except Exception:
                    pass

            LineaVenta.objects.create(
                venta=venta,
                variante=variante,
                referencia_id=l_data.get('referencia') or l_data.get('referencia_id'),
                producto_nombre=l_data.get('producto_nombre') or l_data.get('linea_nombre', 'Producto'),
                variante_nombre=l_data.get('variante_nombre', ''),
                categoria_nombre=l_data.get('categoria_nombre', ''),
                grupo_tela=l_data.get('grupo_tela') or l_data.get('grupo_nombre', ''),
                especificaciones=l_data.get('especificaciones') or l_data.get('notas', ''),
                cantidad=cant,
                precio_unitario=pu,
                descuento=desc,
                subtotal=subt,
                costo_estimado=costo_est,
                fecha_compromiso=l_data.get('fecha_compromiso') or venta.fecha_entrega,
                opcionales=l_data.get('opcionales') or [],
                notas=l_data.get('notas', ''),
            )

        # Vincular cotización si viene indicada (P09-04)
        cotizacion_id = request.data.get('cotizacion_id') or venta_data.get('cotizacion_id')
        if cotizacion_id:
            Cotizacion.objects.filter(id=cotizacion_id).update(
                venta_asociada=venta,
                estado=Cotizacion.ESTADO_CONVERTIDA,
                cliente=cliente,
                fecha_conversion=timezone.now(),
            )

        if observacion_texto:
            venta.observaciones.create(autor=request.user, texto=observacion_texto)
        return Response({"message": "Venta creada.", "venta_id": venta.id, "cliente_id": cliente.id}, status=201)

class EditarVentaClienteView(APIView):
    permission_classes = [IsAuthenticated]

    def put(self, request, id):
        # EDITAR_VENTA (completa) y EDITAR_ESTADO_VENTA/EDITAR_ESTADO_PEDIDOS_VENTA
        # comparten esta ruta; se valida por separado venta ajena, estados,
        # cliente y cabecera (H05).
        has_full = tiene_permiso_codigo(request, 'EDITAR_VENTA')
        has_estado = tiene_permiso_codigo(request, 'EDITAR_ESTADO_VENTA')
        has_pedidos = tiene_permiso_codigo(request, 'EDITAR_ESTADO_PEDIDOS_VENTA')
        if not (has_full or has_estado or has_pedidos):
            return Response({"error": "No tienes permiso para editar ventas."}, status=status.HTTP_403_FORBIDDEN)

        cliente_data = request.data.get('cliente') or {}
        venta_data = request.data.get('venta') or {}
        if not isinstance(cliente_data, dict) or not isinstance(venta_data, dict):
            return Response({"error": "Formato inválido."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            with transaction.atomic():
                # Misma selección de objetos que la consulta: una venta ajena no existe para quien no puede verla.
                venta = ventas_visibles(request, Venta.objects.select_for_update()).filter(id=id).first()
                if venta is None:
                    raise ErrorNegocio("Venta no encontrada.", status.HTTP_404_NOT_FOUND, campo='error')

                if not has_full:
                    allowed_keys = set()
                    if has_estado: allowed_keys.add('estado')
                    if has_pedidos: allowed_keys.add('estado_pedidos')
                    if not set(venta_data.keys()).issubset(allowed_keys):
                        raise ErrorNegocio("Solo tienes permiso para modificar los estados autorizados.", status.HTTP_403_FORBIDDEN, campo='error')

                # El cliente solo se modifica con edición completa o EDITAR_CLIENTE;
                # se comparan valores para no rechazar un formulario que reenvía el cliente sin cambios.
                cambios_cliente = {k: v for k, v in cliente_data.items()
                                   if k not in ('id',) and str(getattr(venta.cliente, k, v) or '') != str(v or '')}
                if cambios_cliente and not (has_full or tiene_permiso_codigo(request, 'EDITAR_CLIENTE')):
                    raise ErrorNegocio("No tienes permiso para modificar los datos del cliente.", status.HTTP_403_FORBIDDEN, campo='error')

                # Nota: el valor real en BD es 'anulada' (Venta.ESTADO_CHOICES), no 'anulado' —
                # se compara con startswith('anulad') para no dejar este gate muerto si el valor cambia.
                nuevo_estado_raw = (venta_data.get('estado') or '').lower()
                estado_actual_raw = (venta.estado or '').lower()
                if nuevo_estado_raw.startswith('anulad') and not estado_actual_raw.startswith('anulad'):
                    if not tiene_permiso_codigo(request, 'ANULAR_ORDEN_PEDIDO'):
                        raise ErrorNegocio("No tienes permiso para anular ventas u órdenes.", status.HTTP_403_FORBIDDEN, campo='error')

                if cambios_cliente:
                    cliente_serializer = ClienteSerializer(venta.cliente, data=cambios_cliente, partial=True)
                    cliente_serializer.is_valid(raise_exception=True)
                    cliente_serializer.save()

                venta_serializer = VentaSerializer(venta, data=venta_data, partial=True, context={'request': request})
                venta_serializer.is_valid(raise_exception=True)
                new_valor_total = venta_serializer.validated_data.get('valor_total', venta.valor_total)
                antes = {'estado': venta.estado, 'valor_total': str(venta.valor_total)}
                venta = venta_serializer.save(saldo=new_valor_total - venta.abono)
                auditar(request.user, 'venta.editar', venta, {
                    'antes': antes, 'campos': sorted(venta_data.keys()), 'cliente': sorted(cambios_cliente.keys()),
                })
            return Response({"message": "Venta actualizada.", "venta_id": venta.id}, status=200)
        except ErrorNegocio as e:
            return e.respuesta()
        except ValidationError as e:
            # Error de dato (400), nunca un 500 genérico. La transacción ya se revirtió.
            detail = getattr(e, 'detail', str(e))
            return Response(detail if isinstance(detail, dict) else {"error": str(detail)}, status=status.HTTP_400_BAD_REQUEST)

@api_view(['GET'])
@permission_classes([IsAuthenticated, check_feature_permission('VER_VENTAS')])
def listar_ventas(request):
    ventas = consultar_ventas(request)

    is_report = request.GET.get('is_report')
    if is_report == 'true':
        ventas_data = []
        for v in ventas:
            ventas_data.append({
                'id': v.id,
                'estado': v.estado,
                'vendedor': v.vendedor_id,
                'vendedor_nombre': v.vendedor.first_name if v.vendedor else None,
                'vendedores_compartidos': [vc.id for vc in v.vendedores_compartidos.all()],
                # Nombres para el filtro de vendedores aunque el usuario ya no esté activo.
                'vendedores_compartidos_nombres': [vc.first_name for vc in v.vendedores_compartidos.all()],
                'valor_total': v.valor_total,
                'abono': v.abono,
                'saldo': v.saldo,
                'fecha_venta': v.fecha_venta,
                'sede': v.sede,
                'es_feria_hogar': v.es_feria_hogar,
                'es_postferia': v.es_postferia,
            })
        return Response(ventas_data)

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
            serializer = VentaSerializer(ventas_page, many=True, context={'request': request, 'ver_margenes': tiene_permiso_codigo(request, 'VER_MARGENES')})
            return Response({
                'count': total_count,
                'results': serializer.data
            })
        except ValueError:
            pass

    serializer = VentaSerializer(ventas, many=True, context={'request': request, 'ver_margenes': tiene_permiso_codigo(request, 'VER_MARGENES')})
    return Response(serializer.data)

@api_view(['POST'])
@permission_classes([IsAuthenticated, check_feature_permission('MARCAR_VENTA_FACTURADA')])
def marcar_venta_facturada(request, id):
    """POST /api/ventas/<id>/facturada/ — {facturada: true|false}. Contabilidad (o quien tenga
    MARCAR_VENTA_FACTURADA) marca la venta como facturada; queda quién y cuándo (2026-10-21)."""
    facturada = request.data.get('facturada')
    if not isinstance(facturada, bool):
        return Response({'facturada': 'Indica true o false.'}, status=status.HTTP_400_BAD_REQUEST)
    with transaction.atomic():
        venta = ventas_visibles(request, Venta.objects.select_for_update()).filter(id=id).first()
        if venta is None:
            return Response({'error': 'Venta no encontrada.'}, status=status.HTTP_404_NOT_FOUND)
        if facturada and venta.estado == Venta.ESTADO_ANULADA:
            return Response({'error': 'Una venta anulada no se marca como facturada.'}, status=status.HTTP_400_BAD_REQUEST)
        if venta.facturada != facturada:
            venta.facturada = facturada
            venta.facturada_en = timezone.now() if facturada else None
            venta.facturada_por = request.user if facturada else None
            venta.save(update_fields=['facturada', 'facturada_en', 'facturada_por'])
            auditar(request.user, 'venta.facturada' if facturada else 'venta.no_facturada', venta, {'facturada': facturada})
    nombre = (venta.facturada_por.get_full_name() or venta.facturada_por.username) if venta.facturada_por else ''
    return Response({'id': venta.id, 'facturada': venta.facturada, 'facturada_en': venta.facturada_en, 'facturada_por_nombre': nombre})


@api_view(['GET'])
@permission_classes([IsAuthenticated, check_feature_permission('VER_VENTAS')])
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
            'ordenes_pedido__pedidos_telas__detalles',
            'cliente__observaciones',
            'lineas',
            'cotizaciones'
        ).get(id=id)

        if not ventas_visibles(request).filter(id=venta.id).exists():
            return Response({"error": "No tienes permiso para ver esta venta."}, status=status.HTTP_403_FORBIDDEN)

        serializer = VentaDetalleSerializer(venta, context={'request': request,
            'ver_costos': tiene_permiso_codigo(request, 'VER_COSTOS_ORDEN'),
            'ver_margenes': tiene_permiso_codigo(request, 'VER_MARGENES'),
        })
        return Response(serializer.data)
    except Venta.DoesNotExist:
        return Response({"error": "Venta no encontrada."}, status=404)

@api_view(['POST'])
@permission_classes([IsAuthenticated, check_feature_permission('VER_VENTAS')])
def anadir_observacion_venta(request, id):
    try:
        venta = ventas_visibles(request).get(id=id)
        serializer = ObservacionVentaSerializer(data={'venta': venta.id, 'texto': request.data.get('texto')}, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=201)
    except Venta.DoesNotExist:
        return Response({"error": "Venta no encontrada."}, status=404)

@api_view(['POST'])
@permission_classes([IsAuthenticated, check_feature_permission('VER_VENTAS')])
def anadir_remision_a_venta(request, id):
    try:
        venta = ventas_visibles(request).get(id=id)
        if Remision.objects.filter(codigo=request.data.get('codigo')).exists():
            return Response({"error": "El código de remisión ya existe."}, status=400)
        serializer = RemisionSerializer(data={**request.data, 'venta': venta.id})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=201)
    except Venta.DoesNotExist:
        return Response({"error": "Venta no encontrada."}, status=404)

@api_view(['GET'])
@permission_classes([IsAuthenticated, check_feature_permission('VER_VENTAS')])
def ver_remisiones_de_venta(request, id):
    try:
        venta = ventas_visibles(request).get(id=id)
        remisiones = Remision.objects.filter(venta=venta)
        serializer = RemisionSerializer(remisiones, many=True)
        return Response(serializer.data)
    except Venta.DoesNotExist:
        return Response({"error": "Venta no encontrada."}, status=404)

class ClientePagination(StandardResultsSetPagination):
    pass

@api_view(['GET'])
@permission_classes([IsAuthenticated, check_feature_permission('VER_CLIENTES')])
def listar_clientes(request):
    qs, _ = filtrar_clientes(Cliente.objects.all(), request.query_params)
    paginator = ClientePagination()
    page = paginator.paginate_queryset(qs, request)
    serializer = ClienteSerializer(page, many=True)
    response = paginator.get_paginated_response(serializer.data)
    response.data['exportacion'] = {
        'permitida': tiene_permiso_codigo(request, 'EXPORTAR_CLIENTES'),
        'alcance': 'global' if ve_todas_las_ventas(request) else 'propias_compartidas',
    }
    response['Cache-Control'] = 'no-store'
    return response

@api_view(['GET', 'PUT'])
@permission_classes([IsAuthenticated])
def obtener_cliente(request, id):
    permiso = 'VER_CLIENTES' if request.method == 'GET' else 'EDITAR_CLIENTE'
    if not tiene_permiso_codigo(request, permiso):
        return Response({'error': 'No tienes permiso para esta operación sobre clientes.'}, status=403)
    try:
        cliente = Cliente.objects.get(id=id)
    except Cliente.DoesNotExist:
        return Response({"error": "Cliente no encontrado."}, status=status.HTTP_404_NOT_FOUND)
        
    if request.method == 'GET':
        if not check_feature_permission('VER_CLIENTES')().has_permission(request, None):
            return Response({"error": "No tienes permiso para ver clientes."}, status=status.HTTP_403_FORBIDDEN)
        response = Response(ClienteSerializer(cliente).data)
        response['Cache-Control'] = 'no-store'
        return response
        
    elif request.method == 'PUT':
        if not check_feature_permission('EDITAR_CLIENTE')().has_permission(request, None):
            return Response({"error": "No tienes permiso para editar clientes."}, status=status.HTTP_403_FORBIDDEN)
        serializer = ClienteSerializer(cliente, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

@api_view(['GET'])
@permission_classes([IsAuthenticated, check_feature_permission('VER_CLIENTES')])
def ventas_y_observaciones_cliente(request, id):
    try:
        cliente = Cliente.objects.get(id=id)
        en_alcance = clientes_visibles(request).filter(pk=id).exists()
        ventas = ventas_visibles(request).filter(cliente=cliente).select_related('vendedor', 'cliente').prefetch_related('vendedores_compartidos', 'lineas') if tiene_permiso_codigo(request, 'VER_VENTAS') else Venta.objects.none()
        observaciones = cliente.observaciones.select_related('autor').order_by('-fecha', '-id') if en_alcance else ObservacionCliente.objects.none()
        response = Response({
            "cliente_id": cliente.id, "nombre_cliente": cliente.nombre,
            "ventas": VentaSerializer(ventas, many=True, context={'request': request, 'ver_margenes': tiene_permiso_codigo(request, 'VER_MARGENES')}).data,
            "observaciones_cliente": ObservacionClienteSerializer(observaciones, many=True).data,
            "puede_agregar_observaciones": en_alcance,
            "historial_limitado": not ve_todas_las_ventas(request) or not tiene_permiso_codigo(request, 'VER_VENTAS'),
        })
        response['Cache-Control'] = 'no-store'
        return response
    except Cliente.DoesNotExist:
        return Response({"error": "Cliente no encontrado."}, status=404)

@api_view(['POST'])
@permission_classes([IsAuthenticated, check_feature_permission('VER_CLIENTES')])
def anadir_observacion_cliente(request, id):
    try:
        cliente = clientes_visibles(request).get(id=id)
        serializer = ObservacionClienteSerializer(data={'cliente': cliente.id, 'texto': request.data.get('texto')}, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=201)
    except Cliente.DoesNotExist:
        return Response({"error": "Cliente no encontrado."}, status=404)

class CajaPagination(StandardResultsSetPagination):
    pass

from django.db.models import Q, F, Sum, Case, When, DecimalField

@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated, check_feature_permission('VER_CAJA')])
def caja_view(request):
    if request.method == 'GET':
        # 1. Estadísticas del día LOCAL de negocio [inicio, fin) — antes se
        # tomaba la fecha UTC y se interpretaba en Bogotá (H31).
        start_of_day, end_of_day = business_time.rango_dia_local(business_time.hoy())
        del_dia = Caja.objects.filter(fecha_hora__gte=start_of_day, fecha_hora__lt=end_of_day)
        ingresos_hoy = del_dia.filter(tipo='ingreso').aggregate(total=Sum('valor'))['total'] or 0
        egresos_hoy = del_dia.filter(tipo='egreso').aggregate(total=Sum('valor'))['total'] or 0
        saldo_actual = saldo_caja()
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
            try:
                inicio, _ = business_time.rango_dia_local(datetime.strptime(fecha_inicio, '%Y-%m-%d').date())
            except (ValueError, TypeError):
                return Response({"error": "El parámetro fecha_inicio debe tener formato YYYY-MM-DD."}, status=status.HTTP_400_BAD_REQUEST)
            movimientos = movimientos.filter(fecha_hora__gte=inicio)
        if fecha_fin:
            try:
                _, fin = business_time.rango_dia_local(datetime.strptime(fecha_fin, '%Y-%m-%d').date())
            except (ValueError, TypeError):
                return Response({"error": "El parámetro fecha_fin debe tener formato YYYY-MM-DD."}, status=status.HTTP_400_BAD_REQUEST)
            movimientos = movimientos.filter(fecha_hora__lt=fin)
        if query:
            caja_filter = Q(concepto__icontains=query)
            if str(query).isdigit():
                caja_filter |= Q(id=int(query))
            movimientos = movimientos.filter(caja_filter)
        
        # 3. Totales del conjunto filtrado completo (no solo la página), para
        # que la tabla muestre cifras coherentes con sus filtros (P08-08, U05).
        agregados = movimientos.aggregate(
            ingresos=Sum('valor', filter=Q(tipo='ingreso')),
            egresos=Sum('valor', filter=Q(tipo='egreso')),
        )

        paginator = CajaPagination()
        page = paginator.paginate_queryset(movimientos, request)
        serializer = CajaSerializer(page, many=True)
        paginated_response = paginator.get_paginated_response(serializer.data)

        # 4. Combinar todo en una sola respuesta
        data = {
            'stats': stats,
            'totales_filtrados': {
                'ingresos': agregados['ingresos'] or 0,
                'egresos': agregados['egresos'] or 0,
            },
            'movimientos': paginated_response.data
        }
        return Response(data)

    elif request.method == 'POST':
        return _crear_movimiento_caja(request)


@idempotente('caja.movimiento')
def _crear_movimiento_caja(request):
    """Alta manual de ingreso/egreso. Solo esos dos tipos: el cierre tiene su
    acción con permiso propio y nunca fija el saldo (H02)."""
    tipo = request.data.get('tipo')
    if tipo not in ('ingreso', 'egreso'):
        return Response({'tipo': 'Tipo inválido. Usa ingreso o egreso; el cierre de caja tiene su propia acción.'}, status=400)
    codigo = 'CREAR_INGRESO_CAJA' if tipo == 'ingreso' else 'CREAR_EGRESO_CAJA'
    if not tiene_permiso_codigo(request, codigo):
        return Response({'error': f'No tienes permiso para crear {tipo}s.'}, status=403)
    try:
        with transaction.atomic():
            mov = registrar_movimiento_caja(request.user, tipo, request.data.get('valor'), request.data.get('concepto'))
    except ErrorNegocio as e:
        return e.respuesta()
    return Response(CajaSerializer(mov).data, status=status.HTTP_201_CREATED)

class ReciboCajaPagination(StandardResultsSetPagination):
    pass

@api_view(['GET'])
@permission_classes([IsAuthenticated, check_feature_permission('VER_RECIBOS')])
def listar_recibos_caja(request):
    recibos = consultar_recibos_caja(request)

    # Total del conjunto filtrado completo (P08-08, U05). Con filtro de medio
    # de pago suma solo los pagos de ese medio (el join ya los restringe).
    total_filtrado = recibos.aggregate(total=Sum('pagos__valor'))['total'] or 0
    paginator = ReciboCajaPagination()
    page = paginator.paginate_queryset(recibos, request)
    respuesta = paginator.get_paginated_response(ReciboCajaSerializer(page, many=True).data)
    respuesta.data['totales_filtrados'] = {'valor': total_filtrado}
    return respuesta

class ComprobanteEgresoPagination(StandardResultsSetPagination):
    max_page_size = 500

@api_view(['GET'])
@permission_classes([IsAuthenticated, check_feature_permission('VER_COMPROBANTES_EGRESO')])
def listar_comprobantes_egreso(request):
    egresos = consultar_comprobantes_egreso(request)

    # Total del conjunto filtrado completo (P08-08, U05).
    total_filtrado = egresos.aggregate(total=Sum('valor'))['total'] or 0
    paginator = ComprobanteEgresoPagination()
    page = paginator.paginate_queryset(egresos, request)
    respuesta = paginator.get_paginated_response(ComprobanteEgresoSerializer(page, many=True).data)
    respuesta.data['totales_filtrados'] = {'valor': total_filtrado}
    return respuesta

TOLERANCIA_REDONDEO_EFECTIVO = Decimal('50')


def _otros_conceptos_validos(raw):
    """[{descripcion, valor}] con valores positivos; error de fila si no."""
    if raw in (None, ''):
        return [], Decimal('0')
    if not isinstance(raw, list):
        raise ErrorNegocio('Formato de otros conceptos inválido.', campo='otros_conceptos')
    limpios, total = [], Decimal('0')
    for i, c in enumerate(raw, start=1):
        if not isinstance(c, dict) or not str(c.get('descripcion') or '').strip():
            raise ErrorNegocio(f'El concepto #{i} necesita descripción.', campo='otros_conceptos')
        valor = a_decimal(c.get('valor'), campo=f'otros_conceptos #{i}')
        limpios.append({'descripcion': str(c['descripcion']).strip(), 'valor': int(valor) if valor == valor.to_integral() else str(valor)})
        total += valor
    return limpios, total


def _facturas_para_egreso(proveedor_id, ids, egreso=None):
    """Bloquea (orden estable por id) y valida las facturas a pagar: existen,
    son del proveedor del comprobante y están pendientes (o ya vinculadas a
    este mismo comprobante al editar). H10."""
    from suministros.models import FacturaProveedor
    if not ids:
        return []
    if not proveedor_id:
        raise ErrorNegocio('Un proveedor "Otro" no puede tener facturas asociadas.', campo='facturas_ids')
    facturas = list(FacturaProveedor.objects.select_for_update().filter(id__in=ids).order_by('id'))
    encontradas = {f.id for f in facturas}
    faltantes = sorted(set(ids) - encontradas)
    if faltantes:
        raise ErrorNegocio(f'Facturas inexistentes: {", ".join(map(str, faltantes))}.', campo='facturas_ids')
    for f in facturas:
        if f.proveedor_id != int(proveedor_id):
            raise ErrorNegocio(f'La factura {f.id_manual} no pertenece al proveedor del comprobante.', campo='facturas_ids')
        propia = egreso is not None and f.comprobante_egreso_id == egreso.id
        if not propia and (f.estado != 'pendiente' or f.comprobante_egreso_id):
            raise ErrorNegocio(f'La factura {f.id_manual} ya no está pendiente de pago.', campo='facturas_ids')
    return facturas


def _validar_importe_egreso(valor, facturas, proveedor, otros_total):
    """Regla provisional D02: el importe solo puede diferir del total estructurado
    por el % de descuento del proveedor y el redondeo de efectivo a $50."""
    if not facturas and not otros_total:
        return
    total_facturas = sum((f.valor for f in facturas), Decimal('0'))
    pct = Decimal(str(proveedor.porcentaje_descuento or 0)) if proveedor else Decimal('0')
    minimo = total_facturas * (Decimal('1') - pct / Decimal('100')) + otros_total - TOLERANCIA_REDONDEO_EFECTIVO
    maximo = total_facturas + otros_total + TOLERANCIA_REDONDEO_EFECTIVO
    if not (minimo <= valor <= maximo):
        raise ErrorNegocio(
            f'El valor {formato_cop(valor)} no corresponde a las facturas y conceptos seleccionados '
            f'(esperado entre {formato_cop(max(minimo, 0))} y {formato_cop(maximo)}).', campo='valor'
        )


def _ids_enteros(raw, campo='facturas_ids'):
    if raw in (None, ''):
        return []
    if not isinstance(raw, list):
        raise ErrorNegocio('Formato de facturas inválido.', campo=campo)
    try:
        return sorted({int(x) for x in raw})
    except (TypeError, ValueError):
        raise ErrorNegocio('Formato de facturas inválido.', campo=campo)


@api_view(['POST'])
@permission_classes([IsAuthenticated, check_feature_permission('CREAR_COMPROBANTE_EGRESO')])
@idempotente('egreso.crear')
def crear_comprobante_egreso(request):
    """Crea el comprobante como una sola operación: comprobante, facturas,
    movimiento de caja y bitácora se aplican juntos o nada (H03). Toda la
    validación ocurre antes de escribir y se repite bajo bloqueo."""
    try:
        with transaction.atomic():
            egreso = _crear_egreso(request)
    except ErrorNegocio as e:
        return e.respuesta()
    except ValidationError as e:
        detail = getattr(e, 'detail', str(e))
        return Response(detail if isinstance(detail, dict) else {"detail": str(detail)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(ComprobanteEgresoSerializer(egreso).data, status=201)


def _crear_egreso(request):
    from pagos.servicios import cuenta_ce, snapshot
    data_in = request.data
    recibido_por = (data_in.get('recibido_por') or '').strip()
    if not recibido_por:
        raise ErrorNegocio("El campo 'Quien recibe' es obligatorio.")
    proveedor_id = data_in.get('proveedor') or None
    proveedor_tela_id = data_in.get('proveedor_tela') or None
    if proveedor_id and proveedor_tela_id:
        raise ErrorNegocio('Selecciona un único beneficiario.')
    proveedor_tela = get_object_or_404(ProveedorTela, pk=proveedor_tela_id) if proveedor_tela_id else None
    proveedor_otro_nombre = (data_in.get('proveedor_otro_nombre') or '').strip()
    if not proveedor_id and not proveedor_tela_id and not proveedor_otro_nombre:
        raise ErrorNegocio("Debes seleccionar un proveedor o indicar el nombre en 'Otro'.")
    proveedor = None
    if proveedor_id:
        proveedor = Proveedor.objects.filter(id=proveedor_id).first()
        if proveedor is None:
            raise ErrorNegocio('Proveedor no encontrado.', campo='proveedor')
    medio_pago = data_in.get('medio_pago')
    if medio_pago not in dict(ComprobanteEgreso.MEDIO_PAGO_CHOICES):
        raise ErrorNegocio('Medio de pago inválido.', campo='medio_pago')
    destino = cuenta_ce(data_in.get('cuenta_destino'), proveedor_id, medio_pago, proveedor_tela_id)
    valor = a_decimal(data_in.get('valor'))
    otros, otros_total = _otros_conceptos_validos(data_in.get('otros_conceptos'))
    facturas = _facturas_para_egreso(proveedor_id, _ids_enteros(data_in.get('facturas_ids')))
    _validar_importe_egreso(valor, facturas, proveedor, otros_total)

    is_efectivo = medio_pago == 'Efectivo'
    data = {k: v for k, v in data_in.items() if k not in ('facturas_ids', 'id', 'estado', 'otros_conceptos')}
    data.update({
        'recibido_por': recibido_por, 'valor': str(valor), 'otros_conceptos': otros,
        'proveedor': proveedor.id if proveedor else None, 'proveedor_tela': proveedor_tela_id,
        'proveedor_otro_nombre': '' if proveedor else proveedor_otro_nombre,
        # El efectivo sale de caja en este mismo acto; la transferencia queda
        # por confirmar hasta la aprobación (el PDF siempre imprime "Pagado").
        'estado': 'Pagado' if is_efectivo else 'Por Confirmar Pago',
    })
    if facturas and not (data.get('concepto') or '').strip():
        data['concepto'] = "Pago fact. " + ', '.join(str(f.id_manual) for f in facturas)

    # Consecutivo bajo bloqueo de su serie (antes MAX(id)+1 sin bloqueo real, H15).
    max_id = ComprobanteEgreso.objects.aggregate(Max('id'))['id__max'] or 0
    data['id'] = siguiente_consecutivo('comprobante_egreso', 3001, max_id)

    serializer = ComprobanteEgresoSerializer(data=data)
    serializer.is_valid(raise_exception=True)
    egreso = serializer.save(
        cuenta_destino=destino, cuenta_destino_snapshot=snapshot(destino) if destino else {},
        creado_por=request.user,
        aprobado_por=request.user if is_efectivo else None,
        fecha_aprobacion=timezone.now() if is_efectivo else None,
    )

    from suministros.models import FacturaProveedor
    if facturas:
        ids = [f.id for f in facturas]
        if is_efectivo:
            # fecha_pago es la fecha límite acordada (D10f): no se sobrescribe.
            FacturaProveedor.objects.filter(id__in=ids).update(estado='pagada', fecha_pago_real=business_time.hoy(), comprobante_egreso=egreso)
        else:
            FacturaProveedor.objects.filter(id__in=ids).update(estado='pago_en_proceso', comprobante_egreso=egreso)

    if is_efectivo:
        prov_nombre = recibido_por or (proveedor.nombre_empresa if proveedor else 'Proveedor')
        concepto_caja = f"Pago a {prov_nombre}, CE. {egreso.id}"
        if facturas:
            concepto_caja += ", Fact. " + ', '.join(str(f.id_manual) for f in facturas)
        # Si no hay efectivo suficiente, ErrorNegocio revierte TODO lo anterior.
        registrar_movimiento_caja(request.user, 'egreso', egreso.valor, concepto_caja, comprobante_egreso=egreso)
    auditar(request.user, 'egreso.crear', egreso, {'valor': str(valor), 'medio_pago': medio_pago, 'facturas': [f.id for f in facturas]})
    return egreso


@api_view(['PATCH'])
@permission_classes([IsAuthenticated, check_feature_permission('APROBAR_EGRESO')])
@transaction.atomic
def confirmar_comprobante_egreso(request, id):
    from .servicios import confirmar_pago_egreso
    try:
        egreso = ComprobanteEgreso.objects.select_for_update().get(id=id)
    except ComprobanteEgreso.DoesNotExist:
        return Response({"error": "Comprobante de Egreso no encontrado."}, status=status.HTTP_404_NOT_FOUND)

    if egreso.estado == 'Pagado':
        return Response({"message": "El comprobante ya se encuentra pagado."}, status=status.HTTP_200_OK)

    confirmar_pago_egreso(egreso, request.user)

    return Response({"message": "Transferencia de egreso confirmada exitosamente.", "id": egreso.id, "estado": "Pagado"}, status=status.HTTP_200_OK)


@api_view(['PUT'])
@permission_classes([IsAuthenticated, check_feature_permission('EDITAR_COMPROBANTE_EGRESO')])
def editar_comprobante_egreso(request, id):
    """Edita un comprobante de egreso existente, incluida la reversión de uno ya
    'Pagado'. Caja es un libro de solo-agregar: una reversión en efectivo se
    contabiliza como un ingreso compensatorio que referencia al egreso original.

    Cambiar el estado (confirmar o revertir el pago) exige APROBAR_EGRESO además
    de editar (H07). Toda la entrada se valida antes de escribir y la operación
    completa se revierte ante cualquier rechazo (H03)."""
    try:
        with transaction.atomic():
            egreso = _editar_egreso(request, id)
    except ErrorNegocio as e:
        return e.respuesta()
    except ValidationError as e:
        detail = getattr(e, 'detail', str(e))
        return Response(detail if isinstance(detail, dict) else {"detail": str(detail)}, status=status.HTTP_400_BAD_REQUEST)

    from django.db.models import Prefetch
    from suministros.models import FacturaProveedor, Inventario
    items_qs = Inventario.objects.select_related('referencia', 'categoria', 'subcategoria')
    facturas_qs = FacturaProveedor.objects.prefetch_related(Prefetch('items_inventario', queryset=items_qs))
    fresh = ComprobanteEgreso.objects.select_related('proveedor').prefetch_related(
        Prefetch('facturas', queryset=facturas_qs)
    ).get(id=egreso.id)
    return Response(ComprobanteEgresoSerializer(fresh).data, status=status.HTTP_200_OK)


def _editar_egreso(request, id):
    from pagos.servicios import cuenta_ce, snapshot, proteger_ce
    from suministros.models import FacturaProveedor
    egreso = ComprobanteEgreso.objects.select_for_update().select_related('proveedor').filter(id=id).first()
    if egreso is None:
        raise ErrorNegocio("Comprobante de Egreso no encontrado.", status.HTTP_404_NOT_FOUND)
    proteger_ce(egreso)
    data = request.data

    # --- 1. Validar toda la entrada (sin escribir) ---
    recibido_por = (data.get('recibido_por') or '').strip()
    if not recibido_por:
        raise ErrorNegocio("El campo 'Quien recibe' es obligatorio.")
    proveedor_id = data.get('proveedor') or None
    proveedor_tela_id = data.get('proveedor_tela', egreso.proveedor_tela_id) or None
    if proveedor_id and proveedor_tela_id:
        raise ErrorNegocio('Selecciona un único beneficiario.')
    if proveedor_tela_id:
        get_object_or_404(ProveedorTela, pk=proveedor_tela_id)
    proveedor_otro_nombre = (data.get('proveedor_otro_nombre') or '').strip()
    if not proveedor_id and not proveedor_tela_id and not proveedor_otro_nombre:
        raise ErrorNegocio("Debes seleccionar un proveedor o indicar el nombre en 'Otro'.")
    proveedor = None
    if proveedor_id:
        proveedor = Proveedor.objects.filter(id=proveedor_id).first()
        if proveedor is None:
            raise ErrorNegocio("Proveedor no encontrado.", status.HTTP_404_NOT_FOUND)

    nuevo_estado = data.get('estado') or egreso.estado
    if nuevo_estado not in ('Pagado', 'Por Confirmar Pago'):
        raise ErrorNegocio("Estado inválido.")
    if nuevo_estado != egreso.estado and not tiene_permiso_codigo(request, 'APROBAR_EGRESO'):
        raise ErrorNegocio("Confirmar o revertir el pago requiere el permiso de aprobar egresos.", status.HTTP_403_FORBIDDEN)

    nuevo_medio_pago = data.get('medio_pago') or egreso.medio_pago
    if nuevo_medio_pago not in dict(ComprobanteEgreso.MEDIO_PAGO_CHOICES):
        raise ErrorNegocio("Medio de pago inválido.")
    nuevo_valor = a_decimal(data.get('valor'))
    destino = cuenta_ce(data.get('cuenta_destino', egreso.cuenta_destino_id), proveedor_id, nuevo_medio_pago, proveedor_tela_id)

    nueva_fecha = egreso.fecha
    if data.get('fecha'):
        try:
            nueva_fecha = datetime.strptime(data.get('fecha'), '%Y-%m-%d').date()
        except (ValueError, TypeError):
            raise ErrorNegocio("La fecha debe tener formato YYYY-MM-DD.")

    otros_cambian = 'otros_conceptos' in data
    otros, otros_total = _otros_conceptos_validos(data.get('otros_conceptos')) if otros_cambian else (
        egreso.otros_conceptos, sum((Decimal(str(c.get('valor') or 0)) for c in (egreso.otros_conceptos or []) if isinstance(c, dict)), Decimal('0'))
    )

    facturas_deseadas = set(_ids_enteros(data.get('facturas_ids') if proveedor_id else []))
    facturas_actuales = set(FacturaProveedor.objects.select_for_update().filter(comprobante_egreso=egreso).values_list('id', flat=True))
    a_quitar = facturas_actuales - facturas_deseadas
    a_agregar = facturas_deseadas - facturas_actuales
    a_mantener = facturas_actuales & facturas_deseadas
    facturas_finales = _facturas_para_egreso(proveedor_id, sorted(facturas_deseadas), egreso=egreso)
    # El importe se revalida solo si cambia lo que lo determina (comprobantes
    # antiguos pueden no cumplir la regla provisional y deben seguir editables).
    if a_quitar or a_agregar or nuevo_valor != egreso.valor or otros_cambian or (proveedor and proveedor.id != egreso.proveedor_id):
        _validar_importe_egreso(nuevo_valor, facturas_finales, proveedor, otros_total)

    # --- 2. Escribir ---
    old_estado, old_medio_pago, old_valor = egreso.estado, egreso.medio_pago, egreso.valor
    old_efectivo_pagado = old_estado == 'Pagado' and old_medio_pago == 'Efectivo'
    nuevo_efectivo_pagado = nuevo_estado == 'Pagado' and nuevo_medio_pago == 'Efectivo'

    estado_factura_final = 'pagada' if nuevo_estado == 'Pagado' else 'pago_en_proceso'
    # fecha_pago (fecha límite acordada) nunca se toca; fecha_pago_real cambia
    # solo cuando cambia el estado de pago de la factura (D10f).
    fecha_pago_final = business_time.hoy() if nuevo_estado == 'Pagado' else None
    if a_quitar:
        FacturaProveedor.objects.filter(id__in=a_quitar).update(estado='pendiente', comprobante_egreso=None, fecha_pago_real=None)
    if a_agregar:
        FacturaProveedor.objects.filter(id__in=a_agregar).update(estado=estado_factura_final, comprobante_egreso=egreso, fecha_pago_real=fecha_pago_final)
    if a_mantener:
        FacturaProveedor.objects.filter(id__in=a_mantener).exclude(estado=estado_factura_final).update(
            estado=estado_factura_final, fecha_pago_real=fecha_pago_final)

    egreso.fecha = nueva_fecha
    egreso.proveedor_tela_id = proveedor_tela_id
    egreso.proveedor = proveedor
    egreso.proveedor_otro_nombre = '' if proveedor else proveedor_otro_nombre
    egreso.recibido_por = recibido_por
    egreso.medio_pago = nuevo_medio_pago
    egreso.cuenta_destino = destino
    egreso.cuenta_destino_snapshot = snapshot(destino) if destino else {}
    egreso.valor = nuevo_valor
    egreso.concepto = (data.get('concepto') or '').strip() or egreso.concepto
    egreso.descripcion = data.get('descripcion', egreso.descripcion)
    if otros_cambian:
        egreso.otros_conceptos = otros
    if nuevo_estado != old_estado:
        egreso.aprobado_por = request.user if nuevo_estado == 'Pagado' else None
        egreso.fecha_aprobacion = timezone.now() if nuevo_estado == 'Pagado' else None
    egreso.estado = nuevo_estado
    egreso.save()

    # --- 3. Caja (solo efectivo), siempre por el servicio ---
    prov_nombre = recibido_por or (proveedor.nombre_empresa if proveedor else (proveedor_otro_nombre or 'Proveedor'))

    def _ultimo_egreso_vigente():
        return egreso.movimientos_caja.filter(tipo='egreso', reversa_de__isnull=True).exclude(reversiones__isnull=False).order_by('-id').first()

    def _revertir(motivo):
        original = _ultimo_egreso_vigente()
        registrar_movimiento_caja(request.user, 'ingreso', old_valor, f"{motivo}, CE. {egreso.id} ({prov_nombre})",
                                  comprobante_egreso=egreso, reversa_de=original)

    def _pagar():
        registrar_movimiento_caja(request.user, 'egreso', nuevo_valor, f"Pago a proveedor (edición), CE. {egreso.id} ({prov_nombre})",
                                  comprobante_egreso=egreso)

    if old_efectivo_pagado and not nuevo_efectivo_pagado:
        _revertir('Reversión de pago')
    elif not old_efectivo_pagado and nuevo_efectivo_pagado:
        _pagar()
    elif old_efectivo_pagado and nuevo_efectivo_pagado and old_valor != nuevo_valor:
        _revertir('Reversión de pago (ajuste por edición)')
        _pagar()

    auditar(request.user, 'egreso.editar', egreso, {
        'antes': {'estado': old_estado, 'medio_pago': old_medio_pago, 'valor': str(old_valor)},
        'despues': {'estado': nuevo_estado, 'medio_pago': nuevo_medio_pago, 'valor': str(nuevo_valor)},
        'facturas_agregadas': sorted(a_agregar), 'facturas_quitadas': sorted(a_quitar),
    })
    return egreso


@api_view(['POST'])
@permission_classes([IsAuthenticated, check_feature_permission('CREAR_RECIBO')])
@idempotente('recibo.crear')
@transaction.atomic
def crear_recibo_caja(request):
    data = request.data
    pagos_data = data.get('pagos')
    if not isinstance(pagos_data, list) or len(pagos_data) == 0:
        return Response({"error": "Debe incluir al menos un pago (método y valor)."}, status=status.HTTP_400_BAD_REQUEST)

    recibo_id = data.get('id')
    venta_id = data.get('venta')
    if not recibo_id or not venta_id:
        return Response({"error": "Faltan datos del recibo (No. de recibo / venta)."}, status=status.HTTP_400_BAD_REQUEST)

    if ReciboCaja.objects.filter(id=recibo_id).exists():
        return Response({"error": "Ya existe un recibo con ese número."}, status=status.HTTP_400_BAD_REQUEST)

    venta = ventas_visibles(request, Venta.objects.select_for_update()).filter(id=venta_id).first()
    if venta is None:
        return Response({"error": "Venta no encontrada."}, status=status.HTTP_404_NOT_FOUND)

    medios_validos = {c[0] for c in PagoReciboCaja.MEDIO_PAGO_CHOICES}
    pagos_parseados = []
    for pago in pagos_data:
        metodo = pago.get('metodo_pago')
        if metodo not in medios_validos:
            return Response({"error": f"Método de pago inválido: {metodo}"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            valor = Decimal(str(pago.get('valor', 0)))
        except (InvalidOperation, TypeError):
            valor = Decimal('0')
        if valor <= 0:
            return Response({"error": "Cada pago debe tener un valor mayor a cero."}, status=status.HTTP_400_BAD_REQUEST)
        pagos_parseados.append((metodo, valor))

    # Use provided date or default to today
    fecha_str_input = data.get('fecha')
    if fecha_str_input:
        try:
            fecha_creacion = datetime.strptime(fecha_str_input, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            return Response({"error": "La fecha debe tener formato YYYY-MM-DD."}, status=status.HTTP_400_BAD_REQUEST)
    else:
        fecha_creacion = business_time.hoy()

    usuario_nombre = request.user.first_name or request.user.username
    # Format date as "20-nov-2025"
    fecha_str = fecha_creacion.strftime('%d-%b-%Y').lower()

    recibo = ReciboCaja.objects.create(
        id=recibo_id, venta=venta, fecha=fecha_creacion, nota=data.get('nota') or None
    )

    for metodo, valor in pagos_parseados:
        pago = PagoReciboCaja.objects.create(recibo=recibo, metodo_pago=metodo, valor=valor, estado='Pendiente')
        if metodo == 'Efectivo':
            # El efectivo se confirma al recibirlo, con su movimiento de caja (función única).
            _aplicar_confirmacion_pago(request, pago, fecha_str, usuario_nombre)

    return Response(ReciboCajaSerializer(recibo).data, status=status.HTTP_201_CREATED)


@api_view(['PUT'])
@permission_classes([IsAuthenticated, check_feature_permission('EDITAR_RECIBO')])
@transaction.atomic
def editar_recibo_caja(request, recibo_id):
    """Edita un recibo existente. Por diseño, los pagos ya 'Confirmado' (que ya
    sumaron a Caja y al abono/saldo de la venta) nunca se tocan aquí — Caja es un
    libro de solo-agregar sin operación de edición/reversión en todo el sistema.
    Solo se pueden editar/quitar líneas 'Pendiente' y agregar líneas nuevas
    (una línea nueva en Efectivo se confirma al instante, igual que al crear)."""
    try:
        recibo = ReciboCaja.objects.select_for_update().select_related('venta').get(id=recibo_id)
    except ReciboCaja.DoesNotExist:
        return Response({"error": "Recibo no encontrado."}, status=status.HTTP_404_NOT_FOUND)

    pagos_existentes = list(recibo.pagos.select_for_update().order_by('id'))
    if pagos_existentes and all(p.estado == 'Anulado' for p in pagos_existentes):
        return Response({"error": "Este recibo está anulado y no se puede editar."}, status=status.HTTP_400_BAD_REQUEST)

    data = request.data
    pagos_pendientes_data = data.get('pagos_pendientes')
    if not isinstance(pagos_pendientes_data, list):
        return Response({"error": "Formato de pagos inválido."}, status=status.HTTP_400_BAD_REQUEST)

    pagos_confirmados = [p for p in pagos_existentes if p.estado == 'Confirmado']
    pagos_pendientes_actuales = {p.id: p for p in pagos_existentes if p.estado == 'Pendiente'}

    # Venta: solo se puede cambiar si el recibo todavía no tiene pagos confirmados
    # (evita dejar contabilidad ya aplicada colgando de la venta equivocada).
    venta_id = data.get('venta')
    if venta_id is not None:
        try:
            venta_id_int = int(venta_id)
        except (TypeError, ValueError):
            return Response({"error": "Venta inválida."}, status=status.HTTP_400_BAD_REQUEST)
        if venta_id_int != recibo.venta_id:
            if pagos_confirmados:
                return Response({"error": "No se puede cambiar la venta de un recibo con pagos ya confirmados."}, status=status.HTTP_400_BAD_REQUEST)
            try:
                recibo.venta = Venta.objects.get(id=venta_id_int)
            except Venta.DoesNotExist:
                return Response({"error": "Venta no encontrada."}, status=status.HTTP_404_NOT_FOUND)

    fecha_str_input = data.get('fecha')
    if fecha_str_input:
        try:
            recibo.fecha = datetime.strptime(fecha_str_input, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            return Response({"error": "La fecha debe tener formato YYYY-MM-DD."}, status=status.HTTP_400_BAD_REQUEST)

    recibo.nota = data.get('nota') or None

    medios_validos = {c[0] for c in PagoReciboCaja.MEDIO_PAGO_CHOICES}
    ids_enviados = set()
    lineas_parseadas = []  # (pago_existente_o_None, metodo, valor)
    for pago in pagos_pendientes_data:
        metodo = pago.get('metodo_pago')
        if metodo not in medios_validos:
            return Response({"error": f"Método de pago inválido: {metodo}"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            valor = Decimal(str(pago.get('valor', 0)))
        except (InvalidOperation, TypeError):
            valor = Decimal('0')
        if valor <= 0:
            return Response({"error": "Cada pago debe tener un valor mayor a cero."}, status=status.HTTP_400_BAD_REQUEST)

        pago_id = pago.get('id')
        pago_existente = None
        if pago_id is not None:
            try:
                pago_existente = pagos_pendientes_actuales[int(pago_id)]
            except (KeyError, TypeError, ValueError):
                return Response({"error": "Uno de los pagos a editar ya no existe o ya fue confirmado."}, status=status.HTTP_400_BAD_REQUEST)
            ids_enviados.add(pago_existente.id)
        lineas_parseadas.append((pago_existente, metodo, valor))

    if not pagos_confirmados and not lineas_parseadas:
        return Response({"error": "El recibo debe tener al menos un pago."}, status=status.HTTP_400_BAD_REQUEST)

    # Toda la entrada ya está validada: recién ahora se escribe (H03).
    recibo.save(update_fields=['venta', 'fecha', 'nota'])

    # Las líneas pendientes existentes que ya no vienen en la lista se eliminan
    # (nunca tuvieron efecto en Caja/venta, así que borrarlas es seguro).
    for pago_id, pago in pagos_pendientes_actuales.items():
        if pago_id not in ids_enviados:
            pago.delete()

    usuario_nombre = request.user.first_name or request.user.username
    fecha_str = recibo.fecha.strftime('%d-%b-%Y').lower()

    for pago_existente, metodo, valor in lineas_parseadas:
        if pago_existente is not None:
            # Una línea pendiente sigue pendiente aunque cambie a Efectivo: al
            # confirmarla, la función única aplica abono + ingreso de caja (H09).
            pago_existente.metodo_pago = metodo
            pago_existente.valor = valor
            pago_existente.save(update_fields=['metodo_pago', 'valor'])
        else:
            pago = PagoReciboCaja.objects.create(recibo=recibo, metodo_pago=metodo, valor=valor, estado='Pendiente')
            if metodo == 'Efectivo':
                _aplicar_confirmacion_pago(request, pago, fecha_str, usuario_nombre)

    # Recargar sin la caché de prefetch original: las líneas borradas/creadas
    # arriba dejarían datos obsoletos (p. ej. un pago borrado queda con pk=None
    # en el objeto ya cacheado) si se serializara el `recibo` tal cual.
    recibo_actualizado = ReciboCaja.objects.select_related('venta').prefetch_related('pagos').get(id=recibo.id)
    return Response(ReciboCajaSerializer(recibo_actualizado).data, status=status.HTTP_200_OK)


@api_view(['PUT'])
@permission_classes([IsAuthenticated, check_feature_permission('EDITAR_RECIBO')])
@transaction.atomic
def anular_recibo_caja(request, recibo_id):
    """Anula un recibo completo (nunca se borra). Revierte lo que las líneas
    'Confirmado' ya hayan aplicado — abono/saldo de la venta siempre, y un
    movimiento compensatorio de Caja ('egreso') que referencia al ingreso
    original solo para las líneas en Efectivo. Si la caja no tiene efectivo
    suficiente para la reversión, la anulación completa se rechaza sin cambios.
    Todas las líneas quedan 'Anulado' para que no puedan volver a contarse."""
    recibo = ReciboCaja.objects.select_for_update().select_related('venta').filter(id=recibo_id).first()
    if recibo is None:
        return Response({"error": "Recibo no encontrado."}, status=status.HTTP_404_NOT_FOUND)

    pagos = list(recibo.pagos.select_for_update().order_by('id'))
    if not pagos:
        return Response({"error": "Este recibo no tiene pagos registrados."}, status=status.HTTP_400_BAD_REQUEST)
    if all(p.estado == 'Anulado' for p in pagos):
        return Response({"error": "Este recibo ya está anulado."}, status=status.HTTP_400_BAD_REQUEST)

    usuario_nombre = request.user.first_name or request.user.username
    fecha_str = business_time.hoy().strftime('%d-%b-%Y').lower()
    anulacion_text = f"Anulado el {fecha_str} por {usuario_nombre}"

    for pago in pagos:
        if pago.estado == 'Confirmado':
            Venta.objects.filter(pk=recibo.venta_id).update(abono=F('abono') - pago.valor, saldo=F('saldo') + pago.valor)
            if pago.metodo_pago == 'Efectivo':
                original = pago.movimientos_caja.filter(tipo='ingreso', reversa_de__isnull=True).first()
                registrar_movimiento_caja(
                    request.user, 'egreso', pago.valor, f"Reversión RC. {recibo.id} (anulado)",
                    pago_recibo=pago, reversa_de=original,
                )

        pago.estado = 'Anulado'
        pago.confirmacion = f"{pago.confirmacion} | {anulacion_text}" if pago.confirmacion else anulacion_text
        pago.save(update_fields=['estado', 'confirmacion'])

    auditar(request.user, 'recibo.anular', recibo, {'pagos': [p.id for p in pagos]})
    recibo_actualizado = ReciboCaja.objects.select_related('venta').prefetch_related('pagos').get(id=recibo.id)
    return Response(ReciboCajaSerializer(recibo_actualizado).data, status=status.HTTP_200_OK)


def _aplicar_confirmacion_pago(request, pago, fecha_str, nombre):
    """Función única de confirmación (P03-04, H09): transición condicional
    Pendiente→Confirmado, un solo abono a la venta y, si el medio vigente es
    Efectivo, exactamente un ingreso de caja vinculado al pago. Devuelve False
    si otra petición ya lo confirmó (no repite efectos)."""
    cambiadas = PagoReciboCaja.objects.filter(pk=pago.pk, estado='Pendiente').update(
        estado='Confirmado', confirmacion=f"Confirmado el {fecha_str} por {nombre}",
        confirmado_por=request.user, fecha_confirmacion=timezone.now(),
    )
    if not cambiadas:
        return False
    pago.refresh_from_db()
    recibo = pago.recibo
    Venta.objects.filter(pk=recibo.venta_id).update(abono=F('abono') + pago.valor, saldo=F('saldo') - pago.valor)
    if pago.metodo_pago == 'Efectivo':
        registrar_movimiento_caja(request.user, 'ingreso', pago.valor, f"OC. {recibo.venta_id}, RC. {recibo.id}", pago_recibo=pago)
    return True


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
        queryset = PedidoTela.objects.select_related(
            'proveedor', 'usuario', 'orden_asociada', 'orden_asociada__proveedor',
            'orden_asociada__venta', 'orden_asociada__venta__vendedor', 'venta__vendedor'
        ).prefetch_related('detalles', 'orden_asociada__venta__vendedores_compartidos', 'venta__vendedores_compartidos').all().order_by('-id')

        from .permissions import check_feature_permission
        if check_feature_permission('VER_TODOS_PEDIDOS_TELAS')().has_permission(self.request, None):
            pass # Keep all
        elif check_feature_permission('VER_PROPIOS_PEDIDOS_TELAS')().has_permission(self.request, None) or self.request.user.role == 'vendedor':
            user = self.request.user
            queryset = queryset.filter(
                Q(usuario=user) |
                Q(orden_asociada__usuario=user) |
                Q(orden_asociada__venta__vendedor=user) |
                Q(orden_asociada__venta__vendedores_compartidos=user) |
                Q(venta__vendedor=user) | Q(venta__vendedores_compartidos=user)
            ).distinct()
        else:
            queryset = queryset.none()

        # Búsqueda de texto libre: intencionalmente ignora los filtros de
        # Proveedor/Estado de los popovers (que el usuario no relaciona con la
        # caja de búsqueda) para que buscar por cualquiera de las columnas de
        # la tabla (Proveedor, Fabricante, Usuario, Vendedor, ID, Orden
        # Asociada, Venta) siempre encuentre todo lo que exista, sin importar
        # qué haya quedado marcado/desmarcado en esos filtros.
        search = (self.request.query_params.get('search') or '').strip()
        if search:
            search_q = (
                Q(proveedor__nombre_empresa__icontains=search) |          # Proveedor (de la tela)
                Q(usuario__first_name__icontains=search) |                # Usuario (quien creó el pedido)
                Q(orden_asociada__proveedor__nombre_empresa__icontains=search) |  # Fabricante (proveedor de la OP)
                Q(orden_asociada__venta__vendedor__first_name__icontains=search) |  # Vendedor
                Q(orden_asociada__venta__vendedores_compartidos__first_name__icontains=search)  # Vendedor compartido
            )
            if search.isdigit():
                search_q |= (
                    Q(id=int(search)) |                          # ID del pedido de tela (PT)
                    Q(orden_asociada_id=int(search)) |            # Orden Asociada
                    Q(orden_asociada__venta_id=int(search)) |     # Venta
                    Q(venta_id=int(search))
                )
            # .distinct() evita filas duplicadas por el JOIN a través del M2M
            # vendedores_compartidos cuando el pedido matchea por esa vía.
            return queryset.filter(search_q).distinct()

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

        if instance.estado == PedidoTela.ANULADO:
            return Response({'error': 'Este pedido de tela está anulado; su estado ya no cambia.'}, status=status.HTTP_400_BAD_REQUEST)
        # Only allow the 'estado' field to be updated via PATCH
        new_estado = request.data.get('estado', instance.estado)
        if new_estado == PedidoTela.ANULADO:
            return self._anular(request, instance)
        serializer = self.get_serializer(instance, data={'estado': new_estado}, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)

    def _anular(self, request, instance):
        """Anula sin borrar (permiso ANULAR_PEDIDO_TELA): queda el motivo, quién y cuándo, y la
        tela de sus productos vuelve a quedar por pedir."""
        from .productos_venta import liberar_tela_anulada
        if not tiene_permiso_codigo(request, 'ANULAR_PEDIDO_TELA'):
            return Response({'error': 'No tienes permiso para anular pedidos de tela.'}, status=status.HTTP_403_FORBIDDEN)
        motivo = str(request.data.get('motivo_anulacion') or '').strip()
        if not motivo:
            return Response({'error': 'Escribe el motivo de la anulación.'}, status=status.HTTP_400_BAD_REQUEST)
        with transaction.atomic():
            pedido = PedidoTela.objects.select_for_update().get(pk=instance.pk)
            if pedido.estado == PedidoTela.ANULADO:
                return Response({'error': 'Este pedido de tela ya está anulado.'}, status=status.HTTP_400_BAD_REQUEST)
            anterior = pedido.estado
            pedido.estado, pedido.motivo_anulacion = PedidoTela.ANULADO, motivo[:1000]
            pedido.anulado_por, pedido.anulado_en = request.user, timezone.now()
            pedido.save(update_fields=['estado', 'motivo_anulacion', 'anulado_por', 'anulado_en'])
            liberar_tela_anulada(pedido)
            auditar(request.user, 'pedido_tela.anulado', pedido, {'estado_anterior': anterior, 'motivo': pedido.motivo_anulacion})
        return Response(self.get_serializer(self.get_queryset().get(pk=pedido.pk)).data)

class DetallePedidoTelaViewSet(viewsets.ModelViewSet):
    queryset = DetallePedidoTela.objects.all()
    serializer_class = DetallePedidoTelaSerializer

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), check_feature_permission('EDITAR_ESTADO_TELA_ORDEN')()]
        return [IsAuthenticated(), check_feature_permission('VER_PEDIDOS_TELAS')()]


@api_view(['PATCH'])
@permission_classes([IsAuthenticated, check_feature_permission('APROBAR_RECIBO')])
@transaction.atomic
def confirmar_pago_recibo(request, pago_id):
    """Confirma una línea de pago específica de un recibo (un recibo puede tener
    varias, una por medio de pago). La fila se bloquea y la transición es
    condicional: confirmar dos veces o en paralelo abona una sola vez (H15)."""
    pago = PagoReciboCaja.objects.select_for_update().select_related('recibo__venta').filter(id=pago_id).first()
    if pago is None:
        return Response({"error": "Pago no encontrado."}, status=status.HTTP_404_NOT_FOUND)

    if pago.estado == 'Confirmado':
        return Response({"message": "El pago ya está confirmado."}, status=status.HTTP_200_OK)
    if pago.estado == 'Anulado':
        return Response({"error": "Este pago pertenece a un recibo anulado y no se puede confirmar."}, status=status.HTTP_400_BAD_REQUEST)

    fecha_str = business_time.hoy().strftime('%d-%b-%Y').lower()
    admin_nombre = request.user.first_name or request.user.username
    _aplicar_confirmacion_pago(request, pago, fecha_str, admin_nombre)

    recibo = ReciboCaja.objects.select_related('venta').prefetch_related('pagos').get(pk=pago.recibo_id)
    return Response(
        {"message": "Pago confirmado y venta actualizada.", "recibo": ReciboCajaSerializer(recibo).data},
        status=status.HTTP_200_OK
    )



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
    
    can_see_all = any(tiene_permiso_codigo(request, c) for c in ('CREAR_ORDENES_OTROS', 'VER_TODAS_VENTAS', 'VER_TODAS_ORDENES'))

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

@api_view(['PUT', 'DELETE'])
@permission_classes([IsAuthenticated])
def editar_eliminar_observacion_venta(request, obs_id):
    try:
        observacion = ObservacionVenta.objects.select_related('venta').get(id=obs_id)
    except ObservacionVenta.DoesNotExist:
        return Response({'error': 'Observación no encontrada.'}, status=404)

    user = request.user
    venta = observacion.venta
    es_autor = observacion.autor_id == user.id

    if user.role == 'vendedor':
        # EDITAR_VENTA es un permiso de ROL compartido por todos los vendedores (no por venta
        # individual), así que aquí NO debe usarse como bypass: solo el autor de la nota o el
        # vendedor dueño (propio o compartido) de esa venta puntual puede editarla/borrarla.
        es_vendedor_dueno = venta.vendedor_id == user.id or venta.vendedores_compartidos.filter(id=user.id).exists()
        autorizado = es_autor or es_vendedor_dueno
    else:
        tiene_permiso_edicion = check_feature_permission('EDITAR_VENTA')().has_permission(request, None)
        autorizado = es_autor or tiene_permiso_edicion

    if not autorizado:
        return Response({'error': 'No tienes permiso para modificar esta observación.'}, status=403)

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
@permission_classes([IsAuthenticated, check_feature_permission('VER_CLIENTES')])
def editar_eliminar_observacion_cliente(request, obs_id):
    try:
        observacion = ObservacionCliente.objects.filter(cliente__in=clientes_visibles(request)).get(id=obs_id)
    except ObservacionCliente.DoesNotExist:
        return Response({'error': 'Observación no encontrada.'}, status=404)

    user = request.user
    es_autor = observacion.autor_id == user.id
    tiene_permiso_edicion = check_feature_permission('EDITAR_CLIENTE')().has_permission(request, None)

    if not (es_autor or tiene_permiso_edicion):
        return Response({'error': 'No tienes permiso para modificar esta observación.'}, status=403)

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
