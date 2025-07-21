# ==================== ordenes/urls.py (CORRECCIÓN FINAL) ====================

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    caja_dashboard_view, # Nueva vista
    ReferenciaViewSet, ProveedorViewSet, OrdenPedidoViewSet, DetallePedidoViewSet,
    listar_pedidos, detalles_pedido, CrearVentaClienteView, EditarVentaClienteView,
    listar_ventas, detalle_venta, anadir_observacion_venta, anadir_remision_a_venta,
    ver_remisiones_de_venta, listar_clientes, obtener_cliente, ventas_y_observaciones_cliente,
    anadir_observacion_cliente, movimientos_caja, listar_recibos_caja, 
    listar_comprobantes_egreso, crear_comprobante_egreso, crear_recibo_caja, 
    confirmar_recibo, listar_vendedores, UserDetailView, cambiar_contrasena,
    dashboard_stats, sales_chart_data, cierre_caja, listar_ventas_pendientes_ids
)

router = DefaultRouter()
router.register(r'referencias', ReferenciaViewSet)
router.register(r'proveedores', ProveedorViewSet)
router.register(r'ordenes-pedido', OrdenPedidoViewSet)
router.register(r'detalles-pedido', DetallePedidoViewSet)

urlpatterns = [
    path('', include(router.urls)),
    path('caja/dashboard/', caja_dashboard_view, name='caja-dashboard'), # Nueva URL
    path('listar-pedidos/', listar_pedidos, name='listar-pedidos'),
    path('pedidos/<int:orden_id>/detalles/', detalles_pedido, name='detalles-pedido'),
    path('ventas/crear/', CrearVentaClienteView.as_view(), name='crear-venta-cliente'),
    path('ventas/<int:id>/editar/', EditarVentaClienteView.as_view(), name='editar-venta-cliente'),
    path('ventas/', listar_ventas, name='listar-ventas'),
    path('ventas/<int:id>/', detalle_venta, name='detalle-venta'),
    path('ventas/<int:id>/observaciones/', anadir_observacion_venta, name='anadir-observacion-venta'),
    path('ventas/<int:id>/remisiones/', anadir_remision_a_venta, name='anadir-remision-venta'),
    path('ventas/<int:id>/remisiones/ver/', ver_remisiones_de_venta, name='ver-remisiones-venta'),
    path('clientes/', listar_clientes, name='listar-clientes'),
    path('clientes/<int:id>/', obtener_cliente, name='obtener-cliente'),
    path('clientes/<int:id>/ventas-observaciones/', ventas_y_observaciones_cliente, name='ventas-y-observaciones-cliente'),
    path('clientes/<int:id>/observaciones/anadir/', anadir_observacion_cliente, name='anadir-observacion-cliente'),
    path('caja/movimientos/', movimientos_caja, name='movimientos-caja'),
    path('recibos-caja/', listar_recibos_caja, name='listar-recibos-caja'),
    path('comprobantes-egreso/', listar_comprobantes_egreso, name='listar-comprobantes-egreso'),
    path('comprobantes-egreso/crear/', crear_comprobante_egreso, name='crear-comprobante-egreso'),
    path('recibos-caja/crear/', crear_recibo_caja, name='crear-recibo-caja'),
    path('recibos-caja/<int:id>/confirmar/', confirmar_recibo, name='confirmar-recibo'),
    path('vendedores/', listar_vendedores, name='listar-vendedores'),
    path('user/', UserDetailView.as_view(), name='user-detail'),
    path('user/cambiar-contrasena/', cambiar_contrasena, name='cambiar-contrasena'),
    path('dashboard-stats/', dashboard_stats, name='dashboard-stats'),
    path('sales-chart-data/', sales_chart_data, name='sales-chart-data'),
    path('caja/cierre/', cierre_caja, name='cierre-caja'),
    path('ventas/pendientes/ids/', listar_ventas_pendientes_ids, name='listar-ventas-pendientes-ids'),
]