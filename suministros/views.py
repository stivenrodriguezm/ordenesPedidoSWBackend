from django.db.models import Q
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from .models import (
    Categoria, Subcategoria, Inventario,
    FacturaProveedor, DetalleFactura, RemisionSuministro,
    GrupoInventario, Sede, Zona, HistorialTraslado, CostoAdicionalInventario
)
from .serializers import (
    CategoriaSerializer, SubcategoriaSerializer,
    InventarioSerializer, FacturaProveedorSerializer, FacturaProveedorListSerializer,
    DetalleFacturaSerializer, RemisionSuministroSerializer, GrupoInventarioSerializer,
    SedeSerializer, ZonaSerializer, HistorialTrasladoSerializer,
    CostoAdicionalInventarioSerializer
)
from rest_framework.permissions import IsAuthenticated
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

class ZonaViewSet(viewsets.ModelViewSet):
    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), check_feature_permission('ADMINISTRAR_BASES')()]
        return [IsAuthenticated()]
    queryset = Zona.objects.select_related('sede').all()
    serializer_class = ZonaSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['sede']

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
        'costos_adicionales'
    )
    serializer_class = InventarioSerializer

    def get_queryset(self):
        return self.queryset.all()
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
        if self.action != 'list':
            qs = qs.prefetch_related(
                'items_inventario',
                'items_inventario__referencia',
                'items_inventario__referencia__proveedor',
                'items_inventario__categoria',
                'items_inventario__subcategoria',
                'items_inventario__venta',
            )
        return qs.all()
        
    def get_serializer_class(self):
        if self.action == 'list':
            return FacturaProveedorListSerializer
        return FacturaProveedorSerializer
        
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['estado', 'proveedor']
    search_fields = ['id_manual', 'proveedor__nombre_empresa']
    ordering_fields = ['fecha_factura', 'fecha_pago']
    ordering = ['-fecha_factura', '-id']

class DetalleFacturaViewSet(viewsets.ModelViewSet):
    queryset = DetalleFactura.objects.all()
    serializer_class = DetalleFacturaSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['factura']

class RemisionSuministroViewSet(viewsets.ModelViewSet):
    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update', 'destroy']:
            return [IsAuthenticated(), check_feature_permission('CREAR_REMISION')()]
        return [IsAuthenticated(), check_feature_permission('VER_REMISIONES')()]
        
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
        'componentes__subcategoria',
        'items_inventario',
    )

    def get_queryset(self):
        qs = self.queryset.all()
        return qs.exclude(activo=False)
    serializer_class = GrupoInventarioSerializer
    filter_backends = [SearchFilter]
    search_fields = ['nombre']
