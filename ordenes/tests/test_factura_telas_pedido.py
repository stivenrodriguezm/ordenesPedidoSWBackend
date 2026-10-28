"""(2026-10-28) Al cargar una factura desde un pedido al proveedor, cada línea trae las telas de los
pedidos de tela de esa OP (sin los anulados), con la cantidad por unidad del mueble."""
from datetime import date

from ordenes.models import DetallePedido, OrdenPedido, PedidoTela, ProveedorTela
from ordenes.tests.utils import LottusTestCase


class FacturaTelasDelPedidoTests(LottusTestCase):
    def setUp(self):
        self.admin = self.crear_usuario('admin_ft', 'administrador')
        self.c = self.api(self.admin)
        self.prov = self.proveedor()
        self.ref = self.referencia(self.prov, 'Santorini')
        self.textil = ProveedorTela.objects.create(nombre_empresa='Telas ficticias')
        self.op = OrdenPedido.objects.create(proveedor=self.prov, usuario=self.admin, fecha_esperada=date(2026, 11, 10))
        self.l1 = DetallePedido.objects.create(orden=self.op, referencia=self.ref, cantidad=2, especificaciones='Sofá')
        self.l2 = DetallePedido.objects.create(orden=self.op, referencia=self.ref, cantidad=1, especificaciones='Puff')
        self._pt = 9500

    def pedido_tela(self, *telas, estado='Pendiente', linea=None):
        self._pt += 1
        pt = PedidoTela.objects.create(id=self._pt, usuario=self.admin, proveedor=self.textil, direccion_entrega='Fábrica',
                                       orden_asociada=self.op, estado=estado)
        for tela, cantidad in telas:
            pt.detalles.create(tela=tela, cantidad=cantidad, linea_venta=linea)
        return pt

    def recepcion(self):
        r = self.c.get(f'/api/productos-venta/pedidos/{self.op.pk}/recepcion/')
        self.assertEqual(r.status_code, 200, r.data)
        return {f['detalle_pedido']: f['telas'] for f in r.data['productos']}

    def test_una_tela_por_linea_en_orden_y_por_unidad(self):
        self.pedido_tela(('Lazio - Color: Marfil', '9.00'))
        self.pedido_tela(('[CUERO]Napa - Color: Miel', '120'))
        self.pedido_tela(('Alaska - Color: Gris', '5'), estado=PedidoTela.ANULADO)  # anulado: no cuenta
        telas = self.recepcion()
        self.assertEqual([(t['tipo'], t['referencia'], t['color'], t['cantidad']) for t in telas[self.l1.pk]],
                         [('tela', 'Lazio', 'Marfil', '4.50')])  # 9 m para 2 sofás
        self.assertEqual([(t['tipo'], t['referencia'], t['color'], t['cantidad']) for t in telas[self.l2.pk]],
                         [('cuero', 'Napa', 'Miel', '120.00')])
        # El panel «Pedidos de este proveedor» trae lo mismo.
        filas = self.c.get(f'/api/productos-venta/proveedores/{self.prov.pk}/por-facturar/').data['productos']
        self.assertEqual({f['detalle_pedido']: len(f['telas']) for f in filas}, {self.l1.pk: 1, self.l2.pk: 1})
        # La orden completa (al elegir la OP en una fila) tampoco muestra el pedido anulado.
        asociadas = self.c.get(f'/api/ordenes-pedido/{self.op.pk}/completo/').data['telas_asociadas']
        self.assertEqual(sorted(t['tela'] for t in asociadas), ['Lazio - Color: Marfil', '[CUERO]Napa - Color: Miel'])

    def test_si_no_coinciden_van_con_la_primera_linea_pendiente(self):
        self.pedido_tela(('Lino - Color: Arena', '6'), ('Lino - Color: Gris', '2'), ('Botones', '1'))
        telas = self.recepcion()
        self.assertEqual([t['referencia'] for t in telas[self.l1.pk]], ['Lino', 'Lino', 'Botones'])
        self.assertEqual(telas[self.l2.pk], [])
