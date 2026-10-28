from . import gestion_venta, productos_venta, oficina, coordinacion
from .asistente import views as asistente_views
from .asistente import automatizaciones_views as automatizaciones_ia
from .asistente import academia_views
from .asistente import agente_views
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import nomina_views
from .views import (
    caja_view,
    ReferenciaViewSet, ProveedorViewSet, OrdenPedidoViewSet, DetallePedidoViewSet,
    listar_pedidos, detalles_pedido, detalle_orden_completo, subir_imagen_pedido_feria, CrearVentaClienteView, EditarVentaClienteView,
    listar_ventas, detalle_venta, marcar_venta_facturada, anadir_observacion_venta, anadir_remision_a_venta,
    ver_remisiones_de_venta, listar_clientes, obtener_cliente, ventas_y_observaciones_cliente,
    anadir_observacion_cliente, listar_recibos_caja, editar_eliminar_observacion_venta, editar_eliminar_observacion_cliente, 
    listar_comprobantes_egreso, crear_comprobante_egreso, confirmar_comprobante_egreso, editar_comprobante_egreso, crear_recibo_caja,
    editar_recibo_caja, anular_recibo_caja, confirmar_pago_recibo, siguiente_numero_recibo, subir_comprobante_recibo,
    agregar_comprobantes_recibo, quitar_comprobante_recibo, listar_vendedores, UserDetailView, cambiar_contrasena,
    dashboard_stats, sales_chart_data, cierre_caja, listar_ventas_pendientes_ids,
    vendedor_recent_activity, listar_transportadores,
    ProveedorTelaViewSet, PedidoTelaViewSet, DetallePedidoTelaViewSet, DireccionEntregaViewSet, UserViewSet, RolePermissionViewSet
)

from .calidad_clientes_views import CalidadClientesViewSet
from .clientes_exportacion import exportar_clientes
from .reportes_views import exportar_reporte
from .dashboard_admin import dashboard_admin

router = DefaultRouter()
router.register(r'calidad-clientes', CalidadClientesViewSet, basename='calidad-clientes')
router.register(r'referencias', ReferenciaViewSet)
router.register(r'proveedores', ProveedorViewSet)
router.register(r'ordenes-pedido', OrdenPedidoViewSet)
router.register(r'detalles-pedido', DetallePedidoViewSet)
router.register(r'proveedores-telas', ProveedorTelaViewSet)
router.register(r'pedidos-telas', PedidoTelaViewSet)
router.register(r'detalles-pedido-tela', DetallePedidoTelaViewSet)
router.register(r'direcciones-entrega', DireccionEntregaViewSet)
router.register(r'usuarios', UserViewSet)
router.register(r'role-permissions', RolePermissionViewSet, basename='role-permissions')

