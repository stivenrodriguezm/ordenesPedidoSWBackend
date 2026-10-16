"""P14-01: recorridos integrales por rol con los permisos REALES configurados
(foto del 2026-10-06 en roles_reales.py), por la API y con datos ficticios.

Cubre lo que pide el plan: vendedor principal/compartido, auxiliar, bodega
(en la operación real lo hace el auxiliar), transportador, aprobador (hoy solo
el administrador aprueba) y administrador; compra para cliente y para stock,
contado/transferencia, parcial, anulación, devolución, costo restringido y
documento histórico. Las pantallas nuevas se verifican contra el permiso que
exige cada una, para saber qué hay que asignar al desplegar."""
from datetime import date
from decimal import Decimal

from ordenes.models import DetallePedido, OrdenPedido, PagoReciboCaja, ReciboCaja, RolePermission, Venta
from ordenes.permissions import PERMISSION_ALIASES
from ordenes.servicios import cuenta_principal
from ordenes.tests.roles_reales import ROLES_REALES_2026_10_06 as ROLES
from ordenes.tests.utils import LottusTestCase
from suministros.models import Inventario, MovimientoInventario, RemisionSuministro


def tiene(rol, codigo):
    codigos = set(ROLES.get(rol, []))
    return rol == 'administrador' or 'ALL' in codigos or bool(PERMISSION_ALIASES.get(codigo, {codigo}) & codigos)


