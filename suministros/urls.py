from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    CategoriaViewSet, SubcategoriaViewSet,
    InventarioViewSet, FacturaProveedorViewSet, DetalleFacturaViewSet,
    RemisionSuministroViewSet, GrupoInventarioViewSet
)

router = DefaultRouter()
router.register(r'categorias', CategoriaViewSet)
router.register(r'subcategorias', SubcategoriaViewSet)
router.register(r'inventario', InventarioViewSet)
router.register(r'facturas', FacturaProveedorViewSet)
router.register(r'facturas-detalle', DetalleFacturaViewSet)
router.register(r'remisiones', RemisionSuministroViewSet)
router.register(r'grupos', GrupoInventarioViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