urlpatterns = [
    path('oficina/coordinacion/', coordinacion.programa),
    path('oficina/informes/', coordinacion.solicitar),
    path('oficina/informes/<int:pk>/', coordinacion.detalle),
    path('oficina/interacciones/', coordinacion.interacciones),
    path('oficina/estado/', oficina.estado),
    path('oficina/equipo/', oficina.equipo),
    path('oficina/presencia/', oficina.presencia),
    path('oficina/mensajes/', oficina.mensajes),
    path('oficina/conversaciones/', oficina.conversaciones),
    path('oficina/mensajes/leer/', oficina.leer_mensajes),
    path('oficina/mensajes/<int:pk>/', oficina.mensaje),
    path('oficina/trabajos/', oficina.trabajos),
    path('oficina/trabajos/<int:pk>/', oficina.trabajo),
    path('oficina/trabajos/<int:pk>/comentarios/', oficina.comentar),
    path('oficina/personas/<int:pk>/ventas/', oficina.ventas_persona),
    path('ventas/<int:venta_id>/productos/vincular-pedidos/', productos_venta.vincular_pedidos),
    path('productos-venta/pedidos/<int:pedido_id>/recepcion/', productos_venta.preparar_recepcion),
    path('ventas/<int:venta_id>/productos/calcular/', productos_venta.precio_producto),
    path('productos-venta/catalogo/', productos_venta.catalogo_productos),
    path('productos-venta/proveedores/<int:proveedor_id>/por-facturar/', productos_venta.pendientes_factura),
    path('productos-venta/referencias/', productos_venta.referencias_productos),
    path('ventas/<int:venta_id>/productos/', productos_venta.productos),
    path('ventas/<int:venta_id>/productos/pedidos/', productos_venta.pedidos),
    path('ventas/<int:venta_id>/gestion/', gestion_venta.gestion),
    # Chat: asesor gerencial con IA (USAR_ASISTENTE_IA)
    path('asistente/estado/', asistente_views.estado),
    path('asistente/agente/trabajos/', agente_views.trabajos),
    path('asistente/agente/trabajos/<int:pk>/', agente_views.trabajo),
    path('asistente/equipo/hilos/', agente_views.equipo_hilos),
    path('asistente/equipo/hilos/<str:clave>/', agente_views.equipo_hilo),
    path('asistente/academia/conexion/', academia_views.conexion),
    path('asistente/academia/cursos/', academia_views.cursos),
    path('asistente/academia/cursos/<int:pk>/', academia_views.curso),
    path('asistente/academia/cursos/<int:pk>/videos/<int:indice>/', academia_views.video),
    path('asistente/general/', asistente_views.configurar_general),
    path('asistente/oficina-actividad/', automatizaciones_ia.actividad),
    path('asistente/automatizaciones/', automatizaciones_ia.lista),
    path('asistente/automatizaciones/<int:pk>/', automatizaciones_ia.detalle),
    path('asistente/automatizaciones/<int:pk>/ejecutar/', automatizaciones_ia.ejecutar_ahora),
    path('asistente/automatizaciones/<int:pk>/ejecuciones/', automatizaciones_ia.historial),
    path('asistente/ejecuciones/<int:pk>/', automatizaciones_ia.ejecucion),
    path('asistente/conversaciones/', asistente_views.conversaciones),
    path('asistente/conversaciones/<int:pk>/', asistente_views.conversacion),
    path('asistente/preguntar/', asistente_views.preguntar),
    path('asistente/mensajes/<int:pk>/', asistente_views.mensaje),
    path('asistente/mensajes/<int:pk>/valorar/', asistente_views.valorar),
    path('asistente/mensajes/<int:pk>/notas/', asistente_views.notas),
    path('asistente/aprendizajes/', asistente_views.aprendizajes),
    path('asistente/aprendizajes/<int:pk>/', asistente_views.aprendizaje),
    path('asistente/perfiles/', asistente_views.lista_perfiles),
    path('asistente/zonas/', asistente_views.zonas_oficina),
    path('asistente/zonas/<int:pk>/', asistente_views.zona_oficina),
    path('asistente/perfiles/<int:pk>/', asistente_views.detalle_perfil),
    path('asistente/perfiles/<int:pk>/documentos/', asistente_views.documentos_perfil),
    path('asistente/perfiles/<int:pk>/documentos/<int:doc>/', asistente_views.documento_perfil),
    # Nómina de asesores (D12a)
    path('nomina/config/', nomina_views.config_nomina, name='nomina-config'),
    path('nomina/asesores/', nomina_views.asesores_nomina, name='nomina-asesores'),
    path('nomina/asesores/<int:asesor_id>/', nomina_views.editar_asesor_nomina, name='nomina-asesor'),
    path('nomina/cierres/', nomina_views.cierres, name='nomina-cierres'),
    path('nomina/cierres/<int:pk>/', nomina_views.cierre_detalle, name='nomina-cierre'),
    path('nomina/cierres/<int:pk>/<str:accion>/', nomina_views.cierre_accion, name='nomina-cierre-accion'),
    path('nomina/asesores-cierre/<int:pk>/', nomina_views.asesor_cierre, name='nomina-asesor-cierre'),
    path('nomina/asesores-cierre/<int:pk>/ajustes/', nomina_views.ajustes, name='nomina-ajustes'),
    path('nomina/asesores-cierre/<int:pk>/<str:accion>/', nomina_views.asesor_accion, name='nomina-asesor-accion'),
    path('nomina/lineas/<int:pk>/', nomina_views.linea, name='nomina-linea'),
    path('nomina/lineas/<int:pk>/venta/', nomina_views.venta_de_linea, name='nomina-linea-venta'),
    path('reportes-operativos/<str:reporte>/exportar/', exportar_reporte, name='exportar-reporte-operativo'),
    path('', include(router.urls)),
    path('caja/', caja_view, name='caja-view'),
    path('listar-pedidos/', listar_pedidos, name='listar-pedidos'),
    path('pedidos/<int:orden_id>/detalles/', detalles_pedido, name='detalles-pedido'),
    path('ordenes-pedido/<int:orden_id>/completo/', detalle_orden_completo, name='detalle-orden-completo'),
    path('ordenes-pedido/feria-hogar/subir-imagen/', subir_imagen_pedido_feria, name='subir-imagen-pedido-feria'),
    path('ventas/crear/', CrearVentaClienteView.as_view(), name='crear-venta-cliente'),
    path('ventas/<int:id>/editar/', EditarVentaClienteView.as_view(), name='editar-venta-cliente'),
    path('ventas/', listar_ventas, name='listar-ventas'),
    path('ventas/<int:id>/', detalle_venta, name='detalle-venta'),
    path('ventas/<int:id>/facturada/', marcar_venta_facturada, name='venta-facturada'),
    path('ventas/<int:id>/observaciones/', anadir_observacion_venta, name='anadir-observacion-venta'),
    path('ventas/<int:id>/remisiones/', anadir_remision_a_venta, name='anadir-remision-venta'),
    path('ventas/<int:id>/remisiones/ver/', ver_remisiones_de_venta, name='ver-remisiones-venta'),
    path('clientes/', listar_clientes, name='listar-clientes'),
    path('clientes/exportar/', exportar_clientes, name='exportar-clientes'),
    path('clientes/<int:id>/', obtener_cliente, name='obtener-cliente'),
    path('clientes/<int:id>/ventas-observaciones/', ventas_y_observaciones_cliente, name='ventas-y-observaciones-cliente'),
    path('clientes/<int:id>/observaciones/anadir/', anadir_observacion_cliente, name='anadir-observacion-cliente'),
    path('recibos-caja/', listar_recibos_caja, name='listar-recibos-caja'),
    path('comprobantes-egreso/', listar_comprobantes_egreso, name='listar-comprobantes-egreso'),
    path('comprobantes-egreso/crear/', crear_comprobante_egreso, name='crear-comprobante-egreso'),
    path('comprobantes-egreso/<int:id>/confirmar/', confirmar_comprobante_egreso, name='confirmar-comprobante-egreso'),
    path('comprobantes-egreso/<int:id>/editar/', editar_comprobante_egreso, name='editar-comprobante-egreso'),
    path('recibos-caja/crear/', crear_recibo_caja, name='crear-recibo-caja'),
    path('recibos-caja/siguiente-numero/', siguiente_numero_recibo, name='siguiente-numero-recibo'),
    path('recibos-caja/comprobantes/subir/', subir_comprobante_recibo, name='subir-comprobante-recibo'),
    path('recibos-caja/comprobantes/<int:comprobante_id>/', quitar_comprobante_recibo, name='quitar-comprobante-recibo'),
    path('recibos-caja/<int:recibo_id>/comprobantes/', agregar_comprobantes_recibo, name='agregar-comprobantes-recibo'),
    path('recibos-caja/<int:recibo_id>/editar/', editar_recibo_caja, name='editar-recibo-caja'),
    path('recibos-caja/<int:recibo_id>/anular/', anular_recibo_caja, name='anular-recibo-caja'),
    path('recibos-caja/pagos/<int:pago_id>/confirmar/', confirmar_pago_recibo, name='confirmar-pago-recibo'),
    path('vendedores/', listar_vendedores, name='listar-vendedores'),
    path('user/', UserDetailView.as_view(), name='user-detail'),
    path('user/cambiar-contrasena/', cambiar_contrasena, name='cambiar-contrasena'),
    path('dashboard-stats/', dashboard_stats, name='dashboard-stats'),
    path('dashboard-admin/', dashboard_admin, name='dashboard-admin'),
    path('sales-chart-data/', sales_chart_data, name='sales-chart-data'),
    path('caja/cierre/', cierre_caja, name='cierre-caja'),
    path('vendedor-recent-activity/', vendedor_recent_activity, name='vendedor-recent-activity'),
    path('get-pendientes-ids/', listar_ventas_pendientes_ids, name='get-pendientes-ids'),
    path('transportadores/', listar_transportadores, name='listar-transportadores'),
    path('observaciones-venta/<int:obs_id>/', editar_eliminar_observacion_venta, name='editar-eliminar-observacion-venta'),
    path('observaciones-cliente/<int:obs_id>/', editar_eliminar_observacion_cliente, name='editar-eliminar-observacion-cliente'),
]