class RecorridosPorRolTests(LottusTestCase):
    def setUp(self):
        for rol, codigos in ROLES.items():
            RolePermission.objects.update_or_create(role=rol, defaults={'permissions': list(codigos)})
        self.admin = self.crear_usuario('admin-real', role='administrador')
        self.aux = self.crear_usuario('auxiliar-real', role='auxiliar')
        self.principal = self.crear_usuario('vendedora-principal')
        self.compartido = self.crear_usuario('vendedor-compartido')
        self.otro = self.crear_usuario('vendedor-otro')
        self.trans = self.crear_usuario('transporte-real', role='transportador')
        self.prov = self.proveedor('Fábrica ficticia')
        self.ref = self.referencia(self.prov, 'Comedor ficticio')

    def orden(self, cliente, venta=None, cantidad=1, **extra):
        r = self.api(cliente).post('/api/ordenes-pedido/', {
            'proveedor': self.prov.pk, 'fecha_esperada': str(date.today()), 'venta': venta.pk if venta else None,
            'detalles': [{'referencia': self.ref.pk, 'cantidad': cantidad, 'especificaciones': 'Ficticio'}], **extra,
        }, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        orden = OrdenPedido.objects.get(pk=r.data['id'])
        return orden, orden.detalles.get()

    def facturar(self, numero, linea, cantidad):
        r = self.api(self.aux).post('/api/suministros/facturas/', {
            'id_manual': numero, 'proveedor': self.prov.pk, 'valor': str(100 * cantidad),
            'productos': [{'referencia': self.ref.pk, 'costo': '100', 'cantidad': cantidad, 'detalle_pedido': linea.pk}],
        }, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        return r.data['id']

    def test_vendedor_principal_y_compartido_con_costo_restringido(self):
        venta = self.venta(self.principal)
        venta.vendedores_compartidos.add(self.compartido)
        ajena = self.venta(self.otro)
        comp = self.api(self.compartido)
        datos = comp.get('/api/ventas/').data
        ids = {v['id'] for v in (datos['results'] if isinstance(datos, dict) else datos)}
        self.assertIn(venta.pk, ids)
        self.assertNotIn(ajena.pk, ids)
        remision = {'fecha_entrega': str(date.today()), 'items_manuales': [{'referencia': 'Silla', 'cantidad': 1}]}
        self.assertEqual(comp.post('/api/suministros/remisiones/', {**remision, 'ventas': [venta.pk]}, format='json').status_code, 201)
        self.assertEqual(comp.post('/api/suministros/remisiones/', {**remision, 'ventas': [ajena.pk]}, format='json').status_code, 400)
        # La principal pide al proveedor para su venta y no ve costos.
        orden, _ = self.orden(self.principal, venta)
        prin = self.api(self.principal)
        self.assertNotIn('costo', prin.get(f'/api/ordenes-pedido/{orden.pk}/').data)
        self.assertIn('costo', self.api(self.aux).get(f'/api/ordenes-pedido/{orden.pk}/').data)
        # Lo que la configuración real no le da al vendedor.
        self.assertEqual(prin.get('/api/suministros/inventario/').status_code, 403)
        self.assertEqual(prin.post('/api/recibos-caja/crear/', {'venta': venta.pk, 'pagos': []}, format='json').status_code, 403)

    def test_auxiliar_compra_para_cliente_y_stock_cobro_contado_y_transferencia(self):
        venta = self.venta(self.principal, valor='500')
        _, linea_cliente = self.orden(self.aux, venta)
        _, linea_stock = self.orden(self.aux, None, es_exhibicion=True)
        self.facturar('F-CLI', linea_cliente, 1)
        self.facturar('F-STK', linea_stock, 1)
        u_cliente = Inventario.objects.get(detalle_pedido=linea_cliente)
        u_stock = Inventario.objects.get(detalle_pedido=linea_stock)
        self.assertEqual((u_cliente.venta_id, u_cliente.disponibilidad), (venta.pk, 'cliente'))
        self.assertEqual((u_stock.venta_id, u_stock.disponibilidad), (None, 'exhibicion'))

        r = self.api(self.aux).post('/api/recibos-caja/crear/', {'id': 15001, 'venta': venta.pk, 'pagos': [
            {'metodo_pago': 'Efectivo', 'valor': '300'}, {'metodo_pago': 'Bancolombia', 'valor': '200'}]}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(cuenta_principal().saldo, Decimal('300'))
        transferencia = PagoReciboCaja.objects.get(metodo_pago='Bancolombia')
        url = f'/api/recibos-caja/pagos/{transferencia.pk}/confirmar/'
        # Configuración real: el auxiliar registra, solo el administrador confirma (D01).
        self.assertEqual(tiene('auxiliar', 'APROBAR_RECIBO'), False)
        self.assertEqual(self.api(self.aux).patch(url).status_code, 403)
        self.assertEqual(self.api(self.admin).patch(url).status_code, 200)
        venta.refresh_from_db()
        self.assertEqual(venta.saldo, Decimal('0'))
        self.assertEqual(cuenta_principal().saldo, Decimal('300'))

    def test_parcial_entrega_anulacion_y_devolucion(self):
        venta = self.venta(self.principal, valor='900')
        orden, linea = self.orden(self.aux, venta, cantidad=3)
        self.facturar('F-1', linea, 2)
        orden.refresh_from_db()
        self.assertEqual(orden.estado, 'pendiente')
        u1, u2 = Inventario.objects.filter(detalle_pedido=linea).order_by('pk')

        # Configuración real: el auxiliar no tiene CREAR_REMISION; la vendedora la crea.
        crear = {'ventas': [venta.pk], 'fecha_entrega': str(date.today()), 'inventario_items': [u1.pk, u2.pk],
                 'transportador_usuario': self.trans.pk}
        self.assertEqual(self.api(self.aux).post('/api/suministros/remisiones/', crear, format='json').status_code, 403)
        r = self.api(self.principal).post('/api/suministros/remisiones/', crear, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        rem = r.data['id']
        trans = self.api(self.trans)
        self.assertEqual(trans.patch(f'/api/suministros/remisiones/{rem}/', {'estado': 'despachada'}, format='json').status_code, 200)
        r = trans.patch(f'/api/suministros/remisiones/{rem}/', {
            'estado': 'finalizada', 'no_entregados': [{'inventario': u2.pk, 'motivo': 'danado', 'detalle': 'Golpe'}]}, format='json')
        self.assertEqual(r.status_code, 200, r.data)

        # La unidad dañada se devuelve al proveedor: la línea vuelve a pedir 2.
        r = self.api(self.aux).post(f'/api/suministros/inventario/{u2.pk}/devolver-proveedor/', {'motivo': 'Golpe en el transporte'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(self.api(self.aux).get(f'/api/ordenes-pedido/{orden.pk}/completo/').data['detalles'][0]['recibidas'], 1)

        # Anulación de remisión (administrador) libera lo reservado.
        self.facturar('F-2', linea, 1)
        u3 = Inventario.objects.filter(detalle_pedido=linea).exclude(pk__in=[u1.pk, u2.pk]).get()
        r = self.api(self.principal).post('/api/suministros/remisiones/', {**crear, 'inventario_items': [u3.pk]}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        rem2 = r.data['id']
        self.assertEqual(self.api(self.principal).patch(f'/api/suministros/remisiones/{rem2}/', {'estado': 'anulada', 'motivo': 'Cambio de fecha'}, format='json').status_code, 403)
        self.assertEqual(self.api(self.admin).patch(f'/api/suministros/remisiones/{rem2}/', {'estado': 'anulada', 'motivo': 'Cambio de fecha'}, format='json').status_code, 200)
        u3.refresh_from_db()
        self.assertEqual(u3.disponibilidad, 'cliente')

        # Anulación de un cobro: solo el administrador (EDITAR_RECIBO) y deja el saldo como estaba.
        r = self.api(self.aux).post('/api/recibos-caja/crear/', {'id': 15002, 'venta': venta.pk, 'pagos': [
            {'metodo_pago': 'Efectivo', 'valor': '400'}]}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(self.api(self.aux).put('/api/recibos-caja/15002/anular/', {'motivo': 'Error de digitación'}, format='json').status_code, 403)
        r = self.api(self.admin).put('/api/recibos-caja/15002/anular/', {'motivo': 'Error de digitación'}, format='json')
        self.assertIn(r.status_code, (200, 201), r.data)
        venta.refresh_from_db()
        self.assertEqual(venta.saldo, Decimal('900'))
        self.assertEqual(cuenta_principal().saldo, Decimal('0'))

    def test_documentos_historicos(self):
        """Datos anteriores a esta versión: orden marcada recibida a mano sin
        unidades ligadas y unidad sin factura ni movimientos."""
        venta = self.venta(self.principal)
        orden = OrdenPedido.objects.create(proveedor=self.prov, usuario=self.admin, venta=venta,
                                           fecha_esperada=date(2026, 5, 1), estado='recibido')
        DetallePedido.objects.create(orden=orden, referencia=self.ref, cantidad=2, especificaciones='Histórica')
        vieja = Inventario.objects.create(id_referencia='HIST-1', referencia=self.ref, venta=venta, disponibilidad='cliente')
        detalle = self.api(self.aux).get(f'/api/ordenes-pedido/{orden.pk}/completo/').data
        self.assertEqual((detalle['estado'], detalle['detalles'][0]['recibidas']), ('recibido', 0))
        self.assertEqual(self.api(self.aux).get('/api/suministros/inventario/HIST-1/movimientos/').data, [])
        r = self.api(self.principal).post('/api/suministros/remisiones/', {
            'ventas': [venta.pk], 'fecha_entrega': str(date.today()), 'inventario_items': [vieja.pk]}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(list(MovimientoInventario.objects.filter(item=vieja).values_list('tipo', flat=True)), ['reserva'])
        orden.refresh_from_db()
        self.assertEqual(orden.estado, 'recibido')

    def test_pantallas_nuevas_segun_permisos_reales(self):
        """Cada pantalla nueva responde según el permiso que exige y la
        configuración real. Lo que sale en False hay que asignarlo al desplegar."""
        pantallas = {
            '/api/calidad-clientes/': ['VER_CLIENTES', 'VER_CALIDAD_CLIENTES'],
        }
        usuarios = {'administrador': self.admin, 'auxiliar': self.aux, 'vendedor': self.principal, 'transportador': self.trans}
        obtenido, esperado = {}, {}
        for rol, usuario in usuarios.items():
            c = self.api(usuario)
            for url, codigos in pantallas.items():
                obtenido[(rol, url)] = c.get(url).status_code != 403
                esperado[(rol, url)] = all(tiene(rol, cod) for cod in codigos)
        self.assertEqual(obtenido, esperado)
        # Foto para la publicación: el auxiliar real todavía no tiene estas pantallas.
        sin_asignar = sorted(url for (rol, url), ok in obtenido.items() if rol == 'auxiliar' and not ok)
        self.assertEqual(sin_asignar, ['/api/calidad-clientes/'])
