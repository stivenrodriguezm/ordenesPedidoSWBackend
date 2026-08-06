from django.db.models import Q
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from .models import (
    Categoria, Subcategoria, Inventario,
    FacturaProveedor, DetalleFactura, RemisionSuministro,
    GrupoInventario, Sede, Zona, HistorialTraslado, CostoAdicionalInventario, ItemInventarioTelaCuero
)
from .serializers import (
    CategoriaSerializer, SubcategoriaSerializer,
    InventarioSerializer, FacturaProveedorSerializer, FacturaProveedorListSerializer,
    DetalleFacturaSerializer, RemisionSuministroSerializer, GrupoInventarioSerializer,
    SedeSerializer, ZonaSerializer, HistorialTrasladoSerializer,
    CostoAdicionalInventarioSerializer, ItemInventarioTelaCueroSerializer
)
from rest_framework.permissions import IsAuthenticated, BasePermission
from ordenes.permissions import check_feature_permission

class CategoriaViewSet(viewsets.ModelViewSet):
    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), check_feature_permission('ADMINISTRAR_BASES')()]
        return [IsAuthenticated()]
    queryset = Categoria.objects.all()
    serializer_class = CategoriaSerializer

class SubcategoriaViewSet(viewsets.ModelViewSet):
    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), check_feature_permission('ADMINISTRAR_BASES')()]
        return [IsAuthenticated()]
    queryset = Subcategoria.objects.all()
    serializer_class = SubcategoriaSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ['categoria']
    search_fields = ['nombre']

