from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    CategoriaViewSet, SubcategoriaViewSet,
    InventarioViewSet, FacturaProveedorViewSet, DetalleFacturaViewSet,
    RemisionSuministroViewSet, GrupoInventarioViewSet,
    SedeViewSet, ZonaViewSet, HistorialTrasladoViewSet, CostoAdicionalInventarioViewSet
)

router = DefaultRouter()
router.register(r'categorias', CategoriaViewSet)
router.register(r'subcategorias', SubcategoriaViewSet)
router.register(r'inventario', InventarioViewSet)
router.register(r'facturas', FacturaProveedorViewSet)
router.register(r'facturas-detalle', DetalleFacturaViewSet)
router.register(r'remisiones', RemisionSuministroViewSet)
router.register(r'grupos', GrupoInventarioViewSet)
router.register(r'sedes', SedeViewSet)
router.register(r'zonas', ZonaViewSet)
router.register(r'historial-traslados', HistorialTrasladoViewSet)
router.register(r'costos-adicionales', CostoAdicionalInventarioViewSet, basename='costos-adicionales')

urlpatterns = [
    path('', include(router.urls)),
]
