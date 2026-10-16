"""Regresiones de autorización por objeto en ventas y órdenes y validación de
detalles de órdenes (H05, H06, H27 · P02-01, P04-02 · anexo A)."""
from datetime import date

from ordenes.models import DetallePedido, OrdenPedido, Venta
from ordenes.tests.utils import LottusTestCase


class VentaAjenaTests(LottusTestCase):
    def setUp(self):
        self.vendedor = self.crear_usuario('seller', role='vendedor')
        self.dueno = self.crear_usuario('owner', role='vendedor')
        self.permisos('vendedor', ['VER_VENTAS', 'EDITAR_ESTADO_VENTA', 'VER_ORDENES', 'VER_PROPIAS_ORDENES', 'VER_INVENTARIO'])
        self.ajena = self.venta(self.dueno)

    def test_edit_foreign_sale_and_customer_with_state_permission(self):
        c = self.api(self.vendedor)
        self.assertIn(c.get(f'/api/ventas/{self.ajena.pk}/').status_code, (403, 404))
        r = c.put(f'/api/ventas/{self.ajena.pk}/editar/', {
            'venta': {'estado': 'entregado'}, 'cliente': {'nombre': 'Modificado sin permiso'},
        }, format='json')
        self.assertIn(r.status_code, (403, 404))
        self.ajena.refresh_from_db()
        self.assertEqual(self.ajena.estado, 'pendiente')
        self.assertEqual(self.ajena.cliente.nombre, 'Cliente ficticio')

    def test_estado_de_venta_propia_sin_tocar_cliente(self):
        propia = self.venta(self.vendedor, cliente=self.cliente('c-2', 'Cliente dos'))
        c = self.api(self.vendedor)
        r = c.put(f'/api/ventas/{propia.pk}/editar/', {
            'venta': {'estado': 'entregado'}, 'cliente': {'nombre': 'Cambio no autorizado'},
        }, format='json')
        self.assertEqual(r.status_code, 403)
        propia.refresh_from_db()
        self.assertEqual(propia.cliente.nombre, 'Cliente dos')
        self.assertEqual(propia.estado, 'pendiente')
        r = c.put(f'/api/ventas/{propia.pk}/editar/', {'venta': {'estado': 'entregado'}}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        propia.refresh_from_db()
        self.assertEqual(propia.estado, 'entregado')

    def test_venta_compartida_es_propia(self):
        compartida = self.venta(self.dueno)
        compartida.vendedores_compartidos.add(self.vendedor)
        self.assertEqual(self.api(self.vendedor).get(f'/api/ventas/{compartida.pk}/').status_code, 200)

    def test_observaciones_y_remisiones_heredadas_de_venta_ajena(self):
        c = self.api(self.vendedor)
        self.assertIn(c.post(f'/api/ventas/{self.ajena.pk}/observaciones/', {'texto': 'x'}, format='json').status_code, (403, 404))
        self.assertIn(c.get(f'/api/ventas/{self.ajena.pk}/remisiones/ver/').status_code, (403, 404))
        self.assertIn(c.post(f'/api/ventas/{self.ajena.pk}/remisiones/', {'codigo': 'R-1'}, format='json').status_code, (403, 404))
        self.assertEqual(self.ajena.observaciones.count(), 0)

    def test_vendedor_con_edicion_completa_no_edita_venta_ajena(self):
        self.permisos('vendedor', ['VER_VENTAS', 'EDITAR_VENTA', 'EDITAR_CLIENTE'])
        r = self.api(self.vendedor).put(f'/api/ventas/{self.ajena.pk}/editar/', {
            'venta': {'valor_total': '1'},
        }, format='json')
        self.assertIn(r.status_code, (403, 404))
        self.ajena.refresh_from_db()
        self.assertEqual(str(self.ajena.valor_total), '1000.00')

    def test_cliente_editable_con_permisos_completos(self):
        propia = self.venta(self.vendedor, cliente=self.cliente('c-3', 'Cliente tres'))
        self.permisos('vendedor', ['VER_VENTAS', 'EDITAR_VENTA', 'EDITAR_CLIENTE'])
        r = self.api(self.vendedor).put(f'/api/ventas/{propia.pk}/editar/', {
            'venta': {'fecha_entrega': str(date.today())}, 'cliente': {'nombre': 'Cliente tres editado'},
        }, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        propia.refresh_from_db()
        self.assertEqual(propia.cliente.nombre, 'Cliente tres editado')


class OrdenAjenaTests(LottusTestCase):
    def setUp(self):
        self.vendedor = self.crear_usuario('seller', role='vendedor')
        self.dueno = self.crear_usuario('owner', role='vendedor')
        self.permisos('vendedor', ['VER_VENTAS', 'VER_ORDENES', 'VER_PROPIAS_ORDENES'])
        self.p1 = self.proveedor()
        self.orden = OrdenPedido.objects.create(
            proveedor=self.p1, usuario=self.dueno, venta=self.venta(self.dueno),
            fecha_esperada=date.today(), costo='750',
        )

    def test_alternate_order_endpoint_bypasses_ownership(self):
        c = self.api(self.vendedor)
        self.assertEqual(c.get(f'/api/ordenes-pedido/{self.orden.pk}/').status_code, 404)
        r = c.get(f'/api/ordenes-pedido/{self.orden.pk}/completo/')
        self.assertEqual(r.status_code, 404)
        self.assertNotIn('costo', getattr(r, 'data', {}) or {})
        r = c.get(f'/api/pedidos/{self.orden.pk}/detalles/')
        self.assertEqual(r.status_code, 404)

    def test_costo_ausente_sin_permiso_en_orden_propia(self):
        propia = OrdenPedido.objects.create(proveedor=self.p1, usuario=self.vendedor, fecha_esperada=date.today(), costo='500')
        c = self.api(self.vendedor)
        for url in (f'/api/ordenes-pedido/{propia.pk}/', f'/api/ordenes-pedido/{propia.pk}/completo/'):
            r = c.get(url)
            self.assertEqual(r.status_code, 200)
            self.assertNotIn('costo', r.data)
        listado = c.get('/api/listar-pedidos/')
        self.assertTrue(all('costo' not in fila for fila in listado.data))


class DetallesOrdenTests(LottusTestCase):
    def setUp(self):
        self.admin = self.crear_usuario('admin', role='administrador')
        self.p1 = self.proveedor('Proveedor ficticio A')
        self.p2 = self.proveedor('Proveedor ficticio B')
        self.ref = self.referencia(self.p1)

    def crear(self, proveedor, detalles):
        return self.api(self.admin).post('/api/ordenes-pedido/', {
            'proveedor': proveedor.pk, 'fecha_esperada': str(date.today()), 'detalles': detalles,
        }, format='json')

    def test_empty_order_is_correctly_rejected(self):
        self.assertEqual(self.crear(self.p1, []).status_code, 400)
        self.assertEqual(OrdenPedido.objects.count(), 0)

    def test_zero_quantity_and_wrong_supplier_reference_accepted(self):
        self.assertEqual(self.crear(self.p2, [{'referencia': self.ref.pk, 'cantidad': 0, 'especificaciones': 'x'}]).status_code, 400)
        self.assertEqual(self.crear(self.p1, [{'referencia': self.ref.pk, 'cantidad': 0, 'especificaciones': 'x'}]).status_code, 400)
        self.assertEqual(self.crear(self.p2, [{'referencia': self.ref.pk, 'cantidad': 1, 'especificaciones': 'x'}]).status_code, 400)
        self.assertEqual(self.crear(self.p1, [{'referencia': self.ref.pk, 'cantidad': -2, 'especificaciones': 'x'}]).status_code, 400)
        self.assertEqual(self.crear(self.p1, [{'referencia': 999999, 'cantidad': 1, 'especificaciones': 'x'}]).status_code, 400)
        self.assertEqual(OrdenPedido.objects.count(), 0)
        self.assertEqual(DetallePedido.objects.count(), 0)

    def test_orden_valida(self):
        r = self.crear(self.p1, [{'referencia': self.ref.pk, 'cantidad': 2, 'especificaciones': 'x'}])
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(DetallePedido.objects.get().cantidad, 2)

    def test_detalle_directo_valida_cantidad_y_proveedor(self):
        orden = OrdenPedido.objects.create(proveedor=self.p1, usuario=self.admin, fecha_esperada=date.today())
        c = self.api(self.admin)
        r = c.post('/api/detalles-pedido/', {'orden': orden.pk, 'referencia': self.ref.pk, 'cantidad': 0, 'especificaciones': 'x'}, format='json')
        self.assertEqual(r.status_code, 400)
        otra = self.referencia(self.p2, 'Otra')
        r = c.post('/api/detalles-pedido/', {'orden': orden.pk, 'referencia': otra.pk, 'cantidad': 1, 'especificaciones': 'x'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(DetallePedido.objects.count(), 0)
