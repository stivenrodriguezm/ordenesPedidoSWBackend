from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    CategoriaListaViewSet, GrupoTelaViewSet, MultiplicadorViewSet,
    LineaProductoViewSet, VarianteProductoViewSet, CargoVarianteViewSet,
    PrecioVarianteViewSet, categorias_publicas, catalogo, upload_foto,
    calcular_precio_variante,
)

router = DefaultRouter()
router.register(r'categorias', CategoriaListaViewSet)
router.register(r'multiplicadores', MultiplicadorViewSet)
router.register(r'grupos-tela', GrupoTelaViewSet)
router.register(r'lineas', LineaProductoViewSet)
router.register(r'variantes', VarianteProductoViewSet)
router.register(r'cargos', CargoVarianteViewSet)
router.register(r'precios', PrecioVarianteViewSet)

urlpatterns = [
    path('categorias-publicas/', categorias_publicas, name='listaprecios-categorias-publicas'),
    path('catalogo/', catalogo, name='listaprecios-catalogo'),
    path('upload-foto/', upload_foto, name='listaprecios-upload-foto'),
    path('variantes/<int:variante_id>/precio/', calcular_precio_variante, name='listaprecios-calcular-precio-variante'),
    path('', include(router.urls)),
]