class SedeViewSet(viewsets.ModelViewSet):
    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), check_feature_permission('ADMINISTRAR_BASES')()]
        return [IsAuthenticated()]
    queryset = Sede.objects.all()
    serializer_class = SedeSerializer

    def destroy(self, request, *args, **kwargs):
        sede = self.get_object()
        if sede.zonas.exists():
            return Response(
                {'error': 'No se puede eliminar una sede que tiene zonas asociadas. Elimina o reasigna las zonas primero.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        return super().destroy(request, *args, **kwargs)

class ZonaViewSet(viewsets.ModelViewSet):
    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), check_feature_permission('ADMINISTRAR_BASES')()]
        return [IsAuthenticated()]
    queryset = Zona.objects.select_related('sede').all()
    serializer_class = ZonaSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['sede']

    def destroy(self, request, *args, **kwargs):
        zona = self.get_object()
        if zona.items_inventario.exists():
            return Response(
                {'error': 'No se puede eliminar una zona que tiene inventario asignado. Traslada el inventario a otra zona primero.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        return super().destroy(request, *args, **kwargs)

class HistorialTrasladoViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = HistorialTraslado.objects.select_related('item_inventario', 'zona_origen', 'zona_destino', 'usuario').all().order_by('-fecha')
    serializer_class = HistorialTrasladoSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['item_inventario', 'zona_origen', 'zona_destino', 'usuario']

class InventarioViewSet(viewsets.ModelViewSet):
    def get_permissions(self):
        if self.action in ['create']:
            return [IsAuthenticated(), check_feature_permission('CREAR_ITEM_INVENTARIO')()]
        elif self.action in ['update', 'partial_update', 'destroy', 'trasladar']:
            return [IsAuthenticated(), check_feature_permission('EDITAR_ITEM_INVENTARIO')()]
        return [IsAuthenticated(), check_feature_permission('VER_INVENTARIO')()]
    queryset = Inventario.objects.select_related(
        'referencia',
        'referencia__proveedor',
        'categoria',
        'subcategoria',
        'factura',
        'factura__proveedor',
        'detalle_factura',
        'detalle_factura__referencia',
        'detalle_factura__referencia__proveedor',
        'detalle_factura__categoria',
        'detalle_factura__subcategoria',
        'detalle_factura__factura',
        'detalle_factura__factura__proveedor',
        'venta',
        'grupo',
        'zona',
        'zona__sede',
    ).prefetch_related(
        'costos_adicionales',
        'telas_cueros',
        'venta__vendedores_compartidos',
    )
    serializer_class = InventarioSerializer

    def get_queryset(self):
        try:
            return self.queryset.all()
        except Exception:
            return Inventario.objects.all()
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['disponibilidad', 'categoria', 'subcategoria', 'referencia__proveedor']
    search_fields = ['id_referencia', 'referencia__nombre', 'variacion', 'factura_manual']
    ordering_fields = ['fecha_ingreso', 'id_referencia']

    @action(detail=False, methods=['get'], url_path='por-qr')
    def por_qr(self, request):
        qr_uuid = request.query_params.get('qr')
        if not qr_uuid:
            return Response({'error': 'Parámetro qr es requerido'}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            item = self.get_queryset().get(qr_uuid=qr_uuid)
            serializer = self.get_serializer(item)
            return Response(serializer.data)
        except Inventario.DoesNotExist:
            return Response({'error': 'Ítem no encontrado'}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=True, methods=['post'])
    def trasladar(self, request, pk=None):
        item = self.get_object()
        zona_destino_id = request.data.get('zona_destino')
        observacion = request.data.get('observacion', '')

        if not zona_destino_id:
            return Response({'error': 'zona_destino es requerido'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            zona_destino = Zona.objects.get(id=zona_destino_id)
        except Zona.DoesNotExist:
            return Response({'error': 'Zona de destino no existe'}, status=status.HTTP_400_BAD_REQUEST)

        zona_origen = item.zona

        # Actualizar la zona del inventario
        item.zona = zona_destino
        item.save()

        # Registrar historial
        HistorialTraslado.objects.create(
            item_inventario=item,
            zona_origen=zona_origen,
            zona_destino=zona_destino,
            usuario=request.user,
            observacion=observacion
        )

        return Response({'status': 'Traslado exitoso', 'nueva_zona': zona_destino.nombre})


class CostoAdicionalInventarioViewSet(viewsets.ModelViewSet):
    """CRUD de costos adicionales por ítem de inventario."""
    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), check_feature_permission('EDITAR_ITEM_INVENTARIO')()]
        return [IsAuthenticated(), check_feature_permission('VER_COSTOS_INVENTARIO')()]
    serializer_class = CostoAdicionalInventarioSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['inventario']

    def get_queryset(self):
        return CostoAdicionalInventario.objects.all()


class ItemInventarioTelaCueroViewSet(viewsets.ModelViewSet):
    """CRUD de telas y cueros asociadas a ítems de inventario."""
    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), check_feature_permission('EDITAR_ITEM_INVENTARIO')()]
        return [IsAuthenticated(), check_feature_permission('VER_COSTOS_INVENTARIO')()]
    serializer_class = ItemInventarioTelaCueroSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['inventario', 'tipo']

    def get_queryset(self):
        return ItemInventarioTelaCuero.objects.all()

class FacturaProveedorViewSet(viewsets.ModelViewSet):
    def get_permissions(self):
        if self.action in ['create']:
            return [IsAuthenticated(), check_feature_permission('CREAR_FACTURA')()]
        elif self.action in ['update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), check_feature_permission('EDITAR_FACTURA')()]
        return [IsAuthenticated(), check_feature_permission('VER_FACTURAS')()]
    
    queryset = FacturaProveedor.objects.all()

    def get_queryset(self):
        qs = FacturaProveedor.objects.select_related('proveedor')
        full = self.request.query_params.get('full')
        if self.action != 'list' or full == 'true':
            qs = qs.prefetch_related(
                'items_inventario',
                'items_inventario__referencia',
                'items_inventario__referencia__proveedor',
                'items_inventario__categoria',
                'items_inventario__subcategoria',
                'items_inventario__venta',
                'items_inventario__venta__vendedor',
                'items_inventario__venta__vendedores_compartidos',
            )
        return qs.all()
        
    def get_serializer_class(self):
        full = self.request.query_params.get('full')
        if self.action == 'list' and full != 'true':
            return FacturaProveedorListSerializer
        return FacturaProveedorSerializer
        
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['estado', 'proveedor']
    search_fields = ['id_manual', 'proveedor__nombre_empresa']
    ordering_fields = ['fecha_factura', 'fecha_pago']
    ordering = ['-fecha_factura', '-id']

class DetalleFacturaViewSet(viewsets.ModelViewSet):
    def get_permissions(self):
        if self.action in ['create']:
            return [IsAuthenticated(), check_feature_permission('CREAR_FACTURA')()]
        elif self.action in ['update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), check_feature_permission('EDITAR_FACTURA')()]
        return [IsAuthenticated(), check_feature_permission('VER_FACTURAS')()]

    queryset = DetalleFactura.objects.all()
    serializer_class = DetalleFacturaSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['factura']

class RemisionSuministroViewSet(viewsets.ModelViewSet):
    def get_permissions(self):
        # El transportador siempre puede ver las remisiones que se le asignaron (en cualquier
        # estado) y actualizarlas — la única acción que le permite partial_update() es marcar
        # "finalizada". No depende de que un administrador le configure VER_REMISIONES/CREAR_REMISION
        # manualmente en Gestión de Usuarios.
        if self.action in ['create', 'destroy']:
            return [IsAuthenticated(), check_feature_permission('CREAR_REMISION')()]

        if self.action in ['update', 'partial_update']:
            class RemisionEditPermission(BasePermission):
                def has_permission(self, request, view):
                    if not request.user or not request.user.is_authenticated:
                        return False
                    if request.user.role == 'transportador':
                        return True
                    return check_feature_permission('CREAR_REMISION')().has_permission(request, view)
            return [IsAuthenticated(), RemisionEditPermission()]

        class RemisionViewPermission(BasePermission):
            def has_permission(self, request, view):
                if not request.user or not request.user.is_authenticated:
                    return False
                if request.user.role == 'transportador':
                    return True
                return check_feature_permission('VER_REMISIONES')().has_permission(request, view)
        return [IsAuthenticated(), RemisionViewPermission()]

    serializer_class = RemisionSuministroSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['estado', 'vendedor']
    search_fields = ['id', 'direccion_entrega', 'ciudad']
    ordering_fields = ['fecha_creacion', 'fecha_entrega']
    ordering = ['-fecha_creacion', '-id']

    def _base_queryset(self):
        return RemisionSuministro.objects.select_related(
            'orden_asociada',
            'orden_asociada__cliente',
            'transportador_usuario',
            'vendedor',
        ).prefetch_related(
            'inventario_items',
            'inventario_items__referencia',
            'inventario_items__referencia__proveedor',
            'inventario_items__categoria',
            'inventario_items__subcategoria',
            'inventario_items__grupo',
        ).order_by('-fecha_creacion', '-id')

    # Class-level queryset is needed for DRF router registration
    queryset = RemisionSuministro.objects.select_related(
        'orden_asociada',
        'orden_asociada__cliente',
        'transportador_usuario',
        'vendedor',
    ).prefetch_related(
        'inventario_items',
        'inventario_items__referencia',
        'inventario_items__referencia__proveedor',
        'inventario_items__categoria',
        'inventario_items__subcategoria',
        'inventario_items__grupo',
    ).order_by('-fecha_creacion', '-id')

    def get_queryset(self):
        user = self.request.user
        queryset = self._base_queryset()
        if hasattr(user, 'role') and user.role == 'transportador':
            name_filters = Q(transportador__iexact=user.first_name) if user.first_name else Q()
            username_filter = Q(transportador__iexact=user.username)
            queryset = queryset.filter(
                Q(transportador_usuario=user) | name_filters | username_filter
            )
        return queryset

    def _es_remision_del_transportador(self, instance, user):
        if instance.transportador_usuario_id == user.id:
            return True
        if user.first_name and instance.transportador and instance.transportador.lower() == user.first_name.lower():
            return True
        if instance.transportador and instance.transportador.lower() == (user.username or '').lower():
            return True
        return False

    def update(self, request, *args, **kwargs):
        # OJO: UpdateModelMixin.partial_update() delega en self.update(partial=True), así que
        # este bloqueo solo debe aplicar a un PUT completo real, no al PATCH ya validado en
        # partial_update() más abajo.
        if request.user.role == 'transportador' and not kwargs.get('partial', False):
            return Response({'error': 'No tienes permiso para realizar esta acción.'}, status=status.HTTP_403_FORBIDDEN)
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        if request.user.role == 'transportador':
            instance = self.get_object()
            if not self._es_remision_del_transportador(instance, request.user):
                return Response({'error': 'No tienes permiso para modificar esta remisión.'}, status=status.HTTP_403_FORBIDDEN)
            campos_enviados = set(request.data.keys())
            if campos_enviados - {'estado'} or request.data.get('estado') != 'finalizada':
                return Response(
                    {'error': 'Como transportador solo puedes marcar la remisión como "finalizada".'},
                    status=status.HTTP_403_FORBIDDEN
                )
        return super().partial_update(request, *args, **kwargs)

    def perform_create(self, serializer):
        remision = serializer.save()
        # Update associated inventory items to 'por_despachar'
        if remision.inventario_items.exists():
            remision.inventario_items.update(disponibilidad='por_despachar')

    def perform_update(self, serializer):
        old_estado = self.get_object().estado
        remision = serializer.save()
        new_estado = remision.estado

        if old_estado != new_estado:
            items = remision.inventario_items.all()
            if new_estado == 'despachada':
                items.update(disponibilidad='despachado')
            elif new_estado == 'finalizada':
                items.update(disponibilidad='entregado')
                # Check groups: if all items in a group are delivered, deactivate group
                grupos = set(item.grupo for item in items if item.grupo)
                for grupo in grupos:
                    # If all items in this group are delivered
                    if not grupo.items_inventario.exclude(disponibilidad='entregado').exists():
                        grupo.activo = False
                        grupo.save()


class GrupoInventarioViewSet(viewsets.ModelViewSet):
    def get_permissions(self):
        if self.action in ['create']:
            return [IsAuthenticated(), check_feature_permission('CREAR_ITEM_INVENTARIO')()]
        elif self.action in ['update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), check_feature_permission('EDITAR_ITEM_INVENTARIO')()]
        return [IsAuthenticated(), check_feature_permission('VER_INVENTARIO')()]
    queryset = GrupoInventario.objects.prefetch_related(
        'componentes',
        'componentes__referencia',
        'componentes__categoria',
        'componentes__subcategoria',
        'items_inventario',
    )

    def get_queryset(self):
        qs = self.queryset.all()
        return qs.exclude(activo=False)
    serializer_class = GrupoInventarioSerializer
    filter_backends = [SearchFilter]
    search_fields = ['nombre']
