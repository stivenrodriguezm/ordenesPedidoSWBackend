from rest_framework.routers import DefaultRouter
from .views import ReferenciaViewSet, ProveedorViewSet, OrdenPedidoViewSet, DetallePedidoViewSet
from .views import UserDetailView
from django.urls import path
from .views import UserDetailView, listar_pedidos, listar_vendedores, detalles_pedido
from .views import cambiar_contrasena

router = DefaultRouter()
router.register(r'referencias', ReferenciaViewSet)
router.register(r'proveedores', ProveedorViewSet)
router.register(r'ordenes', OrdenPedidoViewSet)
router.register(r'detalles', DetallePedidoViewSet)

urlpatterns = [
    path("user/", UserDetailView.as_view(), name="user-detail"),
    path('vendedores/', listar_vendedores, name='listar_vendedores'),
    path('listar-pedidos/', listar_pedidos, name='listar_pedidos'),
    path('detalles-pedido/<int:orden_id>/', detalles_pedido, name='detalles_pedido'),
    path('cambiar-contrasena/', cambiar_contrasena, name='cambiar_contrasena'),
] + router.urls
