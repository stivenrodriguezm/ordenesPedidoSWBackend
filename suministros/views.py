from django.db.models import Q
from rest_framework import viewsets
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from .models import (
    Categoria, Subcategoria, Inventario,
    FacturaProveedor, DetalleFactura, RemisionSuministro,
    GrupoInventario
)
from .serializers import (
    CategoriaSerializer, SubcategoriaSerializer,
    InventarioSerializer, FacturaProveedorSerializer, DetalleFacturaSerializer,
    RemisionSuministroSerializer, GrupoInventarioSerializer
)
from rest_framework.permissions import IsAuthenticated
from ordenes.permissions import check_feature_permission

class CategoriaViewSet(viewsets.ModelViewSet):
    queryset = Categoria.objects.all()
    serializer_class = CategoriaSerializer

class SubcategoriaViewSet(viewsets.ModelViewSet):
    queryset = Subcategoria.objects.all()
    serializer_class = SubcategoriaSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter]
    filterset_fields = ['categoria']
    search_fields = ['nombre']

class InventarioViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, check_feature_permission('VER_INVENTARIO')]
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
    ).all()
    serializer_class = InventarioSerializer
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['disponibilidad', 'categoria', 'subcategoria', 'referencia__proveedor']
    search_fields = ['id_referencia', 'referencia__nombre', 'variacion', 'factura_manual']
    ordering_fields = ['fecha_ingreso', 'id_referencia']

class FacturaProveedorViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, check_feature_permission('VER_FACTURAS')]
    queryset = FacturaProveedor.objects.select_related('proveedor').prefetch_related(
        'items_inventario',
        'items_inventario__referencia',
        'items_inventario__referencia__proveedor',
        'items_inventario__categoria',
        'items_inventario__subcategoria',
        'items_inventario__venta',
    ).all()
    serializer_class = FacturaProveedorSerializer
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
    permission_classes = [IsAuthenticated, check_feature_permission('VER_REMISIONES')]
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


class GrupoInventarioViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    queryset = GrupoInventario.objects.prefetch_related(
        'componentes',
        'componentes__referencia',
        'componentes__categoria',
        'componentes__subcategoria',
        'items_inventario',
    ).all()
    serializer_class = GrupoInventarioSerializer
    filter_backends = [SearchFilter]
    search_fields = ['nombre']
